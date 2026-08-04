"""SPE (Single Photo-Electron) Gain Analysis Module.

This module implements SPE gain analysis for PMT waveforms based on the
reference notebook: example_code/pmt_gain_example.ipynb

Analysis Logic Summary:
    1. Extract gain samples from raw waveforms:
       - Baseline correction: mean of first 30 samples
       - RMS filtering: skip waveforms with RMS > 4
        - Integration window: sample 105 ~ 115 (symmetric, 10 samples)
       - Area calculation: -sum(window - baseline) * pe_fact
       - pe_fact = (2/16384) * 4e-9 / (50 * 1.6e-19) / 1e6

    2. Build histogram:
       - bins=100, range=(-15, 100)

    3. Fit SPE spectrum with single Gaussian:
       - gaussian(x, amp, mu, sigma) = amp * exp(-0.5 * ((x - mu) / sigma)^2)
       - Initial guess: mu_init=10.0, sigma_init=2.0
       - Fit range: (5, 20)
       - Bounds: mu_bounds=(0.1, 30), sigma_bounds=(0, 12), amp_bounds=(100, 1e5)

    4. Gain = mu (SPE peak position from Gaussian fit)

Dependencies:
    - numpy
    - scipy (for curve_fit)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from pmt_analysis.analysis.gain_fit_models import (
    DEFAULT_FIT_MODEL,
    FIT_MODELS,
    fit_spectrum,
)
from pmt_analysis.io.raw_reader import RawDataBundle

# PE conversion factor from notebook
# Converts ADC counts to photoelectrons (in units of 10^6 e^-)
PE_FACT = (2.0 / 16384.0) * 4.0e-9 / (50.0 * 1.6e-19) / 1.0e6


@dataclass
class GainSample:
    """Single pulse gain measurement."""

    record_id: int
    board: int
    channel: int
    baseline: float
    rms: float
    raw_area: float
    area_pe: float


@dataclass
class GainFitResult:
    """Result of Gaussian fit to SPE spectrum."""

    board: int
    channel: int
    fit_success: bool
    gain_value: Optional[float] = None  # mu from fit (in PE units)
    sigma: Optional[float] = None
    amplitude: Optional[float] = None
    gain_error: Optional[float] = None
    sigma_error: Optional[float] = None
    amplitude_error: Optional[float] = None
    sample_count: int = 0
    fit_parameters: Dict[str, float] = field(default_factory=dict)
    histogram_counts: Optional[np.ndarray] = None
    histogram_edges: Optional[np.ndarray] = None
    fit_model: str = DEFAULT_FIT_MODEL
    resolution: Optional[float] = None
    fit_curve_x: Optional[np.ndarray] = None
    fit_curve_y: Optional[np.ndarray] = None
    raw_params: Optional[np.ndarray] = None
    raw_errors: Optional[np.ndarray] = None


@dataclass
class GainAnalysisResult:
    """Complete SPE gain analysis result."""

    channels: List[GainFitResult] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


def extract_gain_samples(
    bundle: RawDataBundle,
    board: int = 0,
    channels: Optional[List[int]] = None,
    n_waveforms: int = 300000,
    n_baseline_points: int = 30,
    center_idx: int = 95,
    win_left: int = 5,
    win_right: int = 5,
    rms_threshold: float = 50.0,
) -> Dict[int, List[GainSample]]:
    """Extract gain samples from raw waveforms for specified channels.

    Args:
        bundle: Raw data bundle containing records and waveforms
        board: Board ID to analyze
        channels: List of channel IDs (default: auto-detect from data)
        n_waveforms: Max number of waveforms to process per channel
        n_baseline_points: Number of pre-signal samples for baseline
        center_idx: Center sample index for integration window
        win_left: Left half-width of integration window (samples before center)
        win_right: Right half-width of integration window (samples after center)
        rms_threshold: Max allowed baseline RMS (waveforms above are skipped)

    Returns:
        Dictionary mapping channel ID to list of GainSample objects
    """
    rv = bundle.data
    records = rv.records

    # Auto-detect channels if not specified
    if channels is None:
        board_mask = records["board"] == board
        channels = sorted(set(records[board_mask]["channel"].tolist()))

    win_start = center_idx - win_left
    win_end = center_idx + win_right

    result: Dict[int, List[GainSample]] = {}

    for ch in channels:
        # Select record IDs for this board/channel
        mask = (records["board"] == board) & (records["channel"] == ch)
        rec_ids = records[mask]["record_id"][:n_waveforms]

        if len(rec_ids) == 0:
            result[ch] = []
            continue

        # Load waveforms
        signals = rv.signals(rec_ids)
        samples: List[GainSample] = []

        for i in range(signals.shape[0]):
            wave = signals[i]

            # Compute baseline and RMS from first n_baseline_points
            baseline_segment = wave[:n_baseline_points]
            rms_val = float(np.std(baseline_segment))

            # Skip noisy waveforms
            if rms_val > rms_threshold:
                continue

            baseline_val = float(np.mean(baseline_segment))

            # Integrate around center sample
            win_seg = wave[win_start:win_end]
            raw_area = -float(np.sum(win_seg - baseline_val))
            area_pe = raw_area * PE_FACT

            samples.append(
                GainSample(
                    record_id=int(rec_ids[i]),
                    board=board,
                    channel=ch,
                    baseline=baseline_val,
                    rms=rms_val,
                    raw_area=raw_area,
                    area_pe=area_pe,
                )
            )

        result[ch] = samples

    return result


def build_spe_histogram(
    samples: List[GainSample],
    bins: int = 100,
    hist_range: Tuple[float, float] = (-10.0, 40.0),
) -> Tuple[np.ndarray, np.ndarray]:
    """Build histogram of SPE area values.

    Args:
        samples: List of GainSample objects
        bins: Number of histogram bins
        hist_range: (min, max) range for histogram

    Returns:
        Tuple of (counts, edges) arrays
    """
    data = np.array([s.area_pe for s in samples])
    counts, edges = np.histogram(data, bins=bins, range=hist_range)
    return counts, edges


def fit_spe_spectrum(
    counts: np.ndarray,
    edges: np.ndarray,
    mu_init: float = 10.0,
    sigma_init: float = 2.0,
    fit_range: Tuple[float, float] = (3.0, 15.0),
    mu_bounds: Tuple[float, float] = (0.1, 30.0),
    sigma_bounds: Tuple[float, float] = (0.0, 12.0),
    amp_bounds: Tuple[float, float] = (100.0, 1e5),
) -> Tuple[Optional[Dict[str, float]], Optional[Dict[str, float]]]:
    """Fit single Gaussian to SPE spectrum.

    Args:
        counts: Histogram counts
        edges: Histogram bin edges
        mu_init: Initial guess for Gaussian mean
        sigma_init: Initial guess for Gaussian sigma
        fit_range: (min, max) range for fitting
        mu_bounds: (lower, upper) bounds for mu
        sigma_bounds: (lower, upper) bounds for sigma
        amp_bounds: (lower, upper) bounds for amplitude

    Returns:
        Tuple of (params_dict, errors_dict) or (None, None) if fit fails
    """
    try:
        from scipy.optimize import curve_fit
    except ImportError:
        raise ImportError(
            "scipy is required for SPE gain fitting. "
            "Install it with: pip install scipy"
        )

    def gaussian(x: np.ndarray, amp: float, mu: float, sigma: float) -> np.ndarray:
        return amp * np.exp(-0.5 * ((x - mu) / sigma) ** 2)

    # Compute bin centers
    x = 0.5 * (edges[:-1] + edges[1:])
    y = np.array(counts, dtype=float)

    # Apply fit range
    mask = (x >= fit_range[0]) & (x <= fit_range[1])
    x_fit, y_fit = x[mask], y[mask]

    if len(x_fit) == 0:
        return None, None

    # Initial parameters
    amp_init = float(y_fit.max())
    mu_actual = float(x_fit[np.argmax(y_fit)])
    sigma_actual = (x_fit[-1] - x_fit[0]) / 10.0

    # Ensure initial guess is within bounds
    mu_actual = max(mu_bounds[0], min(mu_bounds[1], mu_actual))
    sigma_actual = max(sigma_bounds[0], min(sigma_bounds[1], sigma_actual))
    amp_init = max(amp_bounds[0], min(amp_bounds[1], amp_init))

    p0 = [amp_init, mu_actual, sigma_actual]

    # Build bounds
    lo = [amp_bounds[0], mu_bounds[0], sigma_bounds[0]]
    hi = [amp_bounds[1], mu_bounds[1], sigma_bounds[1]]

    try:
        popt, pcov = curve_fit(gaussian, x_fit, y_fit, p0=p0, bounds=(lo, hi), maxfev=10000)
        perr = np.sqrt(np.diag(pcov))

        params = {"amp": float(popt[0]), "mu": float(popt[1]), "sigma": abs(float(popt[2]))}
        errors = {"amp": float(perr[0]), "mu": float(perr[1]), "sigma": float(perr[2])}
        return params, errors

    except RuntimeError:
        return None, None


def compute_gain_value(fit_result: GainFitResult) -> Optional[float]:
    """Extract gain value from fit result.

    The gain is defined as the SPE peak position (mu) from the Gaussian fit,
    in units of 10^6 e^- (photoelectrons).

    Args:
        fit_result: GainFitResult object

    Returns:
        Gain value (mu) or None if fit failed
    """
    return fit_result.gain_value


def _reconstruct_curve(
    model: str,
    params: np.ndarray,
    counts: np.ndarray,
    edges: np.ndarray,
    kmax: int = 30,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """Rebuild the fitted model curve over the histogram bin centers.

    Returns ``(x, curve_y)`` or ``(None, None)`` if curve reconstruction fails.
    """
    if params is None or len(params) == 0:
        return None, None
    try:
        x = 0.5 * (edges[:-1] + edges[1:])
        if model == "single_fit":
            amp, mu, sigma = params
            y = amp * np.exp(-0.5 * ((x - mu) / sigma) ** 2)
        elif model == "multi_gauss_fit":
            from pmt_analysis.analysis.gain_fit_models import four_gauss
            y = four_gauss(x, *params)
        elif model == "poisson_fit":
            from pmt_analysis.analysis.gain_fit_models import gauss_poisson
            y = gauss_poisson(x, *params, kmax=kmax)
        else:
            return None, None
        return x.astype(float), np.asarray(y, dtype=float)
    except Exception:
        return None, None


def analyze_gain(
    bundle: RawDataBundle,
    board: int = 0,
    channels: Optional[List[int]] = None,
    n_waveforms: int = 300000,
    fit_model: str = DEFAULT_FIT_MODEL,
    **model_kwargs,
) -> GainAnalysisResult:
    """Perform complete SPE gain analysis on a RawDataBundle.

    This is the main entry point for gain analysis.

    Args:
        bundle: Raw data bundle
        board: Board ID to analyze
        channels: List of channel IDs (default: auto-detect from data)
        n_waveforms: Max waveforms per channel
        fit_model: One of "single_fit", "multi_gauss_fit", "poisson_fit".
            Defaults to "multi_gauss_fit".
        **model_kwargs: Extra keywords forwarded to the selected fit model
            (e.g. bins, hist_range, n_peaks, kmax).

    Returns:
        GainAnalysisResult with fit results for each channel
    """
    if fit_model not in FIT_MODELS:
        raise ValueError(
            f"Unknown fit_model {fit_model!r}. Choose from {sorted(FIT_MODELS)}"
        )

    rv = bundle.data
    records = rv.records

    # Auto-detect channels if not specified
    if channels is None:
        board_mask = records["board"] == board
        channels = sorted(set(records[board_mask]["channel"].tolist()))

    # Extract gain samples
    samples_per_ch = extract_gain_samples(
        bundle,
        board=board,
        channels=channels,
        n_waveforms=n_waveforms,
    )

    channel_results: List[GainFitResult] = []

    for ch in channels:
        samples = samples_per_ch.get(ch, [])

        if len(samples) < 10:
            counts, edges = build_spe_histogram(samples)
            channel_results.append(
                GainFitResult(
                    board=board,
                    channel=ch,
                    fit_success=False,
                    sample_count=len(samples),
                    fit_model=fit_model,
                    histogram_counts=counts,
                    histogram_edges=edges,
                )
            )
            continue

        # Raw area_pe values (in PE units)
        values = np.array([s.area_pe for s in samples], dtype=float)

        # Fit SPE spectrum with the selected model
        try:
            result = fit_spectrum(values, fit_model=fit_model, **model_kwargs)
        except Exception:
            result = None

        if result is not None and np.isfinite(result.get("gain", np.nan)):
            params = {
                "mu": float(result["gain"]),
                "sigma": float(result["sigma"]),
                "amp": float(result["amplitude"]),
                "model": fit_model,
                "resolution": result.get("resolution"),
            }
            errors = {
                "mu": float(result["gain_error"]),
                "sigma": float(result["sigma_error"]),
                "amp": float(result["amplitude_error"]),
            }
            counts = np.asarray(result["counts"])
            edges = np.asarray(result["edges"])
            raw_params = result.get("params")
            raw_errors = result.get("errors")
            curve_x, curve_y = _reconstruct_curve(
                fit_model, raw_params, counts, edges, kmax=model_kwargs.get("kmax", 30)
            )
            channel_results.append(
                GainFitResult(
                    board=board,
                    channel=ch,
                    fit_success=True,
                    gain_value=params["mu"],
                    sigma=params["sigma"],
                    amplitude=params["amp"],
                    gain_error=errors["mu"],
                    sigma_error=errors["sigma"],
                    amplitude_error=errors["amp"],
                    sample_count=len(samples),
                    fit_parameters=params,
                    histogram_counts=counts,
                    histogram_edges=edges,
                    fit_model=fit_model,
                    resolution=result.get("resolution"),
                    fit_curve_x=curve_x,
                    fit_curve_y=curve_y,
                    raw_params=raw_params,
                    raw_errors=raw_errors,
                )
            )
        else:
            # On fit failure still store the histogram for diagnostics/plotting.
            counts, edges = build_spe_histogram(samples)
            channel_results.append(
                GainFitResult(
                    board=board,
                    channel=ch,
                    fit_success=False,
                    sample_count=len(samples),
                    fit_model=fit_model,
                    histogram_counts=counts,
                    histogram_edges=edges,
                )
            )

    return GainAnalysisResult(
        channels=channel_results,
        metadata={
            "run_id": bundle.runinfo.run_id,
            "runtype": bundle.runinfo.runtype,
            "board": board,
            "fit_model": fit_model,
        },
    )
