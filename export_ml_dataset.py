import os
import sys
import random
import boto3
from pathlib import Path
from dotenv import load_dotenv

# --- PATH SETUP FOR DATABASE UTILITIES ---
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utilities.db_connector import get_db_cursor
# -----------------------------------------

# 1. ENVIRONMENT & AWS CONFIGURATION
load_dotenv(override=True)

AWS_REGION = os.getenv("AWS_REGION", "us-east-2").strip()
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "ad4-raw-ingestion-2026-454014151118-us-east-2-an").strip().strip('\'"')
OUTPUT_DIR = Path("dataset_yolo")

s3_client = boto3.client('s3', region_name=AWS_REGION)

# 2. DEFINE TARGET TAXONOMIES AND TRAIN/VAL RATIO
# Add any canonical codes defined in your PostGIS taxonomy_catalog
TARGET_TAXONOMIES = ["zea_mays", "glycine_max", "ziziphus_mauritiana", "parthenium_hysterophorus"]
TRAIN_SPLIT_RATIO = 0.80  # 80% Train, 20% Validation
SEED = 42                 # For reproducible random splits


def create_yolo_directories():
    """Generates the required YOLO folder structure."""
    for split in ['train', 'val']:
        (OUTPUT_DIR / 'images' / split).mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / 'labels' / split).mkdir(parents=True, exist_ok=True)


def calculate_yolo_bbox(xmin: float, ymin: float, xmax: float, ymax: float):
    """
    Converts normalized min/max coordinates to YOLO format:
    x_center, y_center, width, height (all normalized 0.0 - 1.0).
    """
    x_center = (xmin + xmax) / 2.0
    y_center = (ymin + ymax) / 2.0
    width = xmax - xmin
    height = ymax - ymin
    return x_center, y_center, width, height


def export_yolo_dataset():
    print("🚀 Initializing PostGIS ML Dataset Exporter for YOLO...")
    random.seed(SEED)
    create_yolo_directories()

    # Map canonical codes to integer class IDs (e.g., zea_mays -> 0, glycine_max -> 1)
    class_map = {code: idx for idx, code in enumerate(TARGET_TAXONOMIES)}

    # SQL query to pull matching imagery and normalized annotations
    query = """
        SELECT 
            im.image_id,
            im.s3_key,
            tc.canonical_code,
            tc.display_name,
            aa.normalized_xmin,
            aa.normalized_ymin,
            aa.normalized_xmax,
            aa.normalized_ymax
        FROM agricultural_annotations aa
        JOIN imagery_metadata im ON aa.image_id = im.image_id
        JOIN taxonomy_catalog tc ON aa.taxonomy_id = tc.taxonomy_id
        WHERE tc.canonical_code = ANY(%s);
    """

    images_map = {}

    # Query PostGIS database
    with get_db_cursor() as cursor:
        cursor.execute(query, (TARGET_TAXONOMIES,))
        rows = cursor.fetchall()

    if not rows:
        print("⚠️ No matching annotated records found for the requested taxonomies.")
        return

    print(f"📊 Query retrieved {len(rows)} matching annotations.")

    # Group annotations by image_id to prevent data leakage across splits
    for row in rows:
        img_id, s3_key, canonical_code, display_name, xmin, ymin, xmax, ymax = row
        
        # Fallback bounding box values if normalized coordinates are unset
        xmin = float(xmin) if xmin is not None else 0.1000
        ymin = float(ymin) if ymin is not None else 0.1000
        xmax = float(xmax) if xmax is not None else 0.9000
        ymax = float(ymax) if ymax is not None else 0.9000

        if img_id not in images_map:
            images_map[img_id] = {
                "s3_key": s3_key,
                "annotations": []
            }

        class_idx = class_map[canonical_code]
        x_center, y_center, width, height = calculate_yolo_bbox(xmin, ymin, xmax, ymax)
        
        images_map[img_id]["annotations"].append(
            f"{class_idx} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"
        )

    # Perform Train/Val Split at the Image level
    image_ids = list(images_map.keys())
    random.shuffle(image_ids)
    split_index = int(len(image_ids) * TRAIN_SPLIT_RATIO)
    
    train_ids = set(image_ids[:split_index])
    val_ids = set(image_ids[split_index:])

    print(f"📦 Total Images: {len(image_ids)} | Train Split: {len(train_ids)} | Val Split: {len(val_ids)}")

    # Download images from S3 and write label .txt files
    for img_id, data in images_map.items():
        split = "train" if img_id in train_ids else "val"
        s3_key = data["s3_key"]
        
        filename = Path(s3_key).name
        stem = Path(s3_key).stem
        
        target_img_path = OUTPUT_DIR / "images" / split / filename
        target_label_path = OUTPUT_DIR / "labels" / split / f"{stem}.txt"

        # 1. Download Image from S3
        print(f"  └─ 📡 Downloading {filename} to images/{split}/...")
        s3_client.download_file(S3_BUCKET_NAME, s3_key, str(target_img_path))

        # 2. Write YOLO Bounding Box Text File
        with open(target_label_path, "w") as label_file:
            label_file.write("\n".join(data["annotations"]) + "\n")

    # Write YOLO dataset.yaml Configuration File
    yaml_path = OUTPUT_DIR / "dataset.yaml"
    with open(yaml_path, "w") as f:
        f.write(f"path: {OUTPUT_DIR.resolve()}\n")
        f.write("train: images/train\n")
        f.write("val: images/val\n\n")
        f.write("names:\n")
        for idx, code in enumerate(TARGET_TAXONOMIES):
            f.write(f"  {idx}: {code}\n")

    print("\n✅ YOLO Dataset Export Complete!")
    print(f"  ├─ Dataset Path: {OUTPUT_DIR.resolve()}")
    print(f"  └─ Configuration File: {yaml_path}")


if __name__ == "__main__":
    export_yolo_dataset()