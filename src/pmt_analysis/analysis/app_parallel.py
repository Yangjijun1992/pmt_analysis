"""Multi-process (parallel) APP analysis framework.

The After-Pulse Probability analysis is the most compute-heavy stage of the
pipeline, processing hundreds of thousands to millions of waveforms. The
serial implementation in :mod:`pmt_analysis.analysis.app` loads each waveform
individually via ``rv.signals(record_id)`` and loops over every record once for
main-pulse finding and again for afterpulse finding. This is slow.

This module parallelises the workload using an event-block partition:

1. Bulk-load ALL waveforms once (``rv.signals(bulk_ids)``) into a single
   contiguous numpy array. This removes the per-record I/O bottleneck.
2. Split the event indices into ``n_workers`` contiguous blocks.
3. A ``multiprocessing.Pool`` processes each block in a separate process. Each
   worker finds the main pulses and afterpulse candidates for its block and
   returns per-channel results (channels are subdivided within a block).
4. The parent merges the per-block results, then reuses the existing
   post-processing from :mod:`pmt_analysis.analysis.app` (afterpulse
   selection, SPE-gain normalization, APP computation, and plotting).

Because Linux ``fork`` is used, the bulk-loaded waveform array and the records
structured array are inherited by workers via copy-on-write shared memory — no
expensive pickling of the data is required.
"""
from __future__ import annotations

import multiprocessing as mp
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from pmt_analysis.analysis.app import (
    AfterpulseRecord,
    DEFAULT_AFTERPULSE_MIN_INTERVAL,
    DEFAULT_AMPLITUDE_THRESHOLD,
    DEFAULT_MAIN_PULSE_HEIGHT_THRESHOLD,
    DEFAULT_MIN_INTERVAL_BETWEEN_PULSES,
    MainPulseRecord,
    cal_area,
    compute_app_per_channel,
    load_spe_gains_by_pmt_id,
    normalize_to_pe_per_channel,
    preprocess_waveform,
    select_afterpulses_per_channel,
)
from pmt_analysis.io.raw_reader import RawDataBundle

# ---------------------------------------------------------------------------
# Shared global set by Pool initializer (inherited by workers via fork)
# ---------------------------------------------------------------------------

_GLOBAL = {}


def _init_worker(waveforms: np.ndarray, records: np.ndarray) -> None:
    """Pool initializer: stash the bulk-loaded arrays as module globals.

    Called once per worker process before any task runs. On Linux fork the
    arrays are already shared via copy-on-write; this just exposes them to the
    worker functions without pickling on every task.
    """
    _GLOBAL["waveforms"] = waveforms
    _GLOBAL["records"] = records


# ---------------------------------------------------------------------------
# Bulk loading
# ---------------------------------------------------------------------------


def bulk_load_waveforms(
    bundle: RawDataBundle,
) -> Tuple[np.ndarray, np.ndarray]:
    """Load all waveforms for the run into a single 2D array.

    Flat arrays ``datatype=float32`` padded to the max event length, with
    ``-1.0`` padding. Row ``i`` of the returned array corresponds to record
    row ``i`` of ``bundle.data.records``.

    Returns:
        (waveforms, records) where waveforms is (n_events, max_len) float32
        and records is the structured records array aligned by row index.
    """
    rv = bundle.data
    records = rv.records
    record_ids = records["record_id"].astype(np.int64)

    waveforms: np.ndarray = rv.signals(record_ids)  # bulk load once
    if waveforms.ndim != 2:
        # signals may return a flat / ragged representation; normalise to 2D
        lengths = records["event_length"].astype(np.int64)
        max_len = int(lengths.max()) if lengths.size else 0
        out = np.full((len(records), max_len), -1.0, dtype=np.float32)
        idx = 0
        for i in range(len(records)):
            ln = int(lengths[i])
            out[i, :ln] = waveforms[idx:idx + ln]
            idx += ln
        waveforms = out

    # Convert to float32 copy (defensive; ensures contiguous shareable layout)
    waveforms = np.ascontiguousarray(waveforms, dtype=np.float32)
    return waveforms, records


# ---------------------------------------------------------------------------
# Per-event (block) processing
# ---------------------------------------------------------------------------


def _find_main_pulses_in_block(
    waveforms: np.ndarray,
    records: np.ndarray,
    indices: np.ndarray,
    height_threshold: float,
) -> Dict[Tuple[int, int], List[MainPulseRecord]]:
    """Find main pulses for the given event block, one waveform per row."""
    grouped: Dict[Tuple[int, int], List[MainPulseRecord]] = {}

    for idx in indices:
        rec = records[idx]
        board = int(rec["board"])
        channel = int(rec["channel"])
        record_id = int(rec["record_id"])

        wave = waveforms[idx]
        # Trim trailing -1 padding (ragged length handling)
        processed, baseline = preprocess_waveform(wave)

        min_idx = int(np.argmin(processed))
        pulse_height = abs(float(processed[min_idx]))
        if pulse_height < height_threshold:
            continue

        start_idx = min_idx
        while start_idx > 0:
            if processed[start_idx] > processed[start_idx - 1]:
                break
            start_idx -= 1

        end_idx = min_idx
        baseline_threshold = 50.0
        baseline_return_count = 0
        baseline_return_needed = 3
        while end_idx < len(processed) - 1:
            end_idx += 1
            if abs(processed[end_idx]) < baseline_threshold:
                baseline_return_count += 1
                if baseline_return_count >= baseline_return_needed:
                    break
            else:
                baseline_return_count = 0

        charge = cal_area(processed, start_idx, end_idx + 1, 0.0)

        mp_rec = MainPulseRecord(
            event_index=int(idx),
            channel_index=channel,
            sample_index=min_idx,
            height=pulse_height,
            charge=charge,
            start=start_idx,
            end=end_idx + 1,
            baseline=baseline,
            metadata={"board": board, "record_id": record_id},
        )

        key = (board, channel)
        grouped.setdefault(key, []).append(mp_rec)

    return grouped


def _find_afterpulse_candidates_in_block(
    waveforms: np.ndarray,
    records: np.ndarray,
    indices: np.ndarray,
    mp_by_record: Dict[int, List[MainPulseRecord]],
    amplitude_threshold: float,
    afterpulse_min_interval: int,
) -> Dict[Tuple[int, int], List[AfterpulseRecord]]:
    """Find afterpulse candidates for the given block, one waveform per row.

    ``mp_by_record`` maps record_id -> list of MainPulseRecord for records
    that have main pulses globally.
    """
    grouped: Dict[Tuple[int, int], List[AfterpulseRecord]] = {}

    for idx in indices:
        rec = records[idx]
        record_id = int(rec["record_id"])
        board = int(rec["board"])
        channel = int(rec["channel"])

        mp_list = mp_by_record.get(record_id)
        if not mp_list:
            continue

        wave = waveforms[idx]
        processed, _baseline = preprocess_waveform(wave)

        for mp in mp_list:
            if mp.end is None:
                continue

            search_start = mp.end + afterpulse_min_interval
            if search_start >= len(processed):
                continue

            ref_points: List[int] = []
            above_threshold = False
            for j in range(search_start, len(processed)):
                if processed[j] < -amplitude_threshold:
                    if not above_threshold:
                        ref_points.append(j)
                        above_threshold = True
                else:
                    above_threshold = False

            # filter_points min_interval=2 (deduplicate adjacent crossings)
            filtered: List[int] = []
            last: Optional[int] = None
            for rp in ref_points:
                if last is None or rp - last >= 2:
                    filtered.append(rp)
                    last = rp

            ch_key = (board, channel)
            dt_ns = float(rec["dt"])
            pulse_idx = 1

            for ref_idx in filtered:
                try:
                    st, minp, ed = _findpulse_st_ed(processed, ref_idx)
                except Exception:
                    continue
                if ed < st:
                    continue
                pulse_height = abs(float(processed[minp]))
                if pulse_height < amplitude_threshold:
                    continue
                charge = cal_area(processed, st, ed + 1, 0.0)
                delay_start = st - (mp.end if mp.end else 0)
                ap = AfterpulseRecord(
                    event_index=mp.event_index,
                    channel_index=channel,
                    delay_time=float(delay_start * dt_ns),
                    height=pulse_height,
                    charge=charge,
                    start=st,
                    end=ed + 1,
                    min_point=minp,
                    metadata={
                        "board": board,
                        "record_id": record_id,
                        "pulse_index": pulse_idx,
                        "main_pulse_end": mp.end,
                        "dt_ns": dt_ns,
                    },
                )
                grouped.setdefault(ch_key, []).append(ap)
                pulse_idx += 1

    return grouped


def _findpulse_st_ed(
    waveform: np.ndarray,
    reference_point: int,
    search_range: int = 5,
) -> Tuple[int, int, int]:
    """Local re-implementation of app.findpulse_st_ed (avoids circular import
    of low-level helpers and keeps worker modules self-contained)."""
    start_range = max(0, reference_point - search_range)
    end_range = min(len(waveform), reference_point + search_range)

    min_index = reference_point
    min_value = waveform[reference_point]
    for i in range(start_range, end_range):
        if waveform[i] < min_value:
            min_value = waveform[i]
            min_index = i

    start_index = min_index
    while start_index > start_range:
        if (waveform[start_index] - waveform[start_index - 1]) < 0:
            start_index -= 1
        else:
            break

    end_index = min_index
    if end_index + 1 < end_range and waveform[min_index] == waveform[end_index + 1]:
        end_index += 1
    while end_index + 1 < end_range:
        if (waveform[end_index + 1] - waveform[end_index]) > 0:
            end_index += 1
        else:
            break

    return start_index, min_index, end_index


@dataclass
class BlockResult:
    """Per-block result: main pulses and afterpulse candidates per channel."""

    main_pulses: Dict[Tuple[int, int], List[MainPulseRecord]] = field(default_factory=dict)
    afterpulses: Dict[Tuple[int, int], List[AfterpulseRecord]] = field(default_factory=dict)


def _process_block(task: Tuple[List[int], float, float, int]) -> BlockResult:
    """Run main-pulse + afterpulse-candidate finding for one event block.

    Uses the shared global arrays populated by ``_init_worker``. This is a
    module-level function so it is picklable for multiprocessing.

    Args:
        task: (block_indices, height_threshold, amplitude_threshold,
              afterpulse_min_interval).
    """
    block_indices, height_threshold, amplitude_threshold, afterpulse_min_interval = task
    waveforms = _GLOBAL["waveforms"]
    records = _GLOBAL["records"]
    indices = np.asarray(block_indices, dtype=np.int64)

    # Pass 1: main pulses in this block
    main = _find_main_pulses_in_block(
        waveforms, records, indices, height_threshold,
    )

    # Pass 2: afterpulse candidates in this block, using ONLY the main pulses
    # found in THIS block (each record belongs to exactly one block, so there
    # is no cross-block main-pulse dependency).
    mp_by_record: Dict[int, List[MainPulseRecord]] = {}
    for (board, channel), pulses in main.items():
        for mp in pulses:
            rid = mp.metadata.get("record_id")
            if rid is not None:
                mp_by_record.setdefault(rid, []).append(mp)

    after = _find_afterpulse_candidates_in_block(
        waveforms, records, indices, mp_by_record,
        amplitude_threshold, afterpulse_min_interval,
    )

    return BlockResult(main_pulses=main, afterpulses=after)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _merge_block_results(
    results: Sequence[BlockResult],
) -> Tuple[Dict[Tuple[int, int], List[MainPulseRecord]],
           Dict[Tuple[int, int], List[AfterpulseRecord]]]:
    main_all: Dict[Tuple[int, int], List[MainPulseRecord]] = {}
    after_all: Dict[Tuple[int, int], List[AfterpulseRecord]] = {}
    for br in results:
        for key, pulses in br.main_pulses.items():
            main_all.setdefault(key, []).extend(pulses)
        for key, aps in br.afterpulses.items():
            after_all.setdefault(key, []).extend(aps)
    # Deterministic order
    for key in main_all:
        main_all[key].sort(key=lambda m: (m.event_index or 0, m.sample_index or 0))
    for key in after_all:
        after_all[key].sort(key=lambda a: (a.event_index or 0, a.start or 0))
    return main_all, after_all


def analyze_app_parallel(
    bundle: RawDataBundle,
    n_workers: Optional[int] = None,
    main_pulse_height_threshold: float = DEFAULT_MAIN_PULSE_HEIGHT_THRESHOLD,
    amplitude_threshold: float = DEFAULT_AMPLITUDE_THRESHOLD,
    afterpulse_min_interval: int = DEFAULT_AFTERPULSE_MIN_INTERVAL,
    min_interval_between_pulses: int = DEFAULT_MIN_INTERVAL_BETWEEN_PULSES,
    pmt_id_map: Optional[Dict[Tuple[int, int], str]] = None,
) -> Any:
    """Run the full APP analysis using a multi-process event-block partition.

    Steps:
        1. Bulk-load all waveforms once.
        2. Partition events into ``n_workers`` blocks.
        3. Parallel find main pulses + afterpulse candidates per block.
        4. Merge, select afterpulses, normalize to PE, compute APP.

    Args:
        bundle: Raw data bundle.
        n_workers: Number of worker processes. Defaults to
            ``min(max(1, os.cpu_count()-1), n_blocks)``.
        pmt_id_map: Optional board/channel -> pmt_id mapping for SPE gains.

    Returns:
        :class:`pmt_analysis.analysis.app.AppAnalysisResult`.
    """
    from pmt_analysis.analysis.app import AppAnalysisResult

    waveforms, records = bulk_load_waveforms(bundle)

    n_events = len(records)
    if n_events == 0:
        return AppAnalysisResult()

    if n_workers is None:
        n_workers = max(1, (os.cpu_count() or 1) - 1)

    # Build contiguous event blocks (balanced sizes)
    block_size = max(1, int(np.ceil(n_events / n_workers)))
    n_actual_blocks = max(1, int(np.ceil(n_events / block_size)))
    n_workers = min(n_workers, n_actual_blocks)

    blocks: List[List[int]] = []
    for b in range(n_actual_blocks):
        start = b * block_size
        end = min(n_events, start + block_size)
        blocks.append(list(range(start, end)))

    print(f"  [parallel] events={n_events}, blocks={len(blocks)}, workers={n_workers}")

    pool = mp.Pool(
        processes=n_workers,
        initializer=_init_worker,
        initargs=(waveforms, records),
    )
    tasks = [
        (
            block,
            main_pulse_height_threshold,
            amplitude_threshold,
            afterpulse_min_interval,
        )
        for block in blocks
    ]
    try:
        block_results = pool.map(_process_block, tasks)
    finally:
        pool.close()
        pool.join()

    main_all, after_all = _merge_block_results(block_results)

    # ---- Reuse existing post-processing ----------------
    selected_after = select_afterpulses_per_channel(
        after_all, min_interval=min_interval_between_pulses,
    )

    spe_gains: Dict[Tuple[int, int], float] = {}
    if pmt_id_map:
        spe_gains = load_spe_gains_by_pmt_id(pmt_id_map)

    normalize_to_pe_per_channel(main_all, selected_after, spe_gains)

    channel_results = compute_app_per_channel(main_all, selected_after, spe_gains)

    total_main = sum(ch_r.main_pulse_count for ch_r in channel_results)
    total_ap = sum(ch_r.afterpulse_count for ch_r in channel_results)
    total_ap_candidates = sum(len(after_all.get((ch_r.board, ch_r.channel), []))
                              for ch_r in channel_results)
    total_main_with_ap = sum(ch_r.main_pulse_with_afterpulse_count
                             for ch_r in channel_results)

    app_raw = None
    app_pe = None
    total_main_charge = sum(ch_r.main_pulse_charge for ch_r in channel_results)
    total_ap_charge = sum(ch_r.afterpulse_charge for ch_r in channel_results)
    if total_main_charge > 0:
        app_raw = total_ap_charge / total_main_charge
    total_main_charge_pe = sum(ch_r.main_pulse_charge_pe for ch_r in channel_results)
    total_ap_charge_pe = sum(ch_r.afterpulse_charge_pe for ch_r in channel_results)
    if total_main_charge_pe > 0:
        app_pe = total_ap_charge_pe / total_main_charge_pe

    return AppAnalysisResult(
        channels=channel_results,
        main_pulse_count=total_main,
        afterpulse_candidate_count=total_ap_candidates,
        afterpulse_count=total_ap,
        main_pulse_with_afterpulse_count=total_main_with_ap,
        app_value=app_raw,
        app_value_pe=app_pe,
        metadata={
            "parallel": True,
            "n_workers": n_workers,
            "n_blocks": len(blocks),
            "noise_suppression_enabled": False,
        },
    )
