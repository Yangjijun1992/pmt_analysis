from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from pmt_analysis.analysis.app import AppAnalysisResult
from pmt_analysis.analysis.dark_count import ChannelDarkCountResult, DarkCountResult
from pmt_analysis.analysis.gain import GainAnalysisResult, GainFitResult
from pmt_analysis.auth import verify_github_user
from pmt_analysis.db.mapping import (
    ChannelNotMappedError,
    ChannelMapping,
    MappingTable,
)
from pmt_analysis.db.models import MeasurementRecord, ensure_schema


class DatabaseWriteError(Exception):
    """Raised when a database write operation fails."""


class DatabaseConnectionError(Exception):
    """Raised when a database connection cannot be established."""


def open_database(db_path: str, timeout: float = 10.0) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(db_path, timeout=timeout)
        conn.execute("PRAGMA journal_mode=WAL")
        ensure_schema(conn)
        return conn
    except sqlite3.Error as e:
        raise DatabaseConnectionError(f"Failed to connect to {db_path}: {e}") from e


def build_channel_lookup(
    dark_result: DarkCountResult,
) -> Dict[tuple, ChannelDarkCountResult]:
    return {
        (ch.board, ch.channel): ch for ch in dark_result.channels
    }


def build_gain_lookup(
    gain_result: GainAnalysisResult,
) -> Dict[tuple, GainFitResult]:
    return {
        (g.board, g.channel): g for g in gain_result.channels
    }


def build_pmt_records(
    mapping: MappingTable,
    dark_result: Optional[DarkCountResult],
    gain_result: Optional[GainAnalysisResult],
    app_result: Optional[AppAnalysisResult],
    run_id: str,
) -> List[MeasurementRecord]:
    dark_lookup = build_channel_lookup(dark_result) if dark_result else {}
    gain_lookup = build_gain_lookup(gain_result) if gain_result else {}

    app_by_board_ch: Dict[tuple, Optional[float]] = {}
    if app_result and app_result.channels:
        for ch_r in app_result.channels:
            key = (ch_r.board, ch_r.channel)
            # Prefer the PE-normalized APP; fall back to the raw APP when
            # SPE gains are unavailable (PE normalization was skipped).
            app_by_board_ch[key] = (
                ch_r.app_value_pe if ch_r.app_value_pe is not None else ch_r.app_value
            )

    records: List[MeasurementRecord] = []
    unmapped: List[str] = []

    for entry in mapping.entries:
        key = (entry.board_id, entry.channel_id)

        dcr = dark_lookup.get(key)
        gr = gain_lookup.get(key)

        dark_count_rate_val = dcr.dark_count_rate_hz if dcr else None
        spe_gain_val = gr.gain_value if gr and gr.fit_success else None
        energy_res = (gr.sigma / gr.gain_value) if gr and gr.fit_success and gr.gain_value else None
        app_val = app_by_board_ch.get(key)

        if dark_count_rate_val is None and spe_gain_val is None and app_val is None:
            continue

        records.append(MeasurementRecord(
            pmt_id=entry.pmt_id,
            board_id=entry.board_id,
            channel_id=entry.channel_id,
            run_id=run_id,
            measurement_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            dark_count_rate=dark_count_rate_val,
            spe_gain=spe_gain_val,
            after_pulse_probability=app_val,
            energy_resolution=energy_res,
        ))

    return records


def dedupe_by_pmt_id(
    conn: sqlite3.Connection,
    records: List[MeasurementRecord],
) -> int:
    """Remove all existing measurement rows whose pmt_id appears in ``records``.

    Enforces global de-duplication by pmt_id: after a write, each pmt_id is
    represented by only the most recent record. The new records are inserted
    after this deletion (they become the latest record for their pmt_id).

    Args:
        conn: Open database connection.
        records: Incoming records whose pmt_ids should be de-duplicated.

    Returns:
        Number of deleted rows.
    """
    if not records:
        return 0
    pmt_ids = sorted({r.pmt_id for r in records})
    placeholders = ",".join("?" * len(pmt_ids))
    sql = f"DELETE FROM measurements WHERE pmt_id IN ({placeholders})"
    try:
        cur = conn.cursor()
        cur.execute(sql, pmt_ids)
        return cur.rowcount
    except sqlite3.Error as e:
        conn.rollback()
        raise DatabaseWriteError(f"Failed to de-duplicate by pmt_id: {e}") from e


def write_measurements(
    conn: sqlite3.Connection,
    records: List[MeasurementRecord],
    dedupe_by_pmt: bool = True,
) -> int:
    if not records:
        return 0

    # Global de-duplication by pmt_id (keep only latest per pmt_id)
    if dedupe_by_pmt:
        n_deleted = dedupe_by_pmt_id(conn, records)
        print(f"  [db] De-duplicated {n_deleted} existing row(s) for {len(records)} pmt_id(s)")

    sql = f"""
        INSERT INTO measurements
            (pmt_id, board_id, channel_id, run_id, measurement_time,
             dark_count_rate, spe_gain, after_pulse_probability, energy_resolution, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    rows = [
        (
            r.pmt_id,
            r.board_id,
            r.channel_id,
            r.run_id,
            r.measurement_time,
            r.dark_count_rate,
            r.spe_gain,
            r.after_pulse_probability,
            r.energy_resolution,
            r.notes,
        )
        for r in records
    ]

    try:
        cursor = conn.cursor()
        cursor.executemany(sql, rows)
        conn.commit()
        return len(rows)
    except sqlite3.Error as e:
        conn.rollback()
        raise DatabaseWriteError(f"Failed to insert {len(rows)} records: {e}") from e


def write_analysis_results(
    db_path: str,
    mapping: MappingTable,
    run_id: str,
    dark_result: Optional[DarkCountResult] = None,
    gain_result: Optional[GainAnalysisResult] = None,
    app_result: Optional[AppAnalysisResult] = None,
    github_user: Optional[str] = None,
    github_token: Optional[str] = None,
) -> int:
    if github_user is None or github_token is None:
        raise DatabaseWriteError(
            "GitHub authentication required for database writes. "
            "Provide --github-user and --github-token."
        )

    verify_github_user(github_user, github_token)
    records = build_pmt_records(
        mapping=mapping,
        dark_result=dark_result,
        gain_result=gain_result,
        app_result=app_result,
        run_id=run_id,
    )

    if not records:
        print(f"[run_id={run_id}] No mapped results to write to database.")
        return 0

    conn = open_database(db_path)
    try:
        count = write_measurements(conn, records)
        print(f"[run_id={run_id}] Wrote {count} measurement records to {db_path}")
        return count
    finally:
        conn.close()
