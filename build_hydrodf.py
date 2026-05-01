"""
build_hydrodf.py
================
Exercise #2 — Collect, process, and save the HydroDataFrame and select figures
for USGS NWIS station 11274790 (Tuolumne River at Hetch Hetchy Reservoir, CA).

Usage:
    python build_hydrodf.py

Outputs:
    files/NWIS/streamflow_<station_id>.csv   — USGS daily streamflow
    files/HydroDF/HydroDF_<station_id>.csv   — Combined HydroDataFrame
    outputs/fig1_streamflow_vs_SWE_WY2017.png
    outputs/fig2_snowmelt_swe_temp_srad_WY2017.png
    outputs/fig3_rainfall_runoff_WY2017.png
    outputs/fig4_daymet_vs_nldas_WY2017.png
"""

import os
import sys
import warnings
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from dataretrieval import nwis

warnings.filterwarnings("ignore")

# ── Configuration ─────────────────────────────────────────────────────────────
STATION_ID  = "11274790"
BASIN_NAME  = "TuolumneRiverBasin"
SNOTEL_PATH = "files/SNOTEL"
DROP_SNOTEL = {"TES"}            # sites with too many missing values
WY_START    = "2016-10-01"       # Water Year 2017
WY_END      = "2017-09-30"
OUTPUT_DIR  = "outputs"
NWIS_DIR    = "files/NWIS"
HYDRODF_DIR = "files/HydroDF"


# ── Helper ────────────────────────────────────────────────────────────────────
def ensure_dirs(*paths):
    for p in paths:
        os.makedirs(p, exist_ok=True)


# ── Step 1: Fetch and save streamflow if not already present ──────────────────
def fetch_streamflow(station_id, out_dir):
    out_path = os.path.join(out_dir, f"streamflow_{station_id}.csv")
    if os.path.exists(out_path):
        print(f"[streamflow] Using cached file: {out_path}")
    else:
        print(f"[streamflow] Downloading from USGS NWIS for site {station_id}...")
        df, _ = nwis.get_dv(sites=station_id, start="1980-01-01", parameterCd="00060")
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        df.rename(columns={"00060_Mean": "Streamflow_cfs"}, inplace=True)
        df.drop(columns=["00060_Mean_cd", "site_no"], errors="ignore", inplace=True)
        df.index.name = "Date"
        df = df.reset_index()
        df.to_csv(out_path, index=False)
        print(f"[streamflow] Saved {len(df)} rows → {out_path}")
    return out_path


# ── Step 2: Load SNOTEL files and build merged SNOTEL dataframe ───────────────
def load_snotel(snotel_path, drop_sites=None):
    drop_sites = drop_sites or set()
    dfs = {}
    for fname in os.listdir(snotel_path):
        if not fname.endswith(".csv"):
            continue
        name = fname.split("_")[1]
        if name in drop_sites:
            continue
        df = pd.read_csv(os.path.join(snotel_path, fname))
        df["Date"] = pd.to_datetime(df["Date"])
        df.set_index("Date", inplace=True)
        swe_col = "Snow Water Equivalent (m) Start of Day Values"
        df.rename(columns={swe_col: f"{name}_SWE_cm"}, inplace=True)
        df[f"{name}_SWE_cm"] = df[f"{name}_SWE_cm"] * 100
        df.drop(columns=["Water_Year"], errors="ignore", inplace=True)
        dfs[name] = df
        print(f"  [snotel] {name}: {len(df)} rows "
              f"({df.index.min().date()} – {df.index.max().date()})")

    latest_start = max(df.index.min() for df in dfs.values())
    soonest_end  = min(df.index.max() for df in dfs.values())
    print(f"[snotel] Common overlap: {latest_start.date()} – {soonest_end.date()}")
    for k in dfs:
        dfs[k] = dfs[k][(dfs[k].index >= latest_start) & (dfs[k].index <= soonest_end)]

    return pd.concat(dfs.values(), axis=1)


# ── Step 3: Load all dataframes and merge ─────────────────────────────────────
def build_hydrodf(station_id):
    print("\n[build] Loading data sources...")

    SNOTEL_df = load_snotel(SNOTEL_PATH, drop_sites=DROP_SNOTEL)

    PyDayMet_df = pd.read_csv(f"files/PyDayMet/PyDayMet_{station_id}.csv")
    PyDayMet_df["Date"] = pd.to_datetime(PyDayMet_df["Date"])
    PyDayMet_df.set_index("Date", inplace=True)
    PyDayMet_df.drop(columns=["Date.1"], errors="ignore", inplace=True)

    NLDAS_df = pd.read_csv(f"files/NLDAS/NLDAS_{station_id}.csv")
    NLDAS_df["Date"] = pd.to_datetime(NLDAS_df["Date"])
    NLDAS_df.set_index("Date", inplace=True)
    NLDAS_df.drop(columns=["Date.1"], errors="ignore", inplace=True)

    streamflow_df = pd.read_csv(f"files/NWIS/streamflow_{station_id}.csv")
    streamflow_df["Date"] = pd.to_datetime(streamflow_df["Date"])
    streamflow_df.set_index("Date", inplace=True)

    basin_info = pd.read_csv(f"files/basin_info/basin_info_{station_id}.csv")

    # Align to overlapping period
    begin_date = max(df.index.min() for df in [SNOTEL_df, PyDayMet_df, streamflow_df, NLDAS_df])
    end_date   = min(df.index.max() for df in [SNOTEL_df, PyDayMet_df, streamflow_df, NLDAS_df])
    print(f"[build] Overlapping period: {begin_date.date()} – {end_date.date()}")

    for df in [SNOTEL_df, PyDayMet_df, streamflow_df, NLDAS_df]:
        mask = (df.index >= begin_date) & (df.index <= end_date)
        df.drop(df.index[~mask], inplace=True)

    Hydro_df = pd.concat([SNOTEL_df, PyDayMet_df, NLDAS_df, streamflow_df], axis=1)

    # Reorder: Streamflow_cfs first
    if "Streamflow_cfs" in Hydro_df.columns:
        cols = ["Streamflow_cfs"] + [c for c in Hydro_df.columns if c != "Streamflow_cfs"]
        Hydro_df = Hydro_df[cols]

    Hydro_df.fillna(0, inplace=True)

    # Add basin attributes as constant columns
    for col in basin_info.columns:
        Hydro_df[col] = basin_info[col].iloc[0]

    print(f"[build] Hydro_df: {Hydro_df.shape[0]} rows × {Hydro_df.shape[1]} columns")
    return Hydro_df


# ── Step 4: Save HydroDF ──────────────────────────────────────────────────────
def save_hydrodf(Hydro_df, station_id, out_dir):
    out_path = os.path.join(out_dir, f"HydroDF_{station_id}.csv")
    Hydro_df.to_csv(out_path)
    print(f"[save] HydroDF saved → {out_path}")


# ── Step 5: Generate and save figures ─────────────────────────────────────────
def make_figures(Hydro_df, wy_start, wy_end, out_dir):
    wy_df = Hydro_df.loc[wy_start:wy_end].copy()
    snotel_cols = [c for c in wy_df.columns if c.endswith("_SWE_cm")]
    wy_df["mean_SWE_cm"] = wy_df[snotel_cols].mean(axis=1)

    # Figure 1: Streamflow vs SWE
    fig, ax1 = plt.subplots(figsize=(14, 5))
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Streamflow (cfs)", color="#1f77b4")
    ax1.plot(wy_df.index, wy_df["Streamflow_cfs"], color="#1f77b4", linewidth=1.5,
             label="Streamflow (cfs)")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")
    ax2 = ax1.twinx()
    ax2.set_ylabel("Mean SNOTEL SWE (cm)", color="#d62728")
    ax2.fill_between(wy_df.index, wy_df["mean_SWE_cm"], alpha=0.3, color="#d62728")
    ax2.plot(wy_df.index, wy_df["mean_SWE_cm"], color="#d62728", linewidth=1.5,
             label="Mean SWE (cm)")
    ax2.tick_params(axis="y", labelcolor="#d62728")
    lines = ax1.get_legend_handles_labels()[0] + ax2.get_legend_handles_labels()[0]
    labels = ax1.get_legend_handles_labels()[1] + ax2.get_legend_handles_labels()[1]
    ax1.legend(lines, labels, loc="upper left")
    plt.title("Figure 1: Streamflow vs. Mean SNOTEL SWE — Tuolumne River WY2017")
    fig.tight_layout()
    path1 = os.path.join(out_dir, "fig1_streamflow_vs_SWE_WY2017.png")
    plt.savefig(path1, dpi=150)
    plt.close()
    print(f"[fig] Saved {path1}")

    # Figure 2: Snowmelt dynamics
    melt_df = wy_df.loc["2017-02-01":"2017-07-31"]
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
    axes[0].fill_between(melt_df.index, melt_df["mean_SWE_cm"], color="#4292c6", alpha=0.5)
    axes[0].plot(melt_df.index, melt_df["mean_SWE_cm"], color="#08519c", linewidth=1.5)
    axes[0].set_ylabel("Mean SWE (cm)")
    axes[0].set_title("Figure 2: Snowmelt Dynamics — SWE, Temperature & SW Radiation (WY2017)")
    axes[1].plot(melt_df.index, melt_df["tmax_C"], color="#d73027", linewidth=1.2, label="Tmax (DayMet)")
    axes[1].plot(melt_df.index, melt_df["tmin_C"], color="#4575b4", linewidth=1.2, label="Tmin (DayMet)")
    axes[1].axhline(0, color="black", linestyle="--", linewidth=0.8, alpha=0.5)
    axes[1].fill_between(melt_df.index, melt_df["tmin_C"], melt_df["tmax_C"],
                         alpha=0.15, color="orange", label="Tmax–Tmin range")
    axes[1].set_ylabel("Temperature (°C)")
    axes[1].legend(loc="upper left", fontsize=9)
    axes[2].plot(melt_df.index, melt_df["srad_W_m2"], color="#fe9929", linewidth=1.2,
                 label="SW Radiation (DayMet)")
    axes[2].set_ylabel("SW Radiation (W/m²)")
    axes[2].set_xlabel("Date")
    axes[2].legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    path2 = os.path.join(out_dir, "fig2_snowmelt_swe_temp_srad_WY2017.png")
    plt.savefig(path2, dpi=150)
    plt.close()
    print(f"[fig] Saved {path2}")

    # Figure 3: Rainfall–runoff (Oct–Jan)
    rain_df = wy_df.loc["2016-10-01":"2017-01-31"]
    fig, ax1 = plt.subplots(figsize=(14, 5))
    ax1.bar(rain_df.index, rain_df["prcp_mm_day"], color="#2166ac", alpha=0.7,
            width=1.0, label="DayMet Precipitation (mm/day)")
    ax1.set_ylabel("Precipitation (mm/day)")
    ax1.set_xlabel("Date")
    ax1.invert_yaxis()
    ax1.set_ylim(rain_df["prcp_mm_day"].max() * 2.5, 0)
    ax2 = ax1.twinx()
    ax2.plot(rain_df.index, rain_df["Streamflow_cfs"], color="#d73027",
             linewidth=2.0, label="Streamflow (cfs)")
    ax2.set_ylabel("Streamflow (cfs)", color="#d73027")
    ax2.tick_params(axis="y", labelcolor="#d73027")
    lines = ax1.get_legend_handles_labels()[0] + ax2.get_legend_handles_labels()[0]
    labels = ax1.get_legend_handles_labels()[1] + ax2.get_legend_handles_labels()[1]
    ax1.legend(lines, labels, loc="lower left")
    plt.title("Figure 3: Rainfall–Runoff Response — Tuolumne River Oct 2016–Jan 2017")
    fig.tight_layout()
    path3 = os.path.join(out_dir, "fig3_rainfall_runoff_WY2017.png")
    plt.savefig(path3, dpi=150)
    plt.close()
    print(f"[fig] Saved {path3}")

    # Figure 4: DayMet vs NLDAS
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
    axes[0].plot(wy_df.index, wy_df["prcp_mm_day"], color="#2166ac", linewidth=1.2,
                 alpha=0.85, label="DayMet Precip (mm/day)")
    axes[0].plot(wy_df.index, wy_df["total_precipitation"], color="#d73027", linewidth=1.2,
                 alpha=0.85, linestyle="--", label="NLDAS Total Precip (mm/day)")
    axes[0].set_ylabel("Precipitation (mm/day)")
    axes[0].legend(loc="upper right", fontsize=9)
    axes[0].set_title("Figure 4: DayMet vs. NLDAS — Precipitation & Temperature (WY2017)")
    corr_p = wy_df["prcp_mm_day"].corr(wy_df["total_precipitation"])
    axes[0].text(0.02, 0.92, f"r = {corr_p:.2f}", transform=axes[0].transAxes,
                 fontsize=10, bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))
    axes[1].plot(wy_df.index, wy_df["tmean"], color="#2166ac", linewidth=1.2,
                 alpha=0.85, label="DayMet Tmean (°C)")
    axes[1].plot(wy_df.index, wy_df["temperature"], color="#d73027", linewidth=1.2,
                 alpha=0.85, linestyle="--", label="NLDAS Temperature (°C)")
    axes[1].axhline(0, color="black", linestyle=":", linewidth=0.8, alpha=0.5)
    axes[1].set_ylabel("Temperature (°C)")
    axes[1].set_xlabel("Date")
    axes[1].legend(loc="upper left", fontsize=9)
    corr_t = wy_df["tmean"].corr(wy_df["temperature"])
    axes[1].text(0.02, 0.08, f"r = {corr_t:.2f}", transform=axes[1].transAxes,
                 fontsize=10, bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))
    fig.tight_layout()
    path4 = os.path.join(out_dir, "fig4_daymet_vs_nldas_WY2017.png")
    plt.savefig(path4, dpi=150)
    plt.close()
    print(f"[fig] Saved {path4}")

    print(f"\n[fig] Precip correlation DayMet vs NLDAS: {corr_p:.3f}")
    print(f"[fig] Temp  correlation DayMet vs NLDAS: {corr_t:.3f}")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ensure_dirs(NWIS_DIR, HYDRODF_DIR, OUTPUT_DIR)

    # 1. Fetch streamflow
    fetch_streamflow(STATION_ID, NWIS_DIR)

    # 2. Build combined HydroDF
    Hydro_df = build_hydrodf(STATION_ID)

    # 3. Save HydroDF
    save_hydrodf(Hydro_df, STATION_ID, HYDRODF_DIR)

    # 4. Generate and save figures
    print("\n[fig] Generating figures...")
    make_figures(Hydro_df, WY_START, WY_END, OUTPUT_DIR)

    print("\n✓ Done. All outputs saved.")
