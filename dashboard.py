import os
import sys
import boto3
import json
import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st
from dotenv import load_dotenv

# Path setup to import local DB connector
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utilities.db_connector import get_db_cursor
from drone_tab import render as render_drone_tab

# Page Setup
st.set_page_config(page_title="AD4 Crop Health", layout="wide", page_icon="🌱")
load_dotenv(override=True)

# Environment Variables
AWS_REGION = os.getenv("AWS_REGION", "us-east-2").strip()
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "ad4-raw-ingestion-2026-454014151118-us-east-2-an").strip().strip('\'"')
PROCESSED_S3_BUCKET_NAME = os.getenv("PROCESSED_S3_BUCKET_NAME", "ad4-processed-training-2026-454014151118-us-east-2-an").strip().strip('\'"')
MAPBOX_TOKEN = os.getenv("MAPBOX_API_KEY", "")

# Initialize AWS S3 Client
try:
    s3_client = boto3.client('s3', region_name=AWS_REGION)
except Exception as e:
    s3_client = None  # keep defined so tabs that use it don't NameError
    st.sidebar.error("AWS S3 Connection Error. Check your .env file.")

# ==========================================
# 1. DATABASE FETCHING FUNCTIONS (CACHED)
# ==========================================
@st.cache_data(ttl=3600)
def fetch_farm_data():
    """Fetches the active farm boundary and centroid from PostGIS."""
    query = """
    SELECT farm_id, customer_name, ST_AsGeoJSON(farm_boundary) as boundary,
           ST_Y(ST_Centroid(farm_boundary)) as lat, ST_X(ST_Centroid(farm_boundary)) as lon
    FROM customer_farms WHERE is_active = TRUE LIMIT 1;
    """
    with get_db_cursor() as cursor:
        cursor.execute(query)
        record = cursor.fetchone()
    
    if record:
        return {"farm_id": record[0], "customer_name": record[1], 
                "boundary": json.loads(record[2]), "lat": record[3], "lon": record[4]}
    return None

@st.cache_data(ttl=3600)
def fetch_agronomic_data(farm_id):
    """Fetches soil, weather, and crop history for the specific farm."""
    data = {}
    with get_db_cursor() as cursor:
        # Soil (parameterized — no string interpolation of ids into SQL)
        cursor.execute("SELECT mapunit_name, organic_matter_pct, ph_water FROM farm_soil_properties WHERE farm_id = %s", (farm_id,))
        data['soil'] = pd.DataFrame(cursor.fetchall(), columns=['Map Unit', 'OM %', 'pH'])

        # Crop History
        cursor.execute("SELECT crop_year, crop_name FROM farm_crop_history WHERE farm_id = %s ORDER BY crop_year DESC", (farm_id,))
        data['crops'] = pd.DataFrame(cursor.fetchall(), columns=['Year', 'Crop'])

        # Weather
        cursor.execute("SELECT forecast_time, temperature_f, wind_speed_mph, precip_probability_pct, short_forecast FROM farm_weather_forecasts WHERE farm_id = %s ORDER BY forecast_time LIMIT 12", (farm_id,))
        data['weather'] = pd.DataFrame(cursor.fetchall(), columns=['Time', 'Temp (F)', 'Wind (mph)', 'Precip %', 'Forecast'])
    return data

# (Removed the DeepWeeds baseline loaders — the app no longer uses the abandoned
#  third-party weed dataset; first-party drone data is served by drone_tab.py.)

# ==========================================
# 2. LOAD DATA (resilient)
# ==========================================
# The Drone Crop Health tab reads first-party maps straight from S3, so a
# missing or unreachable PostGIS database must NOT stop the whole app — it just
# limits the agronomic tabs.
farm, agro_data, db_error = None, None, None
try:
    farm = fetch_farm_data()
    if farm:
        agro_data = fetch_agronomic_data(farm['farm_id'])
except Exception as e:
    db_error = str(e)

st.title(f"🌱 {farm['customer_name'] if farm else 'AD4'} — Crop Health & Farm Intelligence")
st.markdown("First-party drone crop-health maps, USDA agronomic data, and AWS S3 imagery.")

if db_error:
    st.sidebar.warning("Database not reachable — agronomic tabs are limited. "
                       "The Drone Crop Health tab reads S3 directly and still works.")
elif not farm:
    st.sidebar.info("No active farm in the database yet — the agronomic tabs fill in "
                    "once the extraction scripts have run.")

st.markdown("---")

# ==========================================
# 3. TABBED DASHBOARD INTERFACE
# ==========================================
# Drone Crop Health leads: it's the validated, first-party, S3-only view.
tab_drone, tab_map, tab_spray = st.tabs(
    ["🛰️ Drone Crop Health", "🗺️ Field Map & Soil", "🌤️ Spray Windows"])

# --- DRONE CROP HEALTH (first-party imagery, read from S3, no DB) ---
with tab_drone:
    render_drone_tab(globals().get("s3_client"), PROCESSED_S3_BUCKET_NAME, MAPBOX_TOKEN)

# --- FIELD MAP & SOIL (needs the database) ---
with tab_map:
    if not farm:
        st.info("Connect the PostGIS database to see the farm boundary and USDA "
                "soil / crop history here.")
    else:
        col_map, col_data = st.columns([2, 1])
        with col_map:
            st.subheader("Geospatial Field View")
            view_state = pdk.ViewState(latitude=farm["lat"], longitude=farm["lon"], zoom=14, pitch=30)
            boundary_layer = pdk.Layer(
                "GeoJsonLayer", data=farm["boundary"],
                get_fill_color=[0, 255, 0, 40], get_line_color=[0, 255, 0, 255],
                line_width_min_pixels=3)
            deck = pdk.Deck(
                layers=[boundary_layer], initial_view_state=view_state,
                map_style="mapbox://styles/mapbox/satellite-v9" if MAPBOX_TOKEN else "light",
                api_keys={"mapbox": MAPBOX_TOKEN} if MAPBOX_TOKEN else None)
            st.pydeck_chart(deck)
        with col_data:
            st.subheader("USDA Soil Properties")
            st.dataframe(agro_data['soil'], hide_index=True, use_container_width=True)
            st.subheader("USDA Crop History")
            st.dataframe(agro_data['crops'], hide_index=True, use_container_width=True)

# --- SPRAY WINDOWS (needs the database) ---
with tab_spray:
    st.subheader("Next 12 Hours: Herbicide Application Windows")
    st.write("Cross-referencing live NWS wind and precipitation data to prevent chemical drift.")
    if not agro_data or agro_data['weather'].empty:
        st.info("Spray windows appear once the database has forecast data for the active farm.")
    else:
        for _, row in agro_data['weather'].iterrows():
            time_str = pd.to_datetime(row['Time']).strftime('%I:%M %p')
            wind = float(row['Wind (mph)'])
            rain = float(row['Precip %'])
            # Wind 3-10mph (prevents drift/inversion), Rain < 20%
            if 3 <= wind <= 10 and rain < 20:
                st.success(f"**{time_str}** | Temp: {row['Temp (F)']}°F | Wind: {wind} mph | Rain: {rain}% ➔ **SAFE TO SPRAY**")
            else:
                st.error(f"**{time_str}** | Temp: {row['Temp (F)']}°F | Wind: {wind} mph | Rain: {rain}% ➔ **DO NOT SPRAY**")
