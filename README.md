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
  │     analysis.gain.analyze_gain()
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

# With database write
pmt-analysis analyze --run-id 00305 --write-db
```

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
   - RMS filtering: Skip waveforms with baseline RMS > 4
   - Integration window: Sample 97 ± 10 (20-sample window)
   - Charge calculation: `raw_area = -sum(window - baseline)`, `area_pe = raw_area * pe_fact`

3. **Fitting Model**:
   Single Gaussian fit:
   ```
   f(x) = amp * exp(-0.5 * ((x - mu) / sigma)^2)
   ```
   - Fit range: (5, 20) PE
   - Initial guess: mu=10.0, sigma=2.0
   - Bounds: mu ∈ [0.1, 30], sigma ∈ [0, 12], amp ∈ [100, 1e5]

4. **Gain Definition**:
   **Gain = mu** (SPE peak position from Gaussian fit)

**Output Fields**:
- `gain_value`: SPE peak position (mu) in PE units
- `gain_error`: Uncertainty on gain_value
- `sigma`: Gaussian width
- `sample_count`: Number of valid waveforms used

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
| Default fit range (gain) | `(5, 20)` PE | `gain.py` |
| Default RMS threshold (gain) | `4.0` | `gain.py` |

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
├── run00305_afterpulse_2d_ch[0-6].png         # 2D histograms per channel
├── run00305_afterpulse_delta_time_all.png     # Delta time distribution (3x3 grid)
├── run00305_main_pulse_area_all.png           # Main pulse area distribution (3x3 grid)
├── run00305_main_pulse_ch[0-6].png            # Main pulse diagnostics per channel
├── run00305_waveform_markers_ch0.png          # Waveform with start/end markers
├── run00305_{pmt_id}_ch[0-6].npz              # Per-channel data files
└── run00305_all_channels.npz                  # Combined all-channel data
```
