# pmt_analysis

A Python toolkit for PMT (Photomultiplier Tube) test data analysis from liquid xenon TPC detector.

## Architecture

```
CLI (pmt-analysis analyze --run-id X)
  │
  ▼
pipeline.analyze_runs()
  │
  ├── runinfo.get_runinfo()                    # Discover & parse runinfo.json
  │     validate_run_tag()                     # Must be "PMT TEST"
  │     parse_datatypes()                      # Must contain valid keywords
  │
  ├── NotebookBasedRawDataReader.read()        # Load raw binary via waveform_analysis
  │     returns RawDataBundle
  │
  ├── IF "dark rate" in datatype:
  │     analysis.dark_count.analyze_dark_count()
  │
  ├── IF "spe gain" in datatype:
  │     analysis.gain.analyze_gain()            # --fit-model selects the fit
  │       └── gain_fit_models.fit_spectrum()    # single_fit / multi_gauss_fit / poisson_fit
  │       └── plotting.plot_spe_gain_fit_overlay()  # run{id}_multi_gauss_fit.png (all channels)
  │
  ├── IF "after pulse" in datatype:
  │     analysis.app.analyze_app()
  │       ├── find_main_pulses_per_channel()          # Main pulse detection
  │       ├── find_afterpulse_candidates_per_channel() # Afterpulse candidate search
  │       ├── select_afterpulses_per_channel()        # Afterpulse selection
  │       ├── load_spe_gains_by_pmt_id()              # SPE gain loading (with local DB fallback)
  │       ├── normalize_to_pe_per_channel()           # PE normalization
  │       ├── compute_app_per_channel()               # APP calculation
  │       ├── plot_afterpulse_2d_histogram()          # 2D histogram per channel
  │       ├── plot_afterpulse_delta_time_all_channels() # Delta time distribution (3x3 grid)
  │       ├── plot_main_pulse_area_all_channels()     # Main pulse area distribution (3x3 grid)
  │       ├── plot_main_pulse_diagnostics()           # Main pulse parameter histograms
  │       └── save_diagnostics_npz()                  # Save .npz files
  │
  └── db.writer.write_analysis_results()       # Optional DB write
```

## Data Layout

```
/mnt/data/TPC/run_R8520/{run_id}/
  ├── runinfo.json                             # Run configuration
  └── RAW/                                     # Raw binary data files
      ├── run_R8520_*_raw_b0_seg0.bin
      ├── run_R8520_*_raw_b0_seg1.bin
      └── ...
```

## Installation

```bash
# Using pyth12 conda environment (recommended)
conda activate pyth12
pip install -e .
```

### Dependencies

- `numpy`: Array operations
- `scipy`: Gaussian fitting
- `matplotlib`: Plotting
- `waveform_analysis`: Raw data reading (required for all analysis)

## Usage

```bash
# Basic analysis
pmt-analysis analyze --run-id 00305

# Multiple runs
pmt-analysis analyze --run-id 00305 00306 --output-dir output

# Select the SPE gain spectrum fit model (default: multi_gauss_fit)
pmt-analysis analyze --run-id 00305 --fit-model multi_gauss_fit
pmt-analysis analyze --run-id 00305 --fit-model single_fit
pmt-analysis analyze --run-id 00305 --fit-model poisson_fit

# With database write
pmt-analysis analyze --run-id 00305 --write-db

# Also runnable as a python module
python -m pmt_analysis.cli analyze --run-id 00350 --fit-model multi_gauss_fit
```

### SPE gain fit models

| `--fit-model` | Description | Default |
|---------------|-------------|---------|
| `multi_gauss_fit` | Pedestal + 1/2/3-PE Gaussians (Poisson-deviance least squares) | ✅ yes |
| `single_fit` | Single Gaussian peak fit (SPE peak only) | no |
| `poisson_fit` | Gaussian-convolved Poisson (amplitudes tied by a single `mu_pe`) | no |

The fit models live in `src/pmt_analysis/analysis/gain_fit_models.py` and are
selected via `analyze_gain(..., fit_model=...)` or the `--fit-model` CLI flag.

## Analysis Algorithms

### 1. Dark Count Analysis

**Purpose**: Identify dark count pulses and measure dark count rate.

**Algorithm**:

1. **Asymmetry Calculation**:
   ```
   asymmetry = abs(min(waveform)) / (abs(min(waveform)) + max(waveform))
   ```

2. **Classification**:
   - asymmetry > 0.7 → dark count
   - asymmetry ≤ 0.7 → noise

3. **Dark Count Rate**:
   ```
   dark_count_rate = total_dark_count / total_daq_run_time_length (Hz)
   ```

**Output Fields**:
- `dark_count_rate_hz`: Dark count rate in Hz
- `total_pulses`: Total number of pulses
- `dark_count`: Number of dark count pulses
- `noise_count`: Number of noise pulses

### 2. SPE Gain Analysis

**Purpose**: Measure Single Photo-Electron gain by fitting SPE spectrum.

**Algorithm**:

1. **PE Conversion Factor**:
   ```
   pe_fact = (2/16384) * 4e-9 / (50 * 1.6e-19) / 1e6
   ```
   Converts ADC counts to photoelectrons (in units of 10^6 e^-)

2. **Data Processing**:
   - Baseline correction: Mean of first 30 samples
   - RMS filtering: Skip waveforms with baseline RMS > threshold
   - Integration window: `center_idx = 95`, `win_left = 5`, `win_right = 5` → samples `[90:100]`
     (centered on the true PMT pulse peak, which sits at ~sample 93)
   - Charge calculation: `raw_area = -sum(window - baseline)`, `area_pe = raw_area * pe_fact`

3. **Fitting Models** (`src/pmt_analysis/analysis/gain_fit_models.py`):
   The SPE charge spectrum is fit with a switchable model. Each model returns
   a common result dict: `gain, gain_error, sigma, sigma_error, amplitude,
   amplitude_error, resolution, params, errors, x, counts, edges`.

   - **`multi_gauss_fit` (default)**: pedestal + 1/2/3-PE Gaussians. Peak centers
     at `mu0 + n*gain`, widths `sqrt(sigma0^2 + n*sigma1^2)`, independent
     amplitudes. Fit via Poisson-deviance least squares over several gain seeds.
   - **`single_fit`**: single Gaussian peak fit on the SPE peak.
   - **`poisson_fit`**: Gaussian-convolved Poisson
     `sum_k Pois(k|mu_pe)·Gauss(x; mu0 + k*gain, sqrt(sigma0^2 + k*sigma1^2))`.
     All peak amplitudes are tied to a single `mu_pe` (fewest parameters).

   The selected model is recorded on each channel's `GainFitResult.fit_model`.

4. **Gain Definition**:
   **Gain = mu** (SPE peak position) from the fit `gain` parameter, in PE units.

**Output Fields**:
- `gain_value`: SPE peak position (mu) in PE units
- `gain_error`: Uncertainty on gain_value
- `sigma`: SPE peak width
- `resolution`: `sigma / gain`
- `sample_count`: Number of valid waveforms used
- `fit_model`: which fit model was used
- `fit_parameters` / `raw_params` / `raw_errors`: fit parameters for reconstruction

### 3. Afterpulse Probability (APP) Analysis

**Purpose**: Identify afterpulses and calculate afterpulse probability.

**Algorithm Overview**:

```
Main Pulse Detection → Afterpulse Candidate Search → Selection → PE Normalization → APP Calculation
```

#### Step 1: Main Pulse Detection (`find_main_pulses_per_channel`)

For each waveform:
1. **Baseline subtraction**: Mean of first 30 samples
2. **Find minimum**: `min_idx = argmin(processed)`
3. **Height check**: Skip if `abs(processed[min_idx]) < 1000` ADC
4. **Find start**: Move left from minimum until signal starts decreasing
5. **Find end**: Move right from minimum until signal returns to baseline
   - Continue until 3 consecutive samples within 50 ADC of baseline
6. **Calculate area**: Integrate from start to end

**Output**: `MainPulseRecord` with:
- `sample_index`: Position of minimum (peak)
- `height`: Pulse height in ADC
- `charge`: Integrated area
- `start`, `end`: Pulse boundaries

#### Step 2: Afterpulse Candidate Search (`find_afterpulse_candidates_per_channel`)

For each main pulse:
1. **Search window**: Start from `main_pulse.end + 35` samples (minimum interval)
2. **Threshold detection**: Find points where `processed[j] < -20` ADC
3. **Filter points**: Ensure minimum 2 samples between candidates
4. **Pulse fitting**: For each candidate, find start/min/end using `findpulse_st_ed()`
5. **Height check**: Skip if `abs(processed[minp]) < 20` ADC
6. **Calculate delay time**: `delay_time = (afterpulse.start - main_pulse.end) × dt_ns`
   - `dt_ns` is the DAQ time step in nanoseconds (e.g., 4 ns for 250 MHz)

**Output**: `AfterpulseRecord` with:
- `delay_time`: Time from main pulse end to afterpulse start (ns)
- `height`: Afterpulse height in ADC
- `charge`: Afterpulse integrated area

#### Step 3: Afterpulse Selection (`select_afterpulses_per_channel`)

Filter afterpulse candidates with minimum interval between consecutive afterpulses:
- Default: 10 samples between afterpulses

#### Step 4: PE Normalization (`normalize_to_pe_per_channel`)

1. **Load SPE gains**: Query from `pmtdata` client first, then fallback to local SQLite DB
2. **Normalize**: `charge_pe = charge / spe_gain`

#### Step 5: APP Calculation (`compute_app_per_channel`)

```
APP = sum(afterpulse_charge) / sum(main_pulse_charge)
```

**Output Fields**:
- `app_value`: APP in raw units
- `app_value_pe`: APP in PE units
- `main_pulse_count`: Number of main pulses
- `afterpulse_count`: Number of afterpulses

### 4. Diagnostic Outputs

#### 2D Histogram (`plot_afterpulse_2d_histogram`)

For each channel, generates a two-panel figure:
- **Top**: 2D histogram of delta_time (μs) vs area (PE) with log color scale
- **Bottom**: 1D projection of delta_time distribution
- **Ion markers**: H⁺, He⁺ (red), CH₄⁺, N₂⁺, Ar⁺, Xe⁺⁺, Xe⁺ (grey)
- **Figure size**: 5×5 inches

#### Delta Time Distribution (`plot_afterpulse_delta_time_all_channels`)

For all channels, generates a 3×3 grid:
- Each subplot shows delta_time distribution (0-4 μs)
- Shared y-axis for easy comparison
- Ion position markers overlaid

#### Main Pulse Area Distribution (`plot_main_pulse_area_all_channels`)

For all channels, generates a 3×3 grid:
- Each subplot shows main pulse area (PE) histogram
- Shared y-axis for easy comparison
- Mean value marked with red dashed line

#### Main Pulse Diagnostics (`plot_main_pulse_diagnostics`)

For each channel, generates a 2×2 figure with:
- **Top-left**: Height (ADC) histogram
- **Top-right**: Area (raw) histogram
- **Bottom-left**: Area (PE) histogram
- **Bottom-right**: Baseline (ADC) histogram

#### .npz Files (`save_diagnostics_npz`)

Per-channel data files containing:
- `main_height`, `main_area`, `main_area_pe`, `main_start`, `main_end`
- `ap_delta_time`, `ap_area`, `ap_area_pe`, `ap_height`, `ap_start`, `ap_end`

## Configuration

| Constant | Value | Module |
|----------|-------|--------|
| `DEFAULT_OUTPUT_DIR` | `"output"` | `config.py` |
| `DEFAULT_TPC_DATA_ROOT` | `"/mnt/data/TPC"` | `config.py` |
| `DEFAULT_DB_PATH` | `"/mnt/data/TPC/database/pmt_data.db"` | `config.py` |
| `DEFAULT_MAIN_PULSE_HEIGHT_THRESHOLD` | `1000` ADC | `app.py` |
| `DEFAULT_AMPLITUDE_THRESHOLD` | `20` ADC | `app.py` |
| `DEFAULT_AFTERPULSE_MIN_INTERVAL` | `35` samples | `app.py` |
| `DEFAULT_MIN_INTERVAL_BETWEEN_PULSES` | `10` samples | `app.py` |
| Default asymmetry threshold | `0.7` | `dark_count.py` |
| Default gain fit model | `multi_gauss_fit` | `gain.py` / `gain_fit_models.py` |
| Default integration center (`center_idx`) | `95` (window `[90:100]`) | `gain.py` |
| Default gain fit bins / range | `120` / `(-10, 80)` | `gain_fit_models.py` |
| Default RMS threshold (gain) | `50.0` | `gain.py` |

## Database Schema

**Table: `measurements`**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | Auto-increment ID |
| `pmt_id` | TEXT NOT NULL | PMT identifier (e.g. "LV2389") |
| `board_id` | INTEGER NOT NULL | Board number |
| `channel_id` | INTEGER NOT NULL | Channel number |
| `run_id` | TEXT NOT NULL | Run identifier |
| `measurement_time` | TEXT | Timestamp of the write |
| `dark_count_rate` | REAL | Dark count rate in Hz |
| `spe_gain` | REAL | SPE gain in 10^6 e^- |
| `after_pulse_probability` | REAL | APP value |
| `notes` | TEXT | Optional notes |
| `created_at` | TEXT | Default: `datetime('now')` |

## Output Files

For run 00305, the analysis generates:

```
output/
├── run00305_waveform_overlay.png              # Waveform overlay
├── run00305_multi_gauss_fit.png               # SPE gain multi-Gaussian fit (all channels, grid), one per run
├── run00305_afterpulse_2d_ch[0-6].png         # 2D histograms per channel
├── run00305_afterpulse_delta_time_all.png     # Delta time distribution (3x3 grid)
├── run00305_main_pulse_area_all.png           # Main pulse area distribution (3x3 grid)
├── run00305_main_pulse_ch[0-6].png            # Main pulse diagnostics per channel
├── run00305_waveform_markers_ch0.png          # Waveform with start/end markers
├── run00305_{pmt_id}_ch[0-6].npz              # Per-channel data files
└── run00305_all_channels.npz                  # Combined all-channel data
```

> For SPE Gain runs, the gain figure is `run{run_id}_multi_gauss_fit.png`: a
> grid of subplots (one per channel) showing the charge histogram, the total
> multi-Gaussian fit, and the individual pedestal / 1-PE / 2-PE Gaussian
> components as colored dashed lines, with a legend of key fit parameters
> (mu / sigma / resolution). The legacy `spe_gain_validation.png` and
> `area_histogram.png` outputs are no longer generated for SPE Gain runs.

## Afterpulse Probability in a Time Window (`scripts/app_1us_from_npz.py`)

A standalone script that computes the afterpulse probability (APP) within a
time window after the main pulse for an arbitrary run / PMT / channel, by
reading the saved per-channel `.npz` diagnostics file directly (no database
write, no re-analysis).

```
APP_window = sum(afterpulse_area_pe [delay_time <= window]) / sum(main_area_pe)
```

**Usage:**

```bash
# By run-id / pmt-id / channel
python scripts/app_1us_from_npz.py --run-id 00354 --pmt-id LV2264 --channel 4

# Custom window and output directory
python scripts/app_1us_from_npz.py --run-id 00354 --pmt-id LV2264 --channel 4 \
    --window-ns 2000 --output-dir /mnt/data/PMT/R8520_406/output

# By direct .npz path
python scripts/app_1us_from_npz.py --npz /mnt/data/PMT/R8520_406/output/run00354_LV2264_ch4.npz
```

**Options:**

| Flag | Description | Default |
|------|-------------|---------|
| `--run-id` | 5-digit run id (e.g. `00354`) | — |
| `--pmt-id` | PMT id (e.g. `LV2264`) | — |
| `--channel` | Channel number | — |
| `--npz` | Direct path to the `.npz` file (takes precedence over the above) | — |
| `--output-dir` | Directory holding the `.npz` files | `/mnt/data/PMT/R8520_406/output` |
| `--window-ns` | Time window after the main pulse (ns) | `1000` |
