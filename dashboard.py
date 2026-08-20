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

# Page Setup
st.set_page_config(page_title="AD4 Crop Health", layout="wide", page_icon="🌱")
load_dotenv(override=True)

# Environment Variables
AWS_REGION = os.getenv("AWS_REGION", "us-east-2").strip()
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "ad4-raw-ingestion-2026-454014151118-us-east-2-an").strip().strip('\'"')
MAPBOX_TOKEN = os.getenv("MAPBOX_API_KEY", "")

# Initialize AWS S3 Client
try:
    s3_client = boto3.client('s3', region_name=AWS_REGION)
except Exception as e:
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
        # Soil
        cursor.execute(f"SELECT mapunit_name, organic_matter_pct, ph_water FROM farm_soil_properties WHERE farm_id = {farm_id}")
        data['soil'] = pd.DataFrame(cursor.fetchall(), columns=['Map Unit', 'OM %', 'pH'])
        
        # Crop History
        cursor.execute(f"SELECT crop_year, crop_name FROM farm_crop_history WHERE farm_id = {farm_id} ORDER BY crop_year DESC")
        data['crops'] = pd.DataFrame(cursor.fetchall(), columns=['Year', 'Crop'])
        
        # Weather
        cursor.execute(f"SELECT forecast_time, temperature_f, wind_speed_mph, precip_probability_pct, short_forecast FROM farm_weather_forecasts WHERE farm_id = {farm_id} ORDER BY forecast_time LIMIT 12")
        data['weather'] = pd.DataFrame(cursor.fetchall(), columns=['Time', 'Temp (F)', 'Wind (mph)', 'Precip %', 'Forecast'])
    return data

@st.cache_data(ttl=300)
def load_spatial_detections(base_lat, base_lon):
    """Fetches image records and simulates coordinates over the target farm."""
    query = """
        SELECT im.image_id, im.s3_key, tc.display_name as species, aa.feature_type, aa.confidence_score
        FROM imagery_metadata im
        JOIN agricultural_annotations aa ON im.image_id = aa.image_id
        JOIN taxonomy_catalog tc ON aa.taxonomy_id = tc.taxonomy_id
        LIMIT 100;
    """
    with get_db_cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()
    
    df = pd.DataFrame(rows, columns=["image_id", "s3_key", "species", "feature_type", "confidence"])
    
    # SIMULATE MVP DATA: Randomize the S3 image points inside Brad Hocking's field boundary 
    # instead of Australia so the Mapbox visual looks authentic for a Midwest farmer.
    np.random.seed(42)
    df["lat"] = base_lat + np.random.uniform(-0.002, 0.002, size=len(df))
    df["lon"] = base_lon + np.random.uniform(-0.003, 0.003, size=len(df))
    return df

@st.cache_data(ttl=300)
def load_taxonomy_counts():
    """Queries PostGIS for class detection counts."""
    query = """
        SELECT tc.display_name, COUNT(aa.annotation_id) as total_detections
        FROM agricultural_annotations aa
        JOIN taxonomy_catalog tc ON aa.taxonomy_id = tc.taxonomy_id
        GROUP BY tc.display_name ORDER BY total_detections DESC;
    """
    with get_db_cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()
    return pd.DataFrame(rows, columns=["Weed Species", "Detection Count"])

# ==========================================
# 2. LOAD DATA & SETUP UI
# ==========================================
farm = fetch_farm_data()
if not farm:
    st.error("No active farm found in the database. Run your extraction scripts first.")
    st.stop()

agro_data = fetch_agronomic_data(farm['farm_id'])
df_spatial = load_spatial_detections(farm['lat'], farm['lon'])
df_summary = load_taxonomy_counts()

# Header & KPIs
st.title(f"🌱 {farm['customer_name']} - Crop Health & Farm Intelligence")
st.markdown("Real-time telemetry, agronomic data, and AWS S3 drone imagery inspection.")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Farm Location", "Mount Carmel, IL")
col2.metric("Avg Soil OM", f"{agro_data['soil']['OM %'].mean():.1f}%" if not agro_data['soil'].empty else "N/A")
col3.metric("Last Crop (2024)", agro_data['crops']['Crop'].iloc[0] if not agro_data['crops'].empty else "N/A")
col4.metric("Weed Detections (S3)", f"{len(df_spatial)}")

st.markdown("---")

# ==========================================
# 3. TABBED DASHBOARD INTERFACE
# ==========================================
tab1, tab2, tab3 = st.tabs(["🗺️ Field Map & Soil", "🌤️ Spray Windows", "🖼️ Drone Diagnostics (S3)"])

# --- TAB 1: FIELD MAP & AGRONOMICS ---
with tab1:
    col_map, col_data = st.columns([2, 1])
    
    with col_map:
        st.subheader("Geospatial Field View")
        # Build PyDeck Mapbox Map
        view_state = pdk.ViewState(latitude=farm["lat"], longitude=farm["lon"], zoom=14, pitch=30)
        
        # Layer 1: Farm Boundary Polygon
        boundary_layer = pdk.Layer(
            "GeoJsonLayer",
            data=farm["boundary"],
            get_fill_color=[0, 255, 0, 40], # Transparent green
            get_line_color=[0, 255, 0, 255],
            line_width_min_pixels=3,
        )
        
        # Layer 2: Weed Detection Scatterplot
        weed_layer = pdk.Layer(
            "ScatterplotLayer",
            data=df_spatial,
            get_position=["lon", "lat"],
            get_fill_color=[235, 60, 60, 200], # Red dots
            get_radius=10,
            pickable=True
        )

        deck = pdk.Deck(
            layers=[boundary_layer, weed_layer],
            initial_view_state=view_state,
            map_style="mapbox://styles/mapbox/satellite-v9" if MAPBOX_TOKEN else "light",
            api_keys={"mapbox": MAPBOX_TOKEN} if MAPBOX_TOKEN else None,
            tooltip={"text": "Species: {species}\nConfidence: {confidence}\nS3 Key: {s3_key}"}
        )
        st.pydeck_chart(deck)

    with col_data:
        st.subheader("USDA Soil Properties")
        st.dataframe(agro_data['soil'], hide_index=True, use_container_width=True)
        
        st.subheader("USDA Crop History")
        st.dataframe(agro_data['crops'], hide_index=True, use_container_width=True)


# --- TAB 2: SPRAY WINDOWS (WEATHER) ---
with tab2:
    st.subheader("Next 12 Hours: Herbicide Application Windows")
    st.write("Cross-referencing live NWS wind and precipitation data to prevent chemical drift.")
    
    if not agro_data['weather'].empty:
        for index, row in agro_data['weather'].iterrows():
            time_str = pd.to_datetime(row['Time']).strftime('%I:%M %p')
            wind = float(row['Wind (mph)'])
            rain = float(row['Precip %'])
            
            # Simple Agronomic Logic: Wind 3-10mph (prevents drift/inversion), Rain < 20%
            if 3 <= wind <= 10 and rain < 20:
                st.success(f"**{time_str}** | Temp: {row['Temp (F)']}°F | Wind: {wind} mph | Rain: {rain}% ➔ **SAFE TO SPRAY**")
            else:
                st.error(f"**{time_str}** | Temp: {row['Temp (F)']}°F | Wind: {wind} mph | Rain: {rain}% ➔ **DO NOT SPRAY**")


# --- TAB 3: DRONE S3 INSPECTOR ---
with tab3:
    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("📊 Detected Weed Taxonomy")
        st.dataframe(df_summary, hide_index=True, use_container_width=True)

    with col_right:
        st.subheader("🖼️ Live AWS S3 Asset Inspector")
        if not df_spatial.empty:
            selected_key = st.selectbox("Select Asset to Preview:", df_spatial["s3_key"].tolist())
            
            try:
                # Generate temporary 1-hour secure URL for browser display
                presigned_url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': S3_BUCKET_NAME, 'Key': selected_key},
                    ExpiresIn=3600
                )
                st.image(presigned_url, caption=f"Pulled from AWS S3: {selected_key}", use_container_width=True)
            except Exception as e:
                st.error("Could not fetch image. Ensure your S3 bucket name and AWS credentials are correct in the .env file.")