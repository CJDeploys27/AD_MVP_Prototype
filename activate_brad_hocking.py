import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utilities.db_connector import get_db_cursor

FIX_ACTIVE_FARM_SQL = """
-- 1. Deactivate all existing farm records
UPDATE customer_farms SET is_active = FALSE;

-- 2. Insert or Update Brad Hocking Farm as active
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

def set_active_farm():
    print("🔄 Updating PostGIS records to set Brad Hocking as active...")
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(FIX_ACTIVE_FARM_SQL)
    print("✅ Brad Hocking Farms is now the ONLY active farm in your database!")

if __name__ == "__main__":
    set_active_farm()