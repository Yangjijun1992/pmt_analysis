"""Example: Plot afterpulse area vs delta_time from saved .npz files."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

OUTPUT_DIR = Path("output")
RUN_ID = "00305"

# Channels to plot
CHANNELS = [0, 1, 2, 3, 4, 5, 6]
USE_PE = True

fig, axes = plt.subplots(len(CHANNELS), 1, figsize=(12, 2.5 * len(CHANNELS)), sharex=True)
if len(CHANNELS) == 1:
    axes = [axes]

for idx, ch in enumerate(CHANNELS):
    ax = axes[idx]
    matches = list(OUTPUT_DIR.glob(f"run{RUN_ID}_*ch{ch}.npz"))
    if not matches:
        ax.text(0.5, 0.5, f"CH{ch}: file not found", transform=ax.transAxes,
                ha="center", va="center", color="gray")
        continue

    data = np.load(matches[0])
    pmt_id = str(data["pmt_id"])
    delta_time = data["ap_delta_time"]  # already in ns

    if USE_PE:
        area = data["ap_area_pe"]
        ylabel = "Area (PE)"
    else:
        area = data["ap_area"]
        ylabel = "Area (raw)"

    if len(delta_time) == 0:
        ax.text(0.5, 0.5, f"CH{ch} ({pmt_id}): no afterpulses", transform=ax.transAxes,
                ha="center", va="center", color="gray")
        ax.set_ylabel(f"CH{ch} ({pmt_id})\n{ylabel}", fontsize=9)
        continue

    h = ax.hist2d(delta_time, area, bins=[80, 60], cmap="viridis")
    ax.set_ylabel(f"CH{ch} ({pmt_id})\n{ylabel}", fontsize=9)
    ax.tick_params(labelsize=7)
    print(f"CH{ch} ({pmt_id}): {len(delta_time)} afterpulses, "
          f"delta_t=[{delta_time.min():.1f}, {delta_time.max():.1f}] ns, "
          f"area=[{area.min():.2f}, {area.max():.2f}]")

axes[-1].set_xlabel("Delta Time (ns)", fontsize=10)
fig.suptitle(f"Run {RUN_ID} — Afterpulse Area vs Delta Time", fontsize=12, y=1.01)
plt.tight_layout()
out_path = OUTPUT_DIR / f"run{RUN_ID}_afterpulse_area_vs_time.png"
fig.savefig(out_path, dpi=120, bbox_inches="tight")
plt.close(fig)
print(f"\nSaved: {out_path}")
