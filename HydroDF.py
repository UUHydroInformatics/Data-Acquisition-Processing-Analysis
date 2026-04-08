import os
import sys
import datetime
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from dataretrieval import nwis
warnings.filterwarnings("ignore")

sys.path.append(os.path.abspath('supporting_scripts'))

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# --- Station config ---
station_id  = "09330000"
basinname   = "FremontRiverBasin"
water_year  = 2019
wy_start    = f"{water_year - 1}-10-01"
wy_end      = f"{water_year}-09-30"

os.makedirs('Figures', exist_ok=True)
os.makedirs('files/NWIS', exist_ok=True)

print(f"Station: {station_id} — Fremont River near Bicknell, UT")
print(f"Water Year: {water_year}  ({wy_start} to {wy_end})")

# --- Load NLDAS ---
NLDAS_df = pd.read_csv("files/NLDAS/NLDAS_09330000.csv")
NLDAS_df['Date'] = pd.to_datetime(NLDAS_df['Date'])
NLDAS_df.set_index('Date', inplace=True)
NLDAS_df['prcp_mm_day'] = NLDAS_df['total_precipitation'] * 86400

# --- Fetch or load streamflow ---
streamflow_path = "files/NWIS/streamflow_09330000.csv"
os.makedirs('files/NWIS', exist_ok=True)

if os.path.exists(streamflow_path):
    print("Loading cached streamflow...")
    streamflow_df = pd.read_csv(streamflow_path)
    streamflow_df['Date'] = pd.to_datetime(streamflow_df['Date'])
    streamflow_df.set_index('Date', inplace=True)
else:
    print("Fetching streamflow from NWIS...")
    raw, _ = nwis.get_dv(
        sites=station_id,
        start="2006-01-01",
        end="2021-12-31",
        parameterCd="00060"
    )
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    raw.index.name = 'Date'
    raw['flow_cms'] = raw['00060_Mean'] * 0.0283168
    streamflow_df = raw[['flow_cms']].copy()
    streamflow_df['site_no'] = station_id
    streamflow_df.to_csv(streamflow_path)
    print(f"Saved to {streamflow_path}")

# --- Align date ranges and merge ---
begin_date = max([NLDAS_df.index.min(), streamflow_df.index.min()])
end_date   = min([NLDAS_df.index.max(), streamflow_df.index.max()])

NLDAS_df      = NLDAS_df[(NLDAS_df.index >= begin_date) & (NLDAS_df.index <= end_date)]
streamflow_df = streamflow_df[(streamflow_df.index >= begin_date) & (streamflow_df.index <= end_date)]

Hydro_df = pd.concat([streamflow_df, NLDAS_df], axis=1)

# --- Clip to water year ---
wy_df = Hydro_df[(Hydro_df.index >= wy_start) & (Hydro_df.index <= wy_end)].copy()

# Save Hydro_df
os.makedirs('files/HydroDF', exist_ok=True)
Hydro_df.to_csv(f"files/HydroDF/Hydro_df_{station_id}.csv")
wy_df.to_csv(f"files/HydroDF/Hydro_df_{station_id}_WY{water_year}.csv")

# --- Plot 1: Streamflow and SW Radiation ---
fig, ax1 = plt.subplots(figsize=(13, 4))
ax2 = ax1.twinx()
ax1.plot(wy_df.index, wy_df['flow_cms'], color='steelblue', lw=1.5, label='Streamflow (cms)')
ax2.plot(wy_df.index, wy_df['shortwave_radiation'], color='goldenrod', lw=1.2,
         linestyle='--', label='SW Radiation W/m² (NLDAS)')
ax1.set_ylabel('Streamflow (m³/s)', color='steelblue')
ax2.set_ylabel('SW Radiation (W/m²)', color='goldenrod')
ax1.set_xlabel('Date')
ax1.set_title(f'Streamflow and Solar Radiation — Fremont River WY{water_year}')
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
plt.tight_layout()
plt.savefig(f'Figures/{basinname}_WY{water_year}_streamflow_radiation.png', dpi=150)
#plt.show()

# --- Plot 2: Snowmelt Drivers ---
fig, axes = plt.subplots(2, 1, figsize=(13, 6), sharex=True)
axes[0].plot(wy_df.index, wy_df['temperature'], color='tomato', lw=1.2, label='Temperature °C (NLDAS)')
axes[0].axhline(0, color='k', lw=0.8, linestyle='--', alpha=0.5)
axes[0].set_ylabel('Temperature (°C)')
axes[0].set_title(f'Snowmelt Drivers — Fremont River WY{water_year}')
axes[0].legend(loc='upper left')
axes[1].plot(wy_df.index, wy_df['shortwave_radiation'], color='goldenrod', lw=1.2,
             label='SW Radiation W/m² (NLDAS)')
axes[1].set_ylabel('SW Radiation (W/m²)')
axes[1].set_xlabel('Date')
axes[1].legend(loc='upper left')
plt.tight_layout()
plt.savefig(f'Figures/{basinname}_WY{water_year}_snowmelt_drivers.png', dpi=150)
#plt.show()

# --- Plot 3: Rainfall-Runoff ---
fig, ax1 = plt.subplots(figsize=(13, 4))
ax2 = ax1.twinx()
ax2.bar(wy_df.index, wy_df['prcp_mm_day'], color='cornflowerblue',
        alpha=0.5, label='Precip mm/day (NLDAS)', width=1)
ax1.plot(wy_df.index, wy_df['flow_cms'], color='steelblue', lw=1.5, label='Streamflow (cms)')
ax1.set_ylabel('Streamflow (m³/s)', color='steelblue')
ax2.set_ylabel('Precipitation (mm/day)', color='cornflowerblue')
ax2.invert_yaxis()
ax1.set_xlabel('Date')
ax1.set_title(f'Rainfall–Runoff Response — Fremont River WY{water_year}')
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
plt.tight_layout()
plt.savefig(f'Figures/{basinname}_WY{water_year}_rainfall_runoff.png', dpi=150)
#plt.show()

# --- Plot 4: Shortwave vs Longwave Radiation ---
fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
axes[0].plot(wy_df.index, wy_df['shortwave_radiation'], color='goldenrod',
             lw=1.2, label='Shortwave radiation W/m²')
axes[0].plot(wy_df.index, wy_df['longwave_radiation'], color='tomato',
             lw=1.2, linestyle='--', label='Longwave radiation W/m²')
axes[0].set_ylabel('Radiation (W/m²)')
axes[0].set_title(f'Shortwave vs Longwave Radiation — Fremont River WY{water_year}')
axes[0].legend(loc='upper right')
axes[1].plot(wy_df.index, wy_df['temperature'], color='steelblue',
             lw=1.2, label='NLDAS temperature (°C)')
axes[1].plot(wy_df.index, wy_df['prcp_mm_day'], color='cornflowerblue',
             lw=1.2, linestyle='--', label='NLDAS precip (mm/day)')
axes[1].set_ylabel('Temp (°C) / Precip (mm/day)')
axes[1].set_xlabel('Date')
axes[1].legend(loc='upper right')
plt.tight_layout()
plt.savefig(f'Figures/{basinname}_WY{water_year}_radiation_comparison.png', dpi=150)
#plt.show()

print("Done")