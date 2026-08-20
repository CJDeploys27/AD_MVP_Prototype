import sys
import os
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utilities.db_connector import get_db_cursor

# 1. Database Table Creation
CREATE_SOIL_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS farm_soil_properties (
    soil_id SERIAL PRIMARY KEY,
    farm_id INT REFERENCES customer_farms(farm_id),
    mukey VARCHAR(30) NOT NULL,
    mapunit_name VARCHAR(200),
    organic_matter_pct NUMERIC(4, 2),
    ph_water NUMERIC(3, 1),
    texture_class VARCHAR(100),
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_farm_mukey UNIQUE(farm_id, mukey)
);
"""

INSERT_SOIL_DATA_SQL = """
INSERT INTO farm_soil_properties (farm_id, mukey, mapunit_name, organic_matter_pct, ph_water, texture_class)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (farm_id, mukey) DO UPDATE SET
    organic_matter_pct = EXCLUDED.organic_matter_pct,
    ph_water = EXCLUDED.ph_water,
    texture_class = EXCLUDED.texture_class,
    fetched_at = CURRENT_TIMESTAMP;
"""

def extract_ssurgo_data():
    print("🌱 Initializing USDA SSURGO Soil Extraction...")
    
    # Get farm boundary WKT from PostGIS
    with get_db_cursor(commit=False) as cursor:
        cursor.execute("SELECT farm_id, ST_AsText(farm_boundary) FROM customer_farms WHERE is_active = TRUE LIMIT 1;")
        record = cursor.fetchone()
        if not record:
            print("❌ No active farm boundary found in database.")
            return
        farm_id, wkt_geom = record

    sda_url = "https://sdmdataaccess.nrcs.usda.gov/tabular/post.rest"
    
    # Corrected relational joins: mapunit -> component -> chorizon -> chtexturegrp
    sda_sql = f"""
    SELECT DISTINCT
        m.mukey, 
        m.muname, 
        ch.om_r, 
        ch.ph1to1h2o_r, 
        cht.texture
    FROM mapunit m
    INNER JOIN component c ON m.mukey = c.mukey
    INNER JOIN chorizon ch ON c.cokey = ch.cokey
    LEFT JOIN chtexturegrp cht ON ch.chkey = cht.chkey AND (cht.rvindicator = 'Yes' OR cht.rvindicator IS NULL)
    WHERE m.mukey IN (
        SELECT mukey FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt_geom}')
    ) 
    AND c.majcompflag = 'Yes'
    AND ch.hzdept_r = 0;
    """

    payload = {
        "query": sda_sql,
        "format": "JSON+COLUMNNAME"
    }
    
    response = requests.post(sda_url, data=payload)
    
    if response.status_code != 200:
        print(f"❌ USDA SDA API request failed with status code {response.status_code}: {response.text}")
        return

    res_json = response.json()
    table_data = res_json.get("Table", [])
    
    if len(table_data) <= 1:
        print("⚠️ No soil polygons matched the boundary geometry.")
        return

    data_rows = table_data[1:]

    # Ingest into PostGIS
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(CREATE_SOIL_TABLE_SQL)
        for row in data_rows:
            mukey, muname, om, ph, texture = row[0], row[1], row[2], row[3], row[4]
            om_val = float(om) if om is not None else None
            ph_val = float(ph) if ph is not None else None
            cursor.execute(INSERT_SOIL_DATA_SQL, (farm_id, str(mukey), muname, om_val, ph_val, texture))
            
    print(f"✅ Successfully ingested {len(data_rows)} SSURGO soil map unit records into PostGIS!")

if __name__ == "__main__":
    extract_ssurgo_data()