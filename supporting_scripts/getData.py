import os
import io
import sys
import pytz
import urllib3
import datetime
import numpy as np
import pandas as pd
import pyproj
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from dataretrieval import nwis
pd.options.mode.chained_assignment = None

GIMMS_START_DATE = '1981-07-01'
GIMMS_END_DATE = '2013-12-16'

def getSNOTELData(SiteName, SiteID, StateAbb, StartDate, EndDate, OutputFolder):
    #the api changed and we need to pull the site id out - 3-1-2026
    site_id = SiteID.split('_')[0]
    url1 = 'https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/customMultiTimeSeriesGroupByStationReport/daily/start_of_period/'
    #url2 = f'{SiteID}:{StateAbb}:SNTL%7Cid=%22%22%7Cname/'
    url2 = f'{site_id}:{StateAbb}:SNTL%7Cid=%22%22%7Cname/'
    url3 = f'{StartDate},{EndDate}/'
    url4 = 'WTEQ::value?fitToScreen=false'
    url = url1+url2+url3+url4
    print(f'Start retrieving data for {SiteName}, {SiteID} \n {url}')

    http = urllib3.PoolManager(
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'text/csv,text/plain,*/*',
            'Connection': 'keep-alive'
        },
        retries=urllib3.Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504]),
        timeout=urllib3.Timeout(connect=5.0, read=30.0)
    )
    response = http.request('GET', url)
    if response.status != 200:
        raise RuntimeError(f'Failed to retrieve SNOTEL data for {SiteID}: HTTP {response.status}')

    data = response.data.decode('utf-8')
    lines = [line.strip() for line in data.splitlines() if line.strip() and not line.startswith('#')]
    if not lines:
        raise ValueError(f'No parseable data returned for {SiteID}')

    csv_start = 0
    for idx, line in enumerate(lines):
        if line.lower().startswith('date,'):
            csv_start = idx
            break

    csv_text = '\n'.join(lines[csv_start:])
    df = pd.read_csv(io.StringIO(csv_text))
    if df.shape[1] < 2:
        preview = '\n'.join(lines[:5])
        raise ValueError(f'Unexpected SNOTEL CSV format for {SiteID}. Preview:\n{preview}')

    df = df.iloc[:, :2].copy()
    df.columns = ['Date', 'Snow Water Equivalent (m) Start of Day Values']
    df['Date'] = pd.to_datetime(df['Date'])
    df['Snow Water Equivalent (m) Start of Day Values'] = pd.to_numeric(
        df['Snow Water Equivalent (m) Start of Day Values'], errors='coerce'
    ) * 0.0254  # convert inches to meters
    df.dropna(subset=['Date', 'Snow Water Equivalent (m) Start of Day Values'], inplace=True)
    df['Water_Year'] = pd.to_datetime(df['Date']).map(lambda x: x.year+1 if x.month>9 else x.year)

    output_path = os.path.join(OutputFolder, f'df_{SiteID}_{StateAbb}_SNTL.csv')
    df.to_csv(output_path, index=False)

def getCaliSNOTELData(SiteName, SiteID, StartDate, EndDate, OutputFolder):
    StateAbb = 'Ca'
    url1 = 'https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/customMultiTimeSeriesGroupByStationReport/daily/start_of_period/'
    url2 = f'{SiteID}:CA:MSNT%257Cid=%2522%2522%257Cname/'
    url3 = f'{StartDate},{EndDate}/'
    url4 = 'WTEQ::value?fitToScreen=false'
    url = url1+url2+url3+url4
    print(f'Start retrieving data for {SiteName}, {SiteID}')
    print(url)
    
    # Define custom headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/csv,text/plain,application/csv',
        'Connection': 'keep-alive'
    }

    # Add a timeout and retry strategy
    # connect=2.0 (wait 2s to connect), read=10.0 (wait 10s for data)
    timeout = urllib3.Timeout(connect=2.0, read=10.0)
    retries = urllib3.Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])

    http = urllib3.PoolManager(
        headers=headers, 
        timeout=timeout, 
        retries=retries,
        block=False  # Prevents the pool from blocking if multiple requests overlap
    )
    
    try:
        # Set a short 10-second timeout
        response = http.request('GET', url, timeout=10.0)
        print(f"Status: {response.status}")
    except urllib3.exceptions.MaxRetryError:
        print("Error: The HPC network cannot reach the USDA server (Check Proxy).")
    except urllib3.exceptions.TimeoutError:
        print("Error: The request timed out (The server or firewall is not responding).")

    #http = urllib3.PoolManager(headers={'User-Agent': 'SNOTEL-Data-Retrieval-Agent'})
    # print('urllib3 PoolManager created')
    # response = http.request('GET', url)
    # print('Data retrieved from URL')
    data = response.data.decode('utf-8')
    print('Data decoded from bytes to string')
    i=0
    for line in data.split("\n"):
        if line.startswith("#"):
            i=i+1
    data = data.split("\n")[i:]

    df = pd.DataFrame.from_dict(data)
    df = df[0].str.split(',', expand=True)
    df.rename(columns={0:df[0][0], 
                        1:df[1][0]}, inplace=True)
    df.drop(0, inplace=True)
    df.dropna(inplace=True)
    df.reset_index(inplace=True, drop=True)
    df["Date"] = pd.to_datetime(df["Date"])
    df.rename(columns={df.columns[1]:'Snow Water Equivalent (m) Start of Day Values'}, inplace=True)
    df.iloc[:, 1:] = df.iloc[:, 1:].apply(lambda x: pd.to_numeric(x) * 0.0254)  # convert in to m
    df['Water_Year'] = pd.to_datetime(df['Date']).map(lambda x: x.year+1 if x.month>9 else x.year)

    df.to_csv(f'./{OutputFolder}/df_{SiteID}_{StateAbb}_SNTL.csv', index=False)

def convert_latlon_to_yx(lat, lon, input_crs, ds, output_crs):
    """
    This function takes latitude and longitude values along with
    input and output coordinate reference system (CRS) and 
    uses Python's pyproj package to convert the provided values 
    (as single float values, not arrays) to the corresponding y and x 
    coordinates in the output CRS.
    
    Parameters:
    lat: The latitude value
    lon: The longitude value
    input_crs: The input coordinate reference system ('EPSG:4326')
    output_crs: The output coordinate reference system
    
    Returns:
    y, x: a tuple of the transformed coordinates in the specified output
    """
    # Create a transformer
    transformer = pyproj.Transformer.from_crs(input_crs, output_crs, always_xy=True)

    # Perform the transformation
    x, y = transformer.transform(lon, lat)

    return y, x 

def convert_utc_to_local(state_abbr, df):
    state_timezones = {
    'AL': 'US/Central', 'AK': 'US/Alaska', 'AZ': 'US/Mountain', 'AR': 'US/Central',
    'CA': 'US/Pacific', 'CO': 'US/Mountain', 'CT': 'US/Eastern', 'DE': 'US/Eastern',
    'FL': 'US/Eastern', 'GA': 'US/Eastern', 'HI': 'US/Hawaii', 'ID': 'US/Mountain',
    'IL': 'US/Central', 'IN': 'US/Eastern', 'IA': 'US/Central', 'KS': 'US/Central',
    'KY': 'US/Eastern', 'LA': 'US/Central', 'ME': 'US/Eastern', 'MD': 'US/Eastern',
    'MA': 'US/Eastern', 'MI': 'US/Eastern', 'MN': 'US/Central', 'MS': 'US/Central',
    'MO': 'US/Central', 'MT': 'US/Mountain', 'NE': 'US/Central', 'NV': 'US/Pacific',
    'NH': 'US/Eastern', 'NJ': 'US/Eastern', 'NM': 'US/Mountain', 'NY': 'US/Eastern',
    'NC': 'US/Eastern', 'ND': 'US/Central', 'OH': 'US/Eastern', 'OK': 'US/Central',
    'OR': 'US/Pacific', 'PA': 'US/Eastern', 'RI': 'US/Eastern', 'SC': 'US/Eastern',
    'SD': 'US/Central', 'TN': 'US/Central', 'TX': 'US/Central', 'UT': 'US/Mountain',
    'VT': 'US/Eastern', 'VA': 'US/Eastern', 'WA': 'US/Pacific', 'WV': 'US/Eastern',
    'WI': 'US/Central', 'WY': 'US/Mountain'
    }

    # Extract the state abbreviation from the filename
    # state_abbr = os.path.basename(filename).split('_')[2]  
    timezone = state_timezones.get(state_abbr)

    if timezone:
        # Convert the 'Date' column to datetime
        df['Date'] = pd.to_datetime(df['Date'], utc=True)
        
        # Convert to local time zone
        local_tz = pytz.timezone(timezone)
        df['Date_Local'] = df['Date'].dt.tz_convert(local_tz)

         # Save the timezone-aware Date_Local column
        df['Date_Local'] = df['Date_Local'].astype(str)
        df['Date_Local'] = df['Date_Local'].apply(lambda x: datetime.datetime.strptime(x, '%Y-%m-%d %H:%M:%S%z'))
        df['Date_Local'] = df['Date_Local'].apply(lambda x: x.replace(tzinfo=None))

    else:
        print(f"Timezone for state abbreviation {state_abbr} not found.")
        
    return df

def combine(snotel_files, nwm_files, StartDate, EndDate):

    # Create a dictionary to store dataframes
    dataframes = {}
    
    # Read SNOTEL files
    for file in snotel_files:
        location = os.path.basename(file).split('_')[1]  # Extract location from filename
        df = pd.read_csv(file)
        df['Date'] = pd.to_datetime(df['Date']).dt.date  # .dt.date is required because times are not excatly the same between SNOTEL and NWM
        dataframes[f'snotel_{location}'] = df.set_index('Date')
    
    # Read NWM files
    for file in nwm_files:
        location = os.path.basename(file).split('_')[1]  # Extract location from filename
        df = pd.read_csv(file)
        df['Date_Local'] = pd.to_datetime(df['Date_Local']).dt.date  # .dt.date is required because times are not excatly the same between SNOTEL and NWM
        dataframes[f'nwm_{location}'] = df.set_index('Date_Local')
    
    # Merge dataframes on Date
    combined_df = pd.DataFrame(index=pd.date_range(start=StartDate, end=EndDate))  
    for key, df in dataframes.items():
        if 'snotel' in key:
            combined_df[f'{key}_swe_m'] = df['Snow Water Equivalent (m) Start of Day Values']
        elif 'nwm' in key:
            combined_df[f'{key}_swe_m'] = df['NWM_SWE_meters']

    return combined_df

def get_usgs_streamflow(site_id, start_date="1980-01-01", end_date=datetime.datetime.today().strftime('%Y-%m-%d')):
    """
    Retrieves daily mean streamflow data from USGS NWIS.
    
    Parameters:
    site_id (str): The USGS station ID (e.g., '09380000')
    start_date (str): Beginning date in 'YYYY-MM-DD' format
    end_date (str): End date in 'YYYY-MM-DD' format
    """
    # Parameter code '00060' refers specifically to Discharge (streamflow) in cfs
    parameter_code = '00060'
    
    print(f"Retrieving data for Site: {site_id} from {start_date} to {end_date}...")
    
    try:
        # get_dv retrieves "Daily Values"
        # returns a DataFrame and a metadata object
        df, metadata = nwis.get_dv(
            sites=site_id, 
            start=start_date, 
            end=end_date, 
            parameterCd=parameter_code
        )
        
        # Clean up the column names for easier use
        # Usually, the flow data is in a column like '00060_Mean'
        df.rename(columns={f'{parameter_code}_00003': 'Streamflow_cfs'}, inplace=True)
        
        return df
        
    except Exception as e:
        print(f"An error occurred: {e}")
        return None


def get_GIMMS_NDVI_15day(basin_polygon_coords, begin_date=GIMMS_START_DATE, end_date=GIMMS_END_DATE):
    import ee

    dataset_start = pd.Timestamp(GIMMS_START_DATE)
    dataset_end = pd.Timestamp(GIMMS_END_DATE)
    begin_ts = pd.Timestamp(begin_date)
    end_ts = pd.Timestamp(end_date if end_date is not None else GIMMS_END_DATE)

    if end_ts < dataset_start or begin_ts > dataset_end:
        raise ValueError(
            f"Requested dates fall outside the GIMMS availability window of {GIMMS_START_DATE} to {GIMMS_END_DATE}."
        )

    begin_ts = max(begin_ts, dataset_start)
    end_ts = min(end_ts, dataset_end)

    print("Authenticating with Earth Engine...")
    ee.Authenticate()
    print("Initializing Earth Engine...")
    ee.Initialize()
    print("Earth Engine initialized successfully.")

    basin_polygon = ee.Geometry.Polygon(basin_polygon_coords)

    gimms_collection = (
        ee.ImageCollection("NASA/GIMMS/3GV0")
        .select("ndvi")
        .filterBounds(basin_polygon)
        .filterDate(begin_ts.strftime('%Y-%m-%d'), (end_ts + pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
    )

    results = gimms_collection.map(lambda img: get_all_metrics(img, basin_polygon)).getInfo()
    df = pd.DataFrame([feature['properties'] for feature in results['features']])

    if df.empty:
        empty_df = pd.DataFrame(columns=['ndvi'])
        empty_df.index = pd.DatetimeIndex([], name='Date')
        return empty_df

    cols = ['date'] + [column for column in df.columns if column != 'date']
    df = df[cols]
    df['date'] = pd.to_datetime(df['date'].str.split('T').str[0])
    df.rename(columns={'date': 'Date'}, inplace=True)
    df.set_index('Date', drop=True, inplace=True)
    df.sort_index(inplace=True)

    return df
    
 #Main Data Fetcher
def get_NLDAS_daily(basin_polygon_coords, begin_date='2025-01-01', end_date=None):
    #EE only needs to import in the function that is being called, so we can import it here to avoid issues with the other functions that are not being called in this script
    import ee
    print("Authenticating with Earth Engine...")
    ee.Authenticate()
    print("Initializing Earth Engine...")
    ee.Initialize()
    print("Earth Engine initialized successfully.")
    
    basin_polygon = ee.Geometry.Polygon(basin_polygon_coords)
    
    if end_date is None:
        end_date = datetime.datetime.today().strftime('%Y-%m-%d')
    
    # Load Hourly
    nldas_hourly = (ee.ImageCollection("NASA/NLDAS/FORA0125_H002")
                    .filterBounds(basin_polygon)
                    .filterDate(begin_date, end_date))
    
    # Setup Date Math
    start = ee.Date(begin_date)
    end = ee.Date(end_date)
    diff = end.difference(start, 'day')
    day_list = ee.List.sequence(0, diff.subtract(1))
    
    # Map Daily Aggregation
    daily_func = wrap_make_daily(nldas_hourly, start)
    daily_collection = ee.ImageCollection.fromImages(day_list.map(daily_func))
    
    # Map Spatial Reduction
    results = daily_collection.map(lambda img: get_all_metrics(img, basin_polygon)).getInfo()
    
    df = pd.DataFrame([f['properties'] for f in results['features']]) 
    
    # Reorder columns to put date first
    cols = ['date'] + [c for c in df.columns if c != 'date']
    df = df[cols]
    
    df['date'] = df['date'].str.split('T').str[0]
    df['date'] = pd.to_datetime(df['date'])
    df.rename(columns={'date':'Date'}, inplace=True)
    df.set_index('Date', drop = True, inplace = True)
    
    return df

#Temporal Reduction Wrapper (The "Outer" Function)
def wrap_make_daily(collection, start_date):
    def make_daily(day_offset):
        d = start_date.advance(day_offset, 'day')
        daily_images = collection.filterDate(d, d.advance(1, 'day'))
        
        return (daily_images.mean()
                .set('system:time_start', d.millis())
                .set('date', d.format('YYYY-MM-dd')))
    return make_daily
    
    
def get_NLDAS_hourly(basin_polygon_coords, begin_date = '2025-12-30', end_date = '2025-12-31'):
    import ee
    print("Authenticating with Earth Engine...")
    ee.Authenticate()
    print("Initializing Earth Engine...")
    ee.Initialize()
    print("Earth Engine initialized successfully.")
    basin_polygon = ee.Geometry.Polygon(basin_polygon_coords)
    #Load and filter the NLDAS-2 Collection
    nldas_collection = (ee.ImageCollection("NASA/NLDAS/FORA0125_H002")
    .filterBounds(basin_polygon)
    .filterDate(begin_date, end_date) # Define your timeframe
    )
    
    results = nldas_collection.map(lambda img: get_all_metrics(img, basin_polygon)).getInfo()

    df = pd.DataFrame([f['properties'] for f in results['features']])
        
    # Reorder columns to put date first
    cols = ['date'] + [c for c in df.columns if c != 'date']
    df = df[cols]
    df.rename(columns={'date':'Date'}, inplace=True)
    df.set_index('Date', drop = True, inplace = True)
    
    return df
    
# Spatial Reduction Function
def get_all_metrics(image, basin_polygon):
    import ee
    stats = image.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=basin_polygon,
        scale=12500,
        maxPixels=1e9
    )
    return ee.Feature(None, stats).set('date', image.date().format())
    

if __name__ == "__main__":
    import argparse
    from pynhd import NLDI
    import dataprocessing

    def _get_basin_polygon_coords(usgs_gage_id):
        basin = NLDI().get_basins(usgs_gage_id)
        geometry = basin.to_crs("EPSG:4326").geometry.iloc[0]
        return list(geometry.exterior.coords)

    parser = argparse.ArgumentParser(
        description="Download basin-mean GIMMS NDVI from Earth Engine and interpolate to daily."
    )
    parser.add_argument("--gage-id", default="11274790",
                        help="USGS gage ID used to define the basin through NLDI.")
    parser.add_argument("--start-date", default=GIMMS_START_DATE,
                        help="Start date (YYYY-MM-DD).")
    parser.add_argument("--end-date", default=GIMMS_END_DATE,
                        help="End date (YYYY-MM-DD).")
    parser.add_argument("--output-folder", default="files/GIMMS",
                        help="Folder where CSVs and plots will be written.")
    args = parser.parse_args()

    os.makedirs(args.output_folder, exist_ok=True)

    basin_polygon_coords = _get_basin_polygon_coords(args.gage_id)

    gimms_15day = get_GIMMS_NDVI_15day(
        basin_polygon_coords,
        begin_date=args.start_date,
        end_date=args.end_date,
    )

    gimms_daily = dataprocessing.interpolate_to_daily(gimms_15day)

    gimms_15day_out = gimms_15day.copy()
    gimms_15day_out['Date'] = gimms_15day_out.index
    gimms_daily_out = gimms_daily.copy()

    gimms_15day_csv = os.path.join(args.output_folder, f"GIMMS_NDVI_15day_{args.gage_id}.csv")
    gimms_daily_csv = os.path.join(args.output_folder, f"GIMMS_NDVI_daily_{args.gage_id}.csv")
    plot_path = os.path.join(args.output_folder, f"GIMMS_NDVI_{args.gage_id}.png")

    gimms_15day_out.to_csv(gimms_15day_csv, index=False)
    gimms_daily_out.to_csv(gimms_daily_csv, index=False)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(gimms_daily_out['Date'], gimms_daily_out['ndvi'],
            label='Daily interpolated NDVI', color='forestgreen')
    ax.scatter(gimms_15day_out['Date'], gimms_15day_out['ndvi'],
               label='15-day GIMMS NDVI', color='black', s=12)
    ax.set_title(f"GIMMS NDVI for Basin Upstream of USGS Gage {args.gage_id}")
    ax.set_xlabel('Date')
    ax.set_ylabel('NDVI')
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(plot_path, dpi=200)

    print(f"Saved 15-day data  : {gimms_15day_csv}")
    print(f"Saved daily data   : {gimms_daily_csv}")
    print(f"Saved plot         : {plot_path}")

