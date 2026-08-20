import sys
import os
import re
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utilities.db_connector import get_db_cursor

CREATE_CDL_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS farm_crop_history (
    history_id SERIAL PRIMARY KEY,
    farm_id INT REFERENCES customer_farms(farm_id),
    crop_year INT NOT NULL,
    crop_name VARCHAR(100) NOT NULL,
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_farm_year UNIQUE(farm_id, crop_year)
);
"""

INSERT_CDL_SQL = """
INSERT INTO farm_crop_history (farm_id, crop_year, crop_name)
VALUES (%s, %s, %s)
ON CONFLICT (farm_id, crop_year) DO UPDATE SET
    crop_name = EXCLUDED.crop_name,
    fetched_at = CURRENT_TIMESTAMP;
"""

def extract_cdl_history():
    print("🌽 Initializing USDA Cropland Data Layer (CDL) Crop History Extraction...")
    
    with get_db_cursor(commit=False) as cursor:
        cursor.execute("""
            SELECT 
                farm_id, 
                customer_name,
                ST_X(ST_Transform(ST_Centroid(farm_boundary), 5070)) as x_albers, 
                ST_Y(ST_Transform(ST_Centroid(farm_boundary), 5070)) as y_albers
            FROM customer_farms 
            WHERE is_active = TRUE 
            ORDER BY farm_id DESC 
            LIMIT 1;
        """)
        record = cursor.fetchone()
        if not record:
            print("❌ No active farm boundary found in database.")
            return
        farm_id, customer_name, x_albers, y_albers = record
        print(f"📍 Target Active Farm: {customer_name} (Farm ID: {farm_id})")

    years = [2020, 2021, 2022, 2023, 2024]
    crops_retrieved = 0

    with get_db_cursor(commit=True) as cursor:
        cursor.execute(CREATE_CDL_TABLE_SQL)
        for year in years:
            url = f"https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLValue?year={year}&x={x_albers:.3f}&y={y_albers:.3f}"
            response = requests.get(url)
            
            if response.status_code == 200:
                match = re.search(r'category:\s*"([^"]+)"', response.text, re.IGNORECASE)
                if match:
                    crop_name = match.group(1).strip()
                    cursor.execute(INSERT_CDL_SQL, (farm_id, year, crop_name))
                    crops_retrieved += 1
                    print(f"  └─ Year {year}: Detected '{crop_name}'")
                else:
                    print(f"  └─ Year {year}: Response parsing error.")
            else:
                print(f"  └─ Year {year}: API HTTP error {response.status_code}")

    print(f"✅ Ingested {crops_retrieved} yearly crop records into PostGIS!")

if __name__ == "__main__":
    extract_cdl_history()