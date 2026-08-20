import sys
import os
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utilities.db_connector import get_db_cursor

# 1. Database Table Creation
CREATE_WEATHER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS farm_weather_forecasts (
    forecast_id SERIAL PRIMARY KEY,
    farm_id INT REFERENCES customer_farms(farm_id),
    forecast_time TIMESTAMP WITH TIME ZONE NOT NULL,
    temperature_f NUMERIC(4, 1),
    wind_speed_mph NUMERIC(4, 1),
    wind_direction VARCHAR(10),
    precip_probability_pct NUMERIC(3, 0),
    short_forecast VARCHAR(255),
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_farm_forecast_time UNIQUE(farm_id, forecast_time)
);
"""

INSERT_WEATHER_SQL = """
INSERT INTO farm_weather_forecasts 
    (farm_id, forecast_time, temperature_f, wind_speed_mph, wind_direction, precip_probability_pct, short_forecast)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (farm_id, forecast_time) DO UPDATE SET
    temperature_f = EXCLUDED.temperature_f,
    wind_speed_mph = EXCLUDED.wind_speed_mph,
    wind_direction = EXCLUDED.wind_direction,
    precip_probability_pct = EXCLUDED.precip_probability_pct,
    short_forecast = EXCLUDED.short_forecast,
    fetched_at = CURRENT_TIMESTAMP;
"""

def extract_nws_weather():
    print("🌤️ Initializing NWS Weather Forecast Ingestion...")
    
    with get_db_cursor(commit=False) as cursor:
        cursor.execute("""
            SELECT farm_id, ST_Y(ST_Centroid(farm_boundary)), ST_X(ST_Centroid(farm_boundary)) 
            FROM customer_farms WHERE is_active = TRUE LIMIT 1;
        """)
        record = cursor.fetchone()
        if not record:
            print("❌ No active farm boundary found in database.")
            return
        farm_id, lat, lon = record

    headers = {"User-Agent": "(AgriAIPipeline, contact@agriplatform.com)"}
    points_url = f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
    
    # Step 1: Resolve lat/lon to NWS forecast URL
    res = requests.get(points_url, headers=headers)
    if res.status_code != 200:
        print(f"❌ Failed to fetch NWS grid point metadata: {res.status_code}")
        return
        
    forecast_hourly_url = res.json()["properties"]["forecastHourly"]
    
    # Step 2: Fetch hourly forecast records
    forecast_res = requests.get(forecast_hourly_url, headers=headers)
    if forecast_res.status_code != 200:
        print(f"❌ Failed to fetch NWS hourly forecast data: {forecast_res.status_code}")
        return

    periods = forecast_res.json()["properties"]["periods"]

    with get_db_cursor(commit=True) as cursor:
        cursor.execute(CREATE_WEATHER_TABLE_SQL)
        for period in periods:
            time_str = period["startTime"]
            temp = float(period["temperature"])
            
            # Parse wind speed string e.g. "7 mph" -> 7.0
            wind_str = period.get("windSpeed", "0 mph").split()[0]
            wind_speed = float(wind_str) if wind_str.isdigit() else 0.0
            
            wind_dir = period.get("windDirection", "N/A")
            precip_prob = period.get("probabilityOfPrecipitation", {}).get("value", 0)
            short_fc = period.get("shortForecast", "")

            cursor.execute(INSERT_WEATHER_SQL, (
                farm_id, time_str, temp, wind_speed, wind_dir, precip_prob, short_fc
            ))

    print(f"✅ Successfully updated {len(periods)} hourly forecast periods in PostGIS!")

if __name__ == "__main__":
    extract_nws_weather()