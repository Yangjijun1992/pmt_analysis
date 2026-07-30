"""Validation plot generation for PMT analysis results.

This module generates verification plots after dark count and SPE gain
analysis, saved to the output directory for user inspection.

All plot functions return the saved file path on success, or None on failure.
Plotting failures are logged but never crash the main pipeline.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from pmt_analysis.analysis.dark_count import DarkCountResult
from pmt_analysis.analysis.gain import GainAnalysisResult

logger = logging.getLogger(__name__)


def _ensure_matplotlib() -> Any:
    """Import matplotlib, raising ImportError with clear message if missing."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except ImportError as e:
        raise ImportError(
            "matplotlib is required for validation plots. "
            "Install it with: pip install matplotlib"
        ) from e


def plot_dark_count_validation(
    result: DarkCountResult,
    output_dir: str | Path,
    run_id: str | int,
    n_bins: int = 60,
    asym_range: Tuple[float, float] = (0.0, 1.0),
) -> Optional[str]:
    """Generate dark count validation plots.

    Produces per-channel asymmetry histograms (one subplot per channel)
    with threshold line.

    Args:
        result: DarkCountResult from analyze_dark_count()
        output_dir: Directory to save the plot
        run_id: Run ID for filename and title
        n_bins: Number of histogram bins
        asym_range: (min, max) range for asymmetry x-axis

    Returns:
        Saved file path, or None if plotting failed
    """
    try:
        plt = _ensure_matplotlib()
    except ImportError as e:
        logger.warning("Skipping dark count plots: %s", e)
        return None

    try:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        filename = f"run{run_id}_dark_count_validation.png"
        filepath = out / filename

        channels = result.channels
        n_ch = len(channels)
        if n_ch == 0:
            return None

        ncols = min(n_ch, 4)
        nrows = (n_ch + ncols - 1) // ncols

        fig, axes = plt.subplots(nrows, ncols, figsize=(3 * ncols, 2.2 * nrows),
                                 squeeze=False)
        fig.suptitle(f"Dark Count Validation — run_id={run_id} "
                     f"(threshold={result.asymmetry_threshold})",
                     fontsize=11)

        for idx, ch in enumerate(channels):
            r = idx // ncols
            c = idx % ncols
            ax = axes[r][c]

            label = f"B{ch.board}Ch{ch.channel}"
            asym_vals = ch.asymmetry_values

            if not asym_vals:
                ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                        ha="center", va="center", fontsize=10, color="gray")
                ax.set_title(label)
                continue

            ax.hist(asym_vals, bins=n_bins, range=asym_range, color="steelblue",
                    edgecolor="white", alpha=0.85)
            ax.axvline(result.asymmetry_threshold, color="red", linestyle="--",
                       linewidth=1.2, alpha=0.8)
            dcr = ch.dark_count_rate_hz if ch.dark_count_rate_hz is not None else 0.0
            ax.set_title(f"{label}  (n={len(asym_vals)}, DCR={dcr:.1f} Hz)",
                         fontsize=8)
            ax.set_xlabel("Asymmetry", fontsize=7)
            ax.set_ylabel("Counts", fontsize=7)
            ax.tick_params(labelsize=7)
            ax.set_xlim(asym_range)

        for idx in range(n_ch, nrows * ncols):
            r = idx // ncols
            c = idx % ncols
            axes[r][c].set_visible(False)

        fig.tight_layout(rect=[0, 0, 1, 0.93])
        fig.savefig(str(filepath), dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Dark count validation plot saved: %s", filepath)
        return str(filepath)

    except Exception as e:
        logger.warning("Failed to generate dark count validation plot: %s", e)
        return None


def plot_dark_count_baseline_2d(
    result: DarkCountResult,
    output_dir: str | Path,
    run_id: str | int,
    n_bins: int = 80,
) -> Optional[str]:
    """Generate per-channel 2D histogram: baseline deviation vs asymmetry.

    Each channel gets its own subplot showing the 2D distribution of
    (record_baseline - local_baseline) vs asymmetry.

    Args:
        result: DarkCountResult from analyze_dark_count()
        output_dir: Directory to save the plot
        run_id: Run ID for filename and title
        n_bins: Number of bins for each axis in the 2D histogram

    Returns:
        Saved file path, or None if plotting failed
    """
    try:
        plt = _ensure_matplotlib()
    except ImportError as e:
        logger.warning("Skipping baseline 2D plot: %s", e)
        return None

    try:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        filename = f"run{run_id}_baseline_2d.png"
        filepath = out / filename

        channels = [ch for ch in result.channels
                    if ch.baseline_deviations and ch.asymmetry_values]
        n_ch = len(channels)
        if n_ch == 0:
            return None

        ncols = min(n_ch, 4)
        nrows = (n_ch + ncols - 1) // ncols

        fig, axes = plt.subplots(nrows, ncols, figsize=(3.5 * ncols, 2.8 * nrows),
                                 squeeze=False)
        fig.suptitle(f"Baseline Deviation vs Asymmetry — run_id={run_id}",
                     fontsize=11)

        for idx, ch in enumerate(channels):
            r = idx // ncols
            c = idx % ncols
            ax = axes[r][c]

            devs = np.array(ch.baseline_deviations)
            asyms = np.array(ch.asymmetry_values)

            if len(devs) == 0 or len(asyms) == 0:
                ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                        ha="center", va="center", fontsize=10, color="gray")
                ax.set_title(f"B{ch.board}Ch{ch.channel}", fontsize=9)
                continue

            ax.hist2d(asyms, devs, bins=n_bins,
                      cmap="jet")
            ax.axhline(0, color="gray", linestyle="--", linewidth=0.6, alpha=0.6)
            ax.axvline(result.asymmetry_threshold, color="red", linestyle="--",
                       linewidth=0.8, alpha=0.7,
                       label=f"asym threshold ({result.asymmetry_threshold})")

            mean_dev = float(np.mean(devs))
            std_dev = float(np.std(devs))
            ax.set_title(f"B{ch.board}Ch{ch.channel} (n={len(devs)})", fontsize=9)
            ax.set_xlabel("Asymmetry", fontsize=7)
            ax.set_ylabel("Baseline Dev (ADC)", fontsize=7)
            ax.tick_params(labelsize=7)
            ax.legend(fontsize=6, loc="upper right")

        for idx in range(n_ch, nrows * ncols):
            r = idx // ncols
            c = idx % ncols
            axes[r][c].set_visible(False)

        fig.tight_layout(rect=[0, 0, 1, 0.93])
        fig.savefig(str(filepath), dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Baseline 2D plot saved: %s", filepath)
        return str(filepath)

    except Exception as e:
        logger.warning("Failed to generate baseline 2D plot: %s", e)
        return None


def plot_spe_gain_validation(
    result: GainAnalysisResult,
    output_dir: str | Path,
    run_id: str | int,
    histogram_counts: Optional[Dict[int, Tuple[np.ndarray, np.ndarray]]] = None,
    fit_params: Optional[Dict[int, Dict[str, float]]] = None,
) -> Optional[str]:
    """Generate SPE gain validation plots.

    Produces two subplots:
      1. Per-channel gain comparison bar chart
      2. First channel's histogram with Gaussian fit overlay (if data provided)

    Args:
        result: GainAnalysisResult from analyze_gain()
        output_dir: Directory to save the plot
        run_id: Run ID for filename and title
        histogram_counts: Optional dict mapping channel -> (counts, edges)
        fit_params: Optional dict mapping channel -> {"amp", "mu", "sigma"}

    Returns:
        Saved file path, or None if plotting failed
    """
    try:
        plt = _ensure_matplotlib()
    except ImportError as e:
        logger.warning("Skipping SPE gain plots: %s", e)
        return None

    try:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        filename = f"run{run_id}_spe_gain_validation.png"
        filepath = out / filename

        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        fig.suptitle(f"SPE Gain Validation — run_id={run_id}", fontsize=13)

        # --- Subplot 1: Per-channel gain bar chart ---
        ax1 = axes[0]
        ch_labels = []
        ch_gains = []
        ch_errors = []
        for ch_fit in result.channels:
            label = f"B{ch_fit.board}Ch{ch_fit.channel}"
            ch_labels.append(label)
            if ch_fit.fit_success and ch_fit.gain_value is not None:
                ch_gains.append(ch_fit.gain_value)
                ch_errors.append(ch_fit.gain_error or 0.0)
            else:
                ch_gains.append(0.0)
                ch_errors.append(0.0)

        if ch_gains:
            x_pos = np.arange(len(ch_gains))
            colors = ["seagreen" if g > 0 else "lightgray" for g in ch_gains]
            ax1.bar(x_pos, ch_gains, yerr=ch_errors, color=colors,
                    edgecolor="white", alpha=0.85, capsize=3)
            ax1.set_xticks(x_pos)
            ax1.set_xticklabels(ch_labels, rotation=45, ha="right", fontsize=8)
            ax1.set_ylabel("SPE Gain (10^6 e^-)")
            ax1.set_title("Per-Channel SPE Gain")
        else:
            ax1.text(0.5, 0.5, "No gain data", transform=ax1.transAxes,
                     ha="center", va="center", fontsize=12, color="gray")
            ax1.set_title("Per-Channel SPE Gain")

        # --- Subplot 2: Histogram + Gaussian fit overlay ---
        ax2 = axes[1]
        plotted = False

        if histogram_counts and fit_params:
            for ch_id in sorted(histogram_counts.keys()):
                if ch_id not in fit_params:
                    continue
                counts, edges = histogram_counts[ch_id]
                params = fit_params[ch_id]
                if not params:
                    continue

                x = 0.5 * (edges[:-1] + edges[1:])
                ax2.hist(x, bins=len(counts), weights=counts, range=(edges[0], edges[-1]),
                         color="steelblue", edgecolor="white", alpha=0.7,
                         label=f"Ch{ch_id} data")

                mu = params.get("mu", 0)
                sigma = params.get("sigma", 1)
                amp = params.get("amp", 1)
                x_fit = np.linspace(max(edges[0], mu - 4 * sigma),
                                    min(edges[-1], mu + 4 * sigma), 200)
                y_fit = amp * np.exp(-0.5 * ((x_fit - mu) / sigma) ** 2)
                ax2.plot(x_fit, y_fit, "r-", linewidth=1.5,
                         label=f"Ch{ch_id} fit: μ={mu:.2f}, σ={abs(sigma):.2f}")

                plotted = True
                break  # Plot only the first channel with valid fit

        if not plotted:
            ax2.text(0.5, 0.5, "No fit data available\nfor histogram overlay",
                     transform=ax2.transAxes, ha="center", va="center",
                     fontsize=11, color="gray")
            ax2.set_title("SPE Spectrum + Gaussian Fit")

        ax2.set_xlabel("Charge (10^6 e^-)")
        ax2.set_ylabel("Counts")
        ax2.set_title("SPE Spectrum + Gaussian Fit")
        if plotted:
            ax2.legend(fontsize=8)

        fig.tight_layout(rect=[0, 0, 1, 0.94])
        fig.savefig(str(filepath), dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("SPE gain validation plot saved: %s", filepath)
        return str(filepath)

    except Exception as e:
        logger.warning("Failed to generate SPE gain validation plot: %s", e)
        return None


def plot_waveform_overlay(
    bundle: Any,
    output_dir: str | Path,
    run_id: str | int,
    board: int = 0,
    n_waveforms: int = 100,
    int_center: int = 110,
    int_left: int = 5,
    int_right: int = 5,
    x_range: Optional[Tuple[int, int]] = None,
) -> Optional[str]:
    """Generate waveform overlay plot for quick inspection.

    Plots the first N waveforms overlaid for each channel on board,
    one subplot per channel. Integration window is marked with vertical
    dashed lines.

    Args:
        bundle: RawDataBundle from NotebookBasedRawDataReader.read()
        output_dir: Directory to save the plot
        run_id: Run ID for filename and title
        board: Board number to plot (default 0)
        n_waveforms: Number of waveforms per channel to overlay (default 100)
        int_center: Center sample index for integration window (default 110)
        int_left: Left half-width of integration window (default 5)
        int_right: Right half-width of integration window (default 5)
        x_range: Optional (start, end) sample range to display on x-axis

    Returns:
        Saved file path, or None if plotting failed
    """
    try:
        plt = _ensure_matplotlib()
    except ImportError as e:
        logger.warning("Skipping waveform overlay plot: %s", e)
        return None

    try:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        filename = f"run{run_id}_waveform_overlay.png"
        filepath = out / filename

        rv = bundle.data
        records = rv.records

        board_mask = records["board"] == board
        channels = sorted(set(records[board_mask]["channel"].tolist()))

        if not channels:
            logger.warning("No channels found for board %d", board)
            return None

        n_ch = len(channels)
        ncols = min(n_ch, 4)
        nrows = (n_ch + ncols - 1) // ncols

        fig, axes = plt.subplots(nrows, ncols, figsize=(3 * ncols, 2.2 * nrows),
                                 squeeze=False)
        fig.suptitle(f"Waveform Overlay — run_id={run_id}, board={board} "
                     f"(first {n_waveforms} per channel)", fontsize=12)

        int_start = int_center - int_left
        int_end = int_center + int_right

        for idx, ch in enumerate(channels):
            r = idx // ncols
            c = idx % ncols
            ax = axes[r][c]

            ch_mask = board_mask & (records["channel"] == ch)
            rec_ids = records[ch_mask]["record_id"][:n_waveforms]

            if len(rec_ids) == 0:
                ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                        ha="center", va="center", fontsize=10, color="gray")
                ax.set_title(f"Ch {ch}")
                continue

            signals = rv.signals(rec_ids)
            waveform_len = signals.shape[1]
            x = np.arange(waveform_len)

            for i in range(signals.shape[0]):
                ax.plot(x, signals[i], color="steelblue", alpha=0.15, linewidth=0.5)

            ax.axvline(int_start, color="red", linestyle="--", linewidth=0.8,
                       alpha=0.7, label=f"int window [{int_start}:{int_end}]")
            ax.axvline(int_end, color="red", linestyle="--", linewidth=0.8, alpha=0.7)

            ax.set_title(f"Ch {ch} ({len(rec_ids)} wfm)", fontsize=9)
            ax.set_xlabel("Sample", fontsize=7)
            ax.set_ylabel("ADC", fontsize=7)
            ax.tick_params(labelsize=7)
            ax.legend(fontsize=6, loc="upper right")
            if x_range is not None:
                ax.set_xlim(x_range)

        for idx in range(n_ch, nrows * ncols):
            r = idx // ncols
            c = idx % ncols
            axes[r][c].set_visible(False)

        fig.tight_layout(rect=[0, 0, 1, 0.94])
        fig.savefig(str(filepath), dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Waveform overlay plot saved: %s", filepath)
        return str(filepath)

    except Exception as e:
        logger.warning("Failed to generate waveform overlay plot: %s", e)
        return None


def plot_area_histogram(
    bundle: Any,
    output_dir: str | Path,
    run_id: str | int,
    board: int = 0,
    n_waveforms: int = 300000,
    center_idx: int = 110,
    win_left: int = 5,
    win_right: int = 5,
    n_bins: int = 50,
    hist_range: Tuple[float, float] = (-10.0, 50.0),
    fit_range: Tuple[float, float] = (3.0, 15.0),
    histogram_counts: Optional[Dict[int, Tuple[np.ndarray, np.ndarray]]] = None,
    fit_params: Optional[Dict[int, Dict[str, float]]] = None,
) -> Optional[str]:
    """Generate per-channel area (charge) distribution histograms.

    Extracts gain samples and plots the area_pe distribution for each
    channel on a separate subplot. If fit_params are provided, overlays
    Gaussian fit curves and marks the fit range with blue dashed lines.

    Args:
        bundle: RawDataBundle from NotebookBasedRawDataReader.read()
        output_dir: Directory to save the plot
        run_id: Run ID for filename and title
        board: Board number to plot (default 0)
        n_waveforms: Max waveforms per channel
        center_idx: Center sample index for integration window
        win_left: Left half-width of integration window
        win_right: Right half-width of integration window
        n_bins: Number of histogram bins
        hist_range: (min, max) range for histogram
        fit_range: (min, max) range for Gaussian fitting
        histogram_counts: Optional dict mapping channel -> (counts, edges)
        fit_params: Optional dict mapping channel -> {"amp", "mu", "sigma"}

    Returns:
        Saved file path, or None if plotting failed
    """
    try:
        plt = _ensure_matplotlib()
    except ImportError as e:
        logger.warning("Skipping area histogram plot: %s", e)
        return None

    try:
        from pmt_analysis.analysis.gain import extract_gain_samples

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        samples_per_ch = extract_gain_samples(
            bundle,
            board=board,
            n_waveforms=n_waveforms,
            center_idx=center_idx,
            win_left=win_left,
            win_right=win_right,
        )

        channels = sorted(samples_per_ch.keys())
        n_ch = len(channels)
        if n_ch == 0:
            return None

        ncols = min(n_ch, 4)
        nrows = (n_ch + ncols - 1) // ncols

        fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 2.5 * nrows),
                                 squeeze=False)
        fig.suptitle(f"Area Distribution \u2014 run_id={run_id}, board={board} "
                     f"(win [{center_idx - win_left}:{center_idx + win_right}])",
                     fontsize=11)

        for idx, ch in enumerate(channels):
            r = idx // ncols
            c = idx % ncols
            ax = axes[r][c]

            samples = samples_per_ch[ch]
            if not samples:
                ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                        ha="center", va="center", fontsize=10, color="gray")
                ax.set_title(f"Ch {ch}")
                continue

            areas = np.array([s.area_pe for s in samples])
            ax.hist(areas, bins=n_bins, range=hist_range, color="steelblue",
                    edgecolor="white", alpha=0.85)

            # Draw Gaussian fit curve if parameters are available
            label = f"Ch {ch} (n={len(samples)})"
            if fit_params and ch in fit_params:
                params = fit_params[ch]
                mu = params.get("mu", 0)
                sigma = params.get("sigma", 1)
                amp = params.get("amp", 1)
                x_fit = np.linspace(hist_range[0], hist_range[1], 500)
                y_fit = amp * np.exp(-0.5 * ((x_fit - mu) / sigma) ** 2)
                ax.plot(x_fit, y_fit, "r-", linewidth=1.5, alpha=0.9,
                        label=f"\u03bc={mu:.2f}, \u03c3={abs(sigma):.2f}")
                label = f"Ch {ch} (n={len(samples)})"
                ax.legend(fontsize=6, loc="upper right")

            # Draw fit range boundaries (blue dashed lines)
            ax.axvline(fit_range[0], color="blue", linestyle="--", linewidth=1.0,
                       alpha=0.7, label=f"fit range [{fit_range[0]},{fit_range[1]}]")
            ax.axvline(fit_range[1], color="blue", linestyle="--", linewidth=1.0, alpha=0.7)

            ax.set_title(label, fontsize=9)
            ax.set_xlabel("Charge (10^6 e^-)", fontsize=7)
            ax.set_ylabel("Counts", fontsize=7)
            ax.tick_params(labelsize=7)
            ax.set_xlim(hist_range)

        for idx in range(n_ch, nrows * ncols):
            r = idx // ncols
            c = idx % ncols
            axes[r][c].set_visible(False)

        fig.tight_layout(rect=[0, 0, 1, 0.93])
        filename = f"run{run_id}_area_histogram.png"
        filepath = out / filename
        fig.savefig(str(filepath), dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Area histogram plot saved: %s", filepath)
        return str(filepath)

    except Exception as e:
        logger.warning("Failed to generate area histogram plot: %s", e)
        return None


def plot_filtered_waveform_overlay(
    bundle: Any,
    output_dir: str | Path,
    run_id: str | int,
    board: int = 0,
    n_waveforms: int = 100,
    int_center: int = 110,
    int_left: int = 5,
    int_right: int = 5,
    x_range: Optional[Tuple[int, int]] = None,
    rms_threshold: float = 50.0,
    n_baseline_points: int = 30,
) -> Optional[str]:
    """Generate filtered waveform overlay plot for SPE Gain analysis.

    Plots the first N waveforms that pass the RMS filtering for each channel
    on board, one subplot per channel. Only waveforms with baseline RMS below
    the threshold are included. Integration window is marked with vertical
    dashed lines.

    Args:
        bundle: RawDataBundle from NotebookBasedRawDataReader.read()
        output_dir: Directory to save the plot
        run_id: Run ID for filename and title
        board: Board number to plot (default 0)
        n_waveforms: Number of waveforms per channel to overlay (default 100)
        int_center: Center sample index for integration window (default 110)
        int_left: Left half-width of integration window (default 5)
        int_right: Right half-width of integration window (default 5)
        x_range: Optional (start, end) sample range to display on x-axis
        rms_threshold: Max allowed baseline RMS (default 50.0)
        n_baseline_points: Number of pre-signal samples for baseline (default 30)

    Returns:
        Saved file path, or None if plotting failed
    """
    try:
        plt = _ensure_matplotlib()
    except ImportError as e:
        logger.warning("Skipping filtered waveform overlay plot: %s", e)
        return None

    try:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        filename = f"run{run_id}_filtered_waveform_overlay.png"
        filepath = out / filename

        rv = bundle.data
        records = rv.records

        board_mask = records["board"] == board
        channels = sorted(set(records[board_mask]["channel"].tolist()))

        if not channels:
            logger.warning("No channels found for board %d", board)
            return None

        n_ch = len(channels)
        ncols = min(n_ch, 4)
        nrows = (n_ch + ncols - 1) // ncols

        fig, axes = plt.subplots(nrows, ncols, figsize=(3 * ncols, 2.2 * nrows),
                                 squeeze=False)
        fig.suptitle(f"Filtered Waveform Overlay — run_id={run_id}, board={board} "
                     f"(first {n_waveforms} per channel, RMS<{rms_threshold})", fontsize=12)

        int_start = int_center - int_left
        int_end = int_center + int_right

        for idx, ch in enumerate(channels):
            r = idx // ncols
            c = idx % ncols
            ax = axes[r][c]

            ch_mask = board_mask & (records["channel"] == ch)
            rec_ids = records[ch_mask]["record_id"][:n_waveforms]

            if len(rec_ids) == 0:
                ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                        ha="center", va="center", fontsize=10, color="gray")
                ax.set_title(f"Ch {ch}")
                continue

            signals = rv.signals(rec_ids)
            waveform_len = signals.shape[1]
            x = np.arange(waveform_len)

            filtered_count = 0
            for i in range(signals.shape[0]):
                wave = signals[i]
                # Compute baseline RMS from first n_baseline_points
                baseline_segment = wave[:n_baseline_points]
                rms_val = float(np.std(baseline_segment))
                
                # Only plot waveforms that pass the RMS filter
                if rms_val <= rms_threshold:
                    ax.plot(x, wave, color="steelblue", alpha=0.15, linewidth=0.5)
                    filtered_count += 1

            ax.axvline(int_start, color="red", linestyle="--", linewidth=0.8,
                       alpha=0.7, label=f"int window [{int_start}:{int_end}]")
            ax.axvline(int_end, color="red", linestyle="--", linewidth=0.8, alpha=0.7)

            ax.set_title(f"Ch {ch} ({filtered_count}/{len(rec_ids)} wfm)", fontsize=9)
            ax.set_xlabel("Sample", fontsize=7)
            ax.set_ylabel("ADC", fontsize=7)
            ax.tick_params(labelsize=7)
            ax.legend(fontsize=6, loc="upper right")
            if x_range is not None:
                ax.set_xlim(x_range)

        for idx in range(n_ch, nrows * ncols):
            r = idx // ncols
            c = idx % ncols
            axes[r][c].set_visible(False)

        fig.tight_layout(rect=[0, 0, 1, 0.94])
        fig.savefig(str(filepath), dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Filtered waveform overlay plot saved: %s", filepath)
        return str(filepath)

    except Exception as e:
        logger.warning("Failed to generate filtered waveform overlay plot: %s", e)
        return None
