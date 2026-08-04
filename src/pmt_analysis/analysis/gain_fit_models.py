"""SPE gain spectrum fit models.

Three interchangeable fit models for PMT single-photoelectron (SPE) charge
spectra.  Each model takes the raw charge values (``area_pe``, in units of
10^6 e^-) and returns a common result dict plus model-specific keys.

Models
------
``single_fit``       single Gaussian    : SPE peak only
``multi_gauss_fit``  pedestal + 1/2/3-PE Gaussians   (default)
``poisson_fit``      Gaussian-convolved Poisson       (amplitudes tied by mu_pe)

The analytic model functions ``three_gauss``/``four_gauss`` and
``gauss_poisson`` are self-contained ports of ``example_code/fit_package.py``;
the robust seed/fitting strategy follows ``robust_multi_gauss_fit`` and
``gauss_poisson_fit`` as used in ``compare_gain_fits_00296.ipynb``.

Result dict keys (common to all models)
---------------------------------------
gain, gain_error, sigma, sigma_error, amplitude, amplitude_error,
resolution, params, errors, x, counts, edges
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import least_squares
from scipy.signal import find_peaks
from scipy.stats import poisson

# Default histogram parameters shared by the multi-Gaussian & Poisson models.
DEFAULT_BINS = 120
DEFAULT_HIST_RANGE = (-10.0, 80.0)

# Default single-Gaussian fitting parameters (matching the legacy gain.py).
SINGLE_MEAN_INIT = 10.0
SINGLE_SIGMA_INIT = 2.0
SINGLE_FIT_RANGE = (3.0, 15.0)
SINGLE_MEAN_BOUNDS = (0.1, 30.0)
SINGLE_SIGMA_BOUNDS = (0.0, 12.0)
SINGLE_AMP_BOUNDS = (100.0, 1e5)

PMAX_KMAX = 30


# ---------------------------------------------------------------------------
# Shared helpers (ports of fit_package internals)
# ---------------------------------------------------------------------------
def _poisson_deviance_residual(observed, expected):
    """Signed square-root Poisson deviance residual (weight for the fit)."""
    expected = np.clip(np.asarray(expected, dtype=float), 1e-12, None)
    observed = np.asarray(observed, dtype=float)
    term = expected - observed
    positive = observed > 0
    term[positive] += observed[positive] * np.log(
        observed[positive] / expected[positive]
    )
    return np.sign(observed - expected) * np.sqrt(np.maximum(2 * term, 0))


def _peak_width_from_hist(x, smooth_y, peak_index, bin_width, default):
    """Estimate sigma from the half-height width of a smoothed peak."""
    half_height = 0.5 * smooth_y[peak_index]
    left = right = peak_index
    while left > 0 and smooth_y[left] > half_height:
        left -= 1
    while right < len(smooth_y) - 1 and smooth_y[right] > half_height:
        right += 1
    if left == 0 or right == len(smooth_y) - 1:
        return default
    return max((x[right] - x[left]) / 2.355, 0.5 * bin_width)


def _hist(values, bins, hist_range):
    """Return (counts, edges, bin_centers, bin_width) from raw charge values."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    counts, edges = np.histogram(values, bins=bins, range=hist_range)
    x = 0.5 * (edges[:-1] + edges[1:])
    bin_width = edges[1] - edges[0]
    return counts, edges, x, bin_width


def _seed_from_hist(x, counts, hist_range):
    """Robust starting points for pedestal position/width and gain."""
    smooth = gaussian_filter1d(counts.astype(float), sigma=1.2)
    bin_width = x[1] - x[0]

    ped_mask = (x >= max(hist_range[0], -5)) & (x <= min(hist_range[1], 5))
    ped_indices = np.flatnonzero(ped_mask)
    ped_index = ped_indices[np.argmax(smooth[ped_mask])]
    mu0_seed = float(x[ped_index])
    sigma0_seed = float(np.clip(
        _peak_width_from_hist(x, smooth, ped_index, bin_width, 1.2), 0.4, 3.0
    ))

    gain_low = max(3.0, 2.5 * sigma0_seed)
    gain_high = min(30.0, (hist_range[1] - mu0_seed) / 3.0)
    spe_mask = (x >= mu0_seed + gain_low) & (x <= mu0_seed + gain_high)
    spe_indices = np.flatnonzero(spe_mask)
    if spe_indices.size == 0:
        gain_candidates = [float(np.clip(8.0, gain_low, gain_high))]
    else:
        prominence = max(3.0, 0.015 * smooth[spe_mask].max())
        peaks, props = find_peaks(
            smooth[spe_mask], prominence=prominence,
            distance=max(2, int(2.0 / bin_width)),
        )
        if peaks.size:
            cand_idx = spe_indices[peaks]
            order = np.argsort(props["prominences"])[::-1]
            gain_candidates = list(x[cand_idx[order[:4]]] - mu0_seed)
        else:
            gain_candidates = [x[spe_indices[np.argmax(smooth[spe_mask])]] - mu0_seed]

    main = float(gain_candidates[0])
    gain_candidates += [0.8 * main, 1.2 * main, 8.0, 12.0, 16.0, 20.0]
    gain_candidates = sorted({
        float(np.clip(g, gain_low, gain_high)) for g in gain_candidates
    })
    return mu0_seed, sigma0_seed, gain_candidates, smooth


# ---------------------------------------------------------------------------
# Analytic model functions
# ---------------------------------------------------------------------------
def three_gauss(x, A0, mu0, sigma0, A1, mu1, sigma1, A2):
    """Pedestal + SPE + DPE.  SPE/DPE widths grow as sqrt(sigma0^2 + n*sigma1^2)."""
    g_ped = A0 * np.exp(-(x - mu0) ** 2 / (2 * sigma0 ** 2))
    g_spe = A1 * np.exp(-(x - mu0 - mu1) ** 2 / (2 * (sigma0 ** 2 + sigma1 ** 2)))
    g_dpe = A2 * np.exp(-(x - mu0 - 2 * mu1) ** 2 / (2 * (sigma0 ** 2 + 2 * sigma1 ** 2)))
    return g_ped + g_spe + g_dpe


def four_gauss(x, A0, mu0, sigma0, A1, mu1, sigma1, A2, A3):
    """Pedestal + SPE + DPE + TPE."""
    base = three_gauss(x, A0, mu0, sigma0, A1, mu1, sigma1, A2)
    g_tpe = A3 * np.exp(-(x - mu0 - 3 * mu1) ** 2 / (2 * (sigma0 ** 2 + 3 * sigma1 ** 2)))
    return base + g_tpe


def gauss_poisson(x, A, mu0, sigma0, mu_pe, gain, sigma1, kmax=PMAX_KMAX):
    """Gaussian-convolved Poisson: sum_k Pois(k|mu_pe) * Gauss(mu0+k*gain, ...)."""
    k = np.arange(kmax + 1)
    prob = poisson.pmf(k, mu_pe)
    x = np.asarray(x, dtype=float)
    terms = np.zeros_like(x)
    for kk, p in zip(k, prob):
        if p <= 0:
            continue
        sigma_k = np.sqrt(sigma0 ** 2 + kk * sigma1 ** 2)
        terms += (p / sigma_k) * np.exp(-0.5 * ((x - mu0 - kk * gain) / sigma_k) ** 2)
    return A * terms / np.sqrt(2 * np.pi)


def _failed_result(counts, edges, x, model) -> Dict:
    """Empty/non-finite result marker used on fit failure."""
    nan = float("nan")
    return {
        "gain": nan, "gain_error": nan, "sigma": nan, "sigma_error": nan,
        "amplitude": nan, "amplitude_error": nan, "resolution": nan,
        "params": np.array([]), "errors": np.array([]),
        "x": x, "counts": counts, "edges": edges,
        "model": model, "success": False,
    }


# ---------------------------------------------------------------------------
# Fit models (each one self-contained, returns a common result dict)
# ---------------------------------------------------------------------------
def single_fit(
    values,
    bins: int = 100,
    hist_range: Tuple[float, float] = (-15.0, 100.0),
    fit_range: Tuple[float, float] = SINGLE_FIT_RANGE,
    mean_init: float = SINGLE_MEAN_INIT,
    sigma_init: float = SINGLE_SIGMA_INIT,
    mean_bounds: Tuple[float, float] = SINGLE_MEAN_BOUNDS,
    sigma_bounds: Tuple[float, float] = SINGLE_SIGMA_BOUNDS,
    amp_bounds: Tuple[float, float] = SINGLE_AMP_BOUNDS,
) -> Dict:
    """Fit a single Gaussian to the SPE peak.

    This mirrors the legacy ``fit_spe_spectrum`` behaviour.  Unlike the other
    two models it is a pure peak fit (no pedestal), most suitable when the
    pedestal is well separated.
    """
    from scipy.optimize import curve_fit

    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]

    def gaussian(x, amp, mu, sigma):
        return amp * np.exp(-0.5 * ((x - mu) / sigma) ** 2)

    counts, edges = np.histogram(values, bins=bins, range=hist_range)
    x = 0.5 * (edges[:-1] + edges[1:])
    y = counts.astype(float)

    mask = (x >= fit_range[0]) & (x <= fit_range[1])
    x_fit, y_fit = x[mask], y[mask]
    if len(x_fit) < 4 or not np.any(y_fit > 0):
        return _failed_result(counts, edges, x, "single_fit")

    amp_init = float(y_fit.max())
    mu_actual = float(x_fit[np.argmax(y_fit)])
    sigma_actual = (x_fit[-1] - x_fit[0]) / 10.0
    mu_actual = float(np.clip(mu_actual, *mean_bounds))
    sigma_actual = float(np.clip(sigma_actual, *sigma_bounds))
    amp_init = float(np.clip(amp_init, *amp_bounds))

    p0 = [amp_init, mu_actual, sigma_actual]
    lo = [amp_bounds[0], mean_bounds[0], sigma_bounds[0]]
    hi = [amp_bounds[1], mean_bounds[1], sigma_bounds[1]]

    try:
        popt, pcov = curve_fit(gaussian, x_fit, y_fit, p0=p0, bounds=(lo, hi),
                               maxfev=20000)
    except Exception:
        return _failed_result(counts, edges, x, "single_fit")

    perr = np.sqrt(np.maximum(np.diag(pcov), 0))
    gain = abs(float(popt[1]))
    sigma = abs(float(popt[2]))
    amp = float(popt[0])
    return {
        "gain": gain,
        "gain_error": float(perr[1]),
        "sigma": sigma,
        "sigma_error": float(perr[2]),
        "amplitude": amp,
        "amplitude_error": float(perr[0]),
        "resolution": sigma / gain if gain > 0 else float("nan"),
        "params": popt,
        "errors": perr,
        "x": x,
        "counts": counts,
        "edges": edges,
        "model": "single_fit",
        "success": True,
    }


def multi_gauss_fit(
    values,
    bins: int = DEFAULT_BINS,
    hist_range: Tuple[float, float] = DEFAULT_HIST_RANGE,
    n_peaks: int = 3,
) -> Dict:
    """Fit pedestal + 1/2/3-PE Gaussians (``three_gauss_fit``; default 3 peaks).

    Amplitudes of the SPE/DPE/TPE peaks are independent (unlike the Poisson
    model).  The fit minimizes the Poisson deviance over several gain seeds.
    """
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 100:
        raise ValueError("multi_gauss_fit requires at least 100 finite values")
    if n_peaks not in (2, 3):
        raise ValueError("n_peaks must be 2 or 3")

    counts, edges, x, bin_width = _hist(values, bins, hist_range)
    mu0, sigma0, gain_candidates, smooth = _seed_from_hist(x, counts, hist_range)

    max_count = max(float(counts.max()), 1.0)
    gain_low = max(3.0, 2.5 * sigma0)
    gain_high = min(30.0, (hist_range[1] - mu0) / n_peaks)

    lower = np.array([0, mu0 - 2.5, 0.2, 0, gain_low, 0.3, 0, 0.0])
    upper = np.array([2 * max_count, mu0 + 2.5, 5.0, 2 * max_count,
                      gain_high, 20.0, 2 * max_count, 2 * max_count])
    if n_peaks == 2:
        upper[7] = 1e-8

    fits = []
    for gain_seed in gain_candidates:
        spe_index = int(np.argmin(np.abs(x - (mu0 + gain_seed))))
        sigma1_seed = float(np.clip(
            _peak_width_from_hist(x, smooth, spe_index, bin_width, 0.4 * gain_seed),
            0.6, min(0.9 * gain_seed, 12.0),
        ))
        p0 = np.array([
            smooth[int(np.argmin(np.abs(x - mu0)))], mu0, sigma0,
            smooth[spe_index], gain_seed, sigma1_seed,
            max(1.0, np.interp(mu0 + 2 * gain_seed, x, smooth)),
            max(1e-8, np.interp(mu0 + 3 * gain_seed, x, smooth)),
        ])
        p0 = np.minimum(np.maximum(p0, lower + 1e-9), upper - 1e-9)
        fit = least_squares(
            lambda p: _poisson_deviance_residual(counts, four_gauss(x, *p)),
            p0, bounds=(lower, upper), max_nfev=30000,
            x_scale="jac", loss="linear",
        )
        fits.append(fit)

    fit = min(fits, key=lambda item: np.sum(item.fun ** 2))
    params = fit.x
    expected = four_gauss(x, *params)
    dof = max(1, np.count_nonzero(counts) - len(params))
    deviance = float(np.sum(_poisson_deviance_residual(counts, expected) ** 2))

    cov = np.full((len(params), len(params)), np.nan)
    try:
        cov = np.linalg.pinv(fit.jac.T @ fit.jac) * (deviance / dof)
    except np.linalg.LinAlgError:
        pass
    errors = np.sqrt(np.maximum(np.diag(cov), 0))

    # layout: [A0, mu0, sigma0, A1, gain, sigma1, A2, A3]
    gain = float(params[4])
    sigma = float(params[5])
    return {
        "gain": gain,
        "gain_error": float(errors[4]),
        "sigma": sigma,
        "sigma_error": float(errors[5]),
        "amplitude": float(params[3]),
        "amplitude_error": float(errors[3]),
        "resolution": sigma / gain if gain > 0 else float("nan"),
        "params": params,
        "errors": errors,
        "x": x,
        "counts": counts,
        "edges": edges,
        "deviance": deviance,
        "reduced_deviance": deviance / dof,
        "model": "multi_gauss_fit",
        "n_peaks": n_peaks,
        "success": bool(fit.success),
    }


def poisson_fit(
    values,
    bins: int = DEFAULT_BINS,
    hist_range: Tuple[float, float] = DEFAULT_HIST_RANGE,
    kmax: int = PMAX_KMAX,
) -> Dict:
    """Fit a Gaussian-convolved Poisson model (``gauss_poisson_fit``).

    The 1/2/3-PE peak amplitudes are not free: all are set by a single Poisson
    mean ``mu_pe``, so this is the most constrained of the three models.
    """
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 100:
        raise ValueError("poisson_fit requires at least 100 finite values")

    counts, edges, x, bin_width = _hist(values, bins, hist_range)
    mu0, sigma0, gain_candidates, smooth = _seed_from_hist(x, counts, hist_range)

    mean_charge = float(values.mean())
    total = float(counts.sum())
    gain_low = max(3.0, 2.5 * sigma0)
    gain_high = min(30.0, (hist_range[1] - mu0) / 3.0)

    lower = np.array([0, mu0 - 2.5, 0.2, 0.01, gain_low, 0.3])
    upper = np.array([2 * total, mu0 + 2.5, 5.0, 8.0, gain_high, 20.0])

    fits = []
    for gain_seed in gain_candidates:
        mu_pe_seed = float(np.clip((mean_charge - mu0) / gain_seed, 0.05, 3.0))
        spe_index = int(np.argmin(np.abs(x - (mu0 + gain_seed))))
        spe_width = _peak_width_from_hist(
            x, smooth, spe_index, bin_width, 0.4 * gain_seed
        )
        sigma1_seed = float(np.clip(
            np.sqrt(max(spe_width ** 2 - sigma0 ** 2, (0.2 * gain_seed) ** 2)),
            0.6, min(0.9 * gain_seed, 12.0),
        ))
        p0 = np.minimum(
            np.maximum(np.array([total, mu0, sigma0, mu_pe_seed, gain_seed, sigma1_seed]),
                       lower + 1e-9),
            upper - 1e-9,
        )
        fit = least_squares(
            lambda p: _poisson_deviance_residual(
                counts, gauss_poisson(x, *p, kmax=kmax)
            ),
            p0, bounds=(lower, upper), max_nfev=30000,
            x_scale="jac", loss="linear",
        )
        fits.append(fit)

    fit = min(fits, key=lambda item: np.sum(item.fun ** 2))
    params = fit.x
    expected = gauss_poisson(x, *params, kmax=kmax)
    dof = max(1, np.count_nonzero(counts) - len(params))
    deviance = float(np.sum(_poisson_deviance_residual(counts, expected) ** 2))

    cov = np.full((len(params), len(params)), np.nan)
    try:
        cov = np.linalg.pinv(fit.jac.T @ fit.jac) * (deviance / dof)
    except np.linalg.LinAlgError:
        pass
    errors = np.sqrt(np.maximum(np.diag(cov), 0))

    gain = float(params[4])
    sigma = float(params[5])
    return {
        "gain": gain,
        "gain_error": float(errors[4]),
        "sigma": sigma,
        "sigma_error": float(errors[5]),
        "amplitude": float(params[0]),
        "amplitude_error": float(errors[0]),
        "resolution": sigma / gain if gain > 0 else float("nan"),
        "params": params,
        "errors": errors,
        "x": x,
        "counts": counts,
        "edges": edges,
        "mu_pe": float(params[3]),
        "deviance": deviance,
        "reduced_deviance": deviance / dof,
        "model": "poisson_fit",
        "success": bool(fit.success),
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
FIT_MODELS: Dict[str, callable] = {
    "single_fit": single_fit,
    "multi_gauss_fit": multi_gauss_fit,
    "poisson_fit": poisson_fit,
}

DEFAULT_FIT_MODEL = "multi_gauss_fit"


def fit_spectrum(values, fit_model: str = DEFAULT_FIT_MODEL, **kwargs) -> Dict:
    """Fit an SPE spectrum with the selected model (default ``multi_gauss_fit``)."""
    if fit_model not in FIT_MODELS:
        raise ValueError(
            f"Unknown fit_model {fit_model!r}. Choose from {sorted(FIT_MODELS)}"
        )
    return FIT_MODELS[fit_model](values, **kwargs)
