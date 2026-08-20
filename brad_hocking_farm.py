import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utilities.db_connector import get_db_cursor

SETUP_FARMS_SQL = """
-- 1. Create Customer Farms Table
CREATE TABLE IF NOT EXISTS customer_farms (
    farm_id SERIAL PRIMARY KEY,
    customer_name VARCHAR(100) NOT NULL,
    farm_name VARCHAR(100) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    farm_boundary GEOMETRY(Polygon, 4326) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Spatial Index
CREATE INDEX IF NOT EXISTS idx_customer_farms_boundary 
ON customer_farms USING GIST (farm_boundary);

-- 3. Deactivate previous test records
UPDATE customer_farms SET is_active = FALSE;

-- 4. Seed Target Customer Farm (Brad Hocking Farms - Mount Carmel, IL)
INSERT INTO customer_farms (customer_name, farm_name, is_active, farm_boundary)
VALUES (
    'Brad Hocking',
    'Mount Carmel Field 01',
    TRUE,
    ST_SetSRID(
        ST_GeomFromGeoJSON('{
            "type": "Polygon",
            "coordinates": [[
                [-87.8814613, 38.3300698],
                [-87.8795058, 38.3300178],
                [-87.8793401, 38.3275998],
                [-87.8791744, 38.3262998],
                [-87.8789755, 38.3261438],
                [-87.8786109, 38.3261958],
                [-87.8784784, 38.3262218],
                [-87.8785447, 38.3255977],
                [-87.8787435, 38.3253117],
                [-87.8789755, 38.3249217],
                [-87.8790418, 38.3246357],
                [-87.8791744, 38.3245577],
                [-87.881627, 38.3246097],
                [-87.8815939, 38.3278338],
                [-87.8814613, 38.3300698]
            ]]
        }'),
        4326
    )
);
"""

def setup_customer_farms():
    print("🌾 Setting up customer farms and locking Brad Hocking as the active target...")
    try:
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(SETUP_FARMS_SQL)
        print("✅ Brad Hocking farm polygon successfully seeded and set to ACTIVE!")
    except Exception as e:
        print(f"❌ Error seeding farm boundary: {e}")

if __name__ == "__main__":
    setup_customer_farms()