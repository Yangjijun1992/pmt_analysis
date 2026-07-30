"""Plotting functions for Afterpulse analysis waveforms."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pmt_analysis.io.raw_reader import RawDataBundle


def plot_afterpulse_waveforms(
    bundle: RawDataBundle,
    channel: int = 0,
    n_waveforms: int = 100,
    output_path: Optional[str] = None,
    x_range: Optional[Tuple[int, int]] = None,
    figsize: Tuple[int, int] = (12, 6),
    baseline_samples: int = 30,
) -> str:
    """Plot overlaid waveforms for a single channel, designed for afterpulse runs.

    Args:
        bundle: Raw data bundle
        channel: Channel number to plot
        n_waveforms: Number of waveforms to overlay
        output_path: Path to save the figure. If None, auto-generated.
        x_range: Optional (start, end) sample range to zoom into.
        figure_size: Figure size (width, height) in inches.
        baseline_samples: Number of initial samples for baseline estimation.

    Returns:
        Path to saved figure.
    """
    rv = bundle.data
    records = rv.records

    ch_records = [(i, r) for i, r in enumerate(records) if int(r["channel"]) == channel]
    n_plot = min(n_waveforms, len(ch_records))

    fig, ax = plt.subplots(figsize=figsize)

    for j in range(n_plot):
        i, r = ch_records[j]
        wave = rv.signals(np.array([int(r["record_id"])]))[0]
        ax.plot(wave, alpha=0.3, linewidth=0.4, color="steelblue")

    if x_range is not None:
        ax.set_xlim(x_range)

    ax.set_title(
        f"Run {bundle.runinfo.run_id} — CH{channel} "
        f"({n_plot} / {len(ch_records)} waveforms)"
    )
    ax.set_xlabel("Sample index")
    ax.set_ylabel("ADC")
    plt.tight_layout()

    if output_path is None:
        output_path = str(
            Path("/mnt/data/PMT/R8520_406/output") / f"run{bundle.runinfo.run_id}_ch{channel}_afterpulse_waves.png"
        )

    fig.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return output_path


def plot_afterpulse_waveforms_bsl_subtracted(
    bundle: RawDataBundle,
    channel: int = 0,
    n_waveforms: int = 100,
    output_path: Optional[str] = None,
    x_range: Optional[Tuple[int, int]] = None,
    figsize: Tuple[int, int] = (12, 6),
    baseline_samples: int = 30,
) -> str:
    """Plot baseline-subtracted waveforms for a single channel.

    Useful for inspecting afterpulse signals after removing DC offset.

    Args:
        bundle: Raw data bundle
        channel: Channel number to plot
        n_waveforms: Number of waveforms to overlay
        output_path: Path to save the figure.
        x_range: Optional (start, end) sample range.
        figure_size: Figure size (width, height) in inches.
        baseline_samples: Number of initial samples for baseline estimation.

    Returns:
        Path to saved figure.
    """
    rv = bundle.data
    records = rv.records

    ch_records = [(i, r) for i, r in enumerate(records) if int(r["channel"]) == channel]
    n_plot = min(n_waveforms, len(ch_records))

    fig, ax = plt.subplots(figsize=figsize)

    for j in range(n_plot):
        i, r = ch_records[j]
        wave = rv.signals(np.array([int(r["record_id"])]))[0]
        bsl = float(np.mean(wave[:baseline_samples]))
        ax.plot(wave - bsl, alpha=0.3, linewidth=0.4, color="steelblue")

    if x_range is not None:
        ax.set_xlim(x_range)

    ax.axhline(y=0, color="gray", linestyle="--", linewidth=0.5)
    ax.set_title(
        f"Run {bundle.runinfo.run_id} — CH{channel} baseline-subtracted "
        f"({n_plot} / {len(ch_records)} waveforms)"
    )
    ax.set_xlabel("Sample index")
    ax.set_ylabel("ADC (baseline-subtracted)")
    plt.tight_layout()

    if output_path is None:
        output_path = str(
            Path("/mnt/data/PMT/R8520_406/output") / f"run{bundle.runinfo.run_id}_ch{channel}_afterpulse_bsl.png"
        )

    fig.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return output_path
