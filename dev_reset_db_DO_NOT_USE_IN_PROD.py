from utilities.db_connector import get_db_cursor

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS postgis;

DROP TABLE IF EXISTS agricultural_annotations CASCADE;
DROP TABLE IF EXISTS macro_boundaries CASCADE;
DROP TABLE IF EXISTS imagery_metadata CASCADE;
DROP TABLE IF EXISTS datasets CASCADE;

CREATE TABLE datasets (
    dataset_id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    dataset_group VARCHAR(100) NOT NULL,
    license_type VARCHAR(50) DEFAULT 'CC BY 4.0',
    attribution TEXT,
    terms_of_service_url TEXT,
    commercial_use_allowed BOOLEAN DEFAULT FALSE,
    attribution_required BOOLEAN DEFAULT TRUE,
    access_type VARCHAR(50) DEFAULT 'Public Domain',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE imagery_metadata (
    image_id SERIAL PRIMARY KEY,
    dataset_id INTEGER REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    s3_key VARCHAR(500) UNIQUE NOT NULL,
    file_checksum VARCHAR(64) UNIQUE,
    source_url TEXT,
    provider_scene_id VARCHAR(255),
    ingested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    ingested_by_daemon VARCHAR(100),
    raw_metadata_json JSONB,
    image_extent geometry(Polygon, 4326)
);

CREATE TABLE agricultural_annotations (
    annotation_id SERIAL PRIMARY KEY,
    image_id INTEGER REFERENCES imagery_metadata(image_id) ON DELETE CASCADE,
    feature_type VARCHAR(50) NOT NULL,
    class_name VARCHAR(100) NOT NULL,
    bounding_box geometry(Polygon, 0),
    confidence_score DECIMAL(3,2) CHECK (confidence_score BETWEEN 0.0 AND 1.0)
);

CREATE TABLE macro_boundaries (
    boundary_id SERIAL PRIMARY KEY,
    dataset_id INTEGER REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    boundary_geom geometry(Polygon, 4326),
    region_name VARCHAR(100)
);

CREATE INDEX idx_agricultural_spatial ON agricultural_annotations USING GIST (bounding_box);
CREATE INDEX idx_macro_spatial ON macro_boundaries USING GIST (boundary_geom);
CREATE INDEX idx_imagery_extent_spatial ON imagery_metadata USING GIST (image_extent);
CREATE INDEX idx_imagery_jsonb_gin ON imagery_metadata USING GIN (raw_metadata_json);
CREATE INDEX idx_datasets_commercial ON datasets (commercial_use_allowed);
"""

def update_database_schema():
    print("🛠️ Applying updated PostGIS governance schema...")
    try:
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(SCHEMA_SQL)
        print("✅ Database schema updated successfully with macro & micro lineage support!")
    except Exception as e:
        print(f"❌ Failed to update schema: {e}")

if __name__ == "__main__":
    update_database_schema()