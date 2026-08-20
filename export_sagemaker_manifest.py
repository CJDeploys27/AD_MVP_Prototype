import os
import sys
import csv
import boto3
from dotenv import load_dotenv

# --- MUST BE PLACED BEFORE ANY IMPORTS FROM UTILITIES ---
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utilities.db_connector import get_db_cursor
# --------------------------------------------------------

load_dotenv(override=True)

# 1. Environment Configuration
AWS_REGION = os.getenv("AWS_REGION", "us-east-2").strip()
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "ad4-raw-ingestion-2026-454014151118-us-east-2-an").strip().strip('\'"')

# Local and Cloud Manifest Destinations
LOCAL_MANIFEST_PATH = "data/train_manifest.csv"
S3_MANIFEST_KEY = "manifests/train_manifest.csv"

# Map PostGIS canonical codes to zero-indexed numerical class IDs for SageMaker model training
TAXONOMY_CLASS_INDEX = {
    "ziziphus_mauritiana": 0,       # Chinee Apple
    "lantana_camara": 1,           # Lantana
    "parkinsonia_aculeata": 2,     # Parkinsonia
    "parthenium_hysterophorus": 3, # Parthenium
    "vachellia_nilotica": 4,       # Prickly Acacia
    "cryptostegia_grandiflora": 5, # Rubber Vine
    "chromolaena_odorata": 6,      # Siam Weed
    "stachytarpheta_spp": 7,       # Snake Weed
    "negatives": 8                  # Background / Soil
}

s3_client = boto3.client('s3', region_name=AWS_REGION)

def export_postgis_to_sagemaker_manifest():
    print("🚀 Querying PostGIS database for imagery annotations...")

    # SQL JOIN across metadata, annotations, and taxonomy catalog
    query = """
        SELECT im.s3_key, tc.canonical_code
        FROM imagery_metadata im
        JOIN agricultural_annotations aa ON im.image_id = aa.image_id
        JOIN taxonomy_catalog tc ON aa.taxonomy_id = tc.taxonomy_id;
    """

    with get_db_cursor() as cursor:
        cursor.execute(query)
        records = cursor.fetchall()

    if not records:
        print("❌ No imagery records found in PostGIS. Run ingestion daemon first.")
        return

    print(f"📦 Retrieved {len(records)} records from PostGIS. Formatting SageMaker manifest...")

    # Ensure local destination folder exists
    os.makedirs(os.path.dirname(LOCAL_MANIFEST_PATH), exist_ok=True)

    manifest_rows = []
    for s3_key, canonical_code in records:
        # Construct full S3 URI required by SageMaker channels
        s3_uri = f"s3://{S3_BUCKET_NAME}/{s3_key}"
        
        # Look up numerical class index (default to 8 for unknown/background)
        class_id = TAXONOMY_CLASS_INDEX.get(canonical_code, 8)
        
        manifest_rows.append([s3_uri, class_id, canonical_code])

    # Write out local CSV manifest
    with open(LOCAL_MANIFEST_PATH, mode="w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        # Header row for verification
        writer.writerow(["s3_uri", "class_id", "canonical_code"])
        writer.writerows(manifest_rows)

    print(f"✅ Generated local manifest: '{LOCAL_MANIFEST_PATH}' ({len(manifest_rows)} rows)")

    # Upload manifest CSV to AWS S3 for SageMaker job consumption
    print(f"📡 Uploading manifest to S3: s3://{S3_BUCKET_NAME}/{S3_MANIFEST_KEY}...")
    s3_client.upload_file(LOCAL_MANIFEST_PATH, S3_BUCKET_NAME, S3_MANIFEST_KEY)
    
    print("✨ Manifest generation complete! Ready for AWS SageMaker ingestion.")

if __name__ == "__main__":
    export_postgis_to_sagemaker_manifest()