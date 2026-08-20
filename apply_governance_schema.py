from utilities.db_connector import get_db_cursor

GOVERNANCE_SQL = """
-- ============================================================================
-- 1. TAXONOMY CATALOG & TAG STANDARDIZATION
-- ============================================================================
CREATE TABLE IF NOT EXISTS taxonomy_catalog (
    taxonomy_id SERIAL PRIMARY KEY,
    canonical_code VARCHAR(100) UNIQUE NOT NULL CHECK (canonical_code ~ '^[a-z0-9_]+$'), -- Enforces lowercase snake_case
    display_name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL CHECK (category IN ('Crop', 'Weed', 'Disease', 'Pest', 'Soil')),
    agrovoc_id VARCHAR(100), -- UN FAO International Agricultural Taxonomy Reference
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Seed Initial Standardized Crop & Weed Tags
INSERT INTO taxonomy_catalog (canonical_code, display_name, category, agrovoc_id)
VALUES 
    ('ziziphus_mauritiana', 'Chinee Apple', 'Weed', 'c_8481'),
    ('zea_mays', 'Corn / Maize', 'Crop', 'c_1234'),
    ('parthenium_hysterophorus', 'Parthenium', 'Weed', 'c_25632'),
    ('solanum_tuberosum', 'Potato', 'Crop', 'c_7256'),
    ('glycine_max', 'Soybean', 'Crop', 'c_3311')
ON CONFLICT (canonical_code) DO NOTHING;


-- ============================================================================
-- 2. MACRO DATASET GOVERNANCE (datasets Table)
-- ============================================================================
ALTER TABLE datasets 
    ADD COLUMN IF NOT EXISTS terms_of_service_url TEXT,
    ADD COLUMN IF NOT EXISTS commercial_use_allowed BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS attribution_required BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS access_type VARCHAR(50) DEFAULT 'Public Domain';


-- ============================================================================
-- 3. MICRO ASSET LINEAGE & PROVENANCE (imagery_metadata Table)
-- ============================================================================
ALTER TABLE imagery_metadata 
    ADD COLUMN IF NOT EXISTS source_url TEXT,
    ADD COLUMN IF NOT EXISTS provider_scene_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS ingested_by_daemon VARCHAR(100),
    ADD COLUMN IF NOT EXISTS raw_metadata_json JSONB;


-- ============================================================================
-- 4. BOUNDING BOX & ANNOTATION STANDARDIZATION (agricultural_annotations Table)
-- ============================================================================
-- A. Link Annotations directly to Centralized Taxonomy
DO $$ 
BEGIN 
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name='agricultural_annotations' AND column_name='taxonomy_id'
    ) THEN
        ALTER TABLE agricultural_annotations 
        ADD COLUMN taxonomy_id INTEGER REFERENCES taxonomy_catalog(taxonomy_id) ON DELETE SET NULL;
    END IF;
END $$;

-- B. Add Standardized Bounding Box Format & Normalized Attributes
ALTER TABLE agricultural_annotations
    ADD COLUMN IF NOT EXISTS bbox_format VARCHAR(30) DEFAULT 'WKT_POLYGON' 
        CHECK (bbox_format IN ('WKT_POLYGON', 'YOLO_NORMALIZED', 'COCO_PIXEL', 'VOC_XML')),
    ADD COLUMN IF NOT EXISTS normalized_xmin NUMERIC(5,4) CHECK (normalized_xmin BETWEEN 0.0 AND 1.0),
    ADD COLUMN IF NOT EXISTS normalized_ymin NUMERIC(5,4) CHECK (normalized_ymin BETWEEN 0.0 AND 1.0),
    ADD COLUMN IF NOT EXISTS normalized_xmax NUMERIC(5,4) CHECK (normalized_xmax BETWEEN 0.0 AND 1.0),
    ADD COLUMN IF NOT EXISTS normalized_ymax NUMERIC(5,4) CHECK (normalized_ymax BETWEEN 0.0 AND 1.0);

-- C. Enforce xmax > xmin and ymax > ymin on Normalized Coordinates
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_valid_normalized_bbox_bounds'
    ) THEN
        ALTER TABLE agricultural_annotations
        ADD CONSTRAINT check_valid_normalized_bbox_bounds 
        CHECK (
            (normalized_xmax IS NULL OR normalized_xmin IS NULL OR normalized_xmax > normalized_xmin) AND
            (normalized_ymax IS NULL OR normalized_ymin IS NULL OR normalized_ymax > normalized_ymin)
        );
    END IF;
END $$;


-- ============================================================================
-- 5. TOPOLOGICAL & GEOMETRY QUALITY CONSTRAINTS
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_valid_bounding_box'
    ) THEN
        ALTER TABLE agricultural_annotations
        ADD CONSTRAINT check_valid_bounding_box CHECK (bounding_box IS NULL OR ST_IsValid(bounding_box));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_valid_image_extent'
    ) THEN
        ALTER TABLE imagery_metadata
        ADD CONSTRAINT check_valid_image_extent CHECK (image_extent IS NULL OR ST_IsValid(image_extent));
    END IF;
END $$;


-- ============================================================================
-- 6. PERFORMANCE & AUDIT INDEXES
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_annotations_taxonomy ON agricultural_annotations(taxonomy_id);
CREATE INDEX IF NOT EXISTS idx_annotations_bbox_format ON agricultural_annotations(bbox_format);
CREATE INDEX IF NOT EXISTS idx_imagery_jsonb_gin ON imagery_metadata USING GIN (raw_metadata_json);
CREATE INDEX IF NOT EXISTS idx_datasets_commercial ON datasets (commercial_use_allowed);
"""

def apply_governance_updates():
    print("🛡️ Applying Full Governance Schema & Standardization Rules to PostGIS...")
    try:
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(GOVERNANCE_SQL)
        print("✅ Governance updates applied successfully!")
        print("   ├─ Tag Standard: Enforced lowercase snake_case taxonomy catalog.")
        print("   ├─ Bounding Box Standard: Added format tags & 0.0–1.0 normalized bounds.")
        print("   ├─ Lineage: Added macro legal & micro provenance tracking fields.")
        print("   └─ Quality: Enforced PostGIS ST_IsValid() constraints.")
    except Exception as e:
        print(f"❌ Failed to apply governance schema: {e}")

if __name__ == "__main__":
    apply_governance_updates()