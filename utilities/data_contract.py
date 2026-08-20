import re
from typing import Literal, Optional
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator  # type: ignore

# 1. WHITELISTED GOVERNANCE LICENSES
ALLOWED_LICENSES = Literal[
    'CC BY 4.0', 
    'CC0 1.0', 
    'MIT', 
    'Apache 2.0', 
    'Open Access', 
    'Proprietary'
]

# 2. NORMALIZED BOUNDING BOX CONTRACT (0.0 to 1.0 image ratio bounds)
class NormalizedBoundingBoxContract(BaseModel):
    """
    Validates computer vision bounding box ratios (YOLO/Object Detection).
    Coordinates must be between 0.0 and 1.0, with max > min.
    """
    xmin: float = Field(..., ge=0.0, le=1.0)
    ymin: float = Field(..., ge=0.0, le=1.0)
    xmax: float = Field(..., ge=0.0, le=1.0)
    ymax: float = Field(..., ge=0.0, le=1.0)

    @model_validator(mode='after')
    def validate_box_dimensions(self):
        if self.xmax <= self.xmin:
            raise ValueError(f"xmax ({self.xmax}) must be strictly greater than xmin ({self.xmin})")
        if self.ymax <= self.ymin:
            raise ValueError(f"ymax ({self.ymax}) must be strictly greater than ymin ({self.ymin})")
        return self

# 3. BASELINE / THIRD-PARTY DATASET CONTRACT
class BaselineIngestionContract(BaseModel):
    """
    Enforces governance, taxonomy, and legal compliance for third-party baseline imagery.
    """
    dataset_name: str = Field(..., min_length=2, max_length=100)
    dataset_group: str = Field(..., min_length=2)
    license_type: ALLOWED_LICENSES
    attribution: str = Field(..., min_length=5)
    remote_url: HttpUrl
    s3_target_key: str = Field(..., pattern=r"^[a-zA-Z0-9_\-\/\.]+$")
    
    # Enforces snake_case taxonomy codes matching taxonomy_catalog (e.g., 'ziziphus_mauritiana')
    canonical_taxonomy_code: str = Field(
        ..., 
        pattern=r"^[a-z0-9_]+$", 
        description="Taxonomy tag must be lowercase snake_case without special characters"
    )
    feature_type: Literal['Crop', 'Weed', 'Disease', 'Pest', 'Soil']
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    polygon_wkt: str

    @field_validator('polygon_wkt')
    @classmethod
    def validate_wkt_format(cls, v: str) -> str:
        clean_v = v.strip().upper()
        if not (clean_v.startswith("POLYGON ((") or clean_v.startswith("POLYGON((")):
            raise ValueError("polygon_wkt must be a valid WKT string starting with 'POLYGON (('")
        return v

# 4. SENTINEL-2 SATELLITE ASSET CONTRACT
class SentinelIngestionContract(BaseModel):
    """
    Enforces governance standards for incoming satellite scenes.
    """
    scene_id: str = Field(..., min_length=10)
    band_key: Literal['B04', 'B06', 'B08']
    s3_target_key: str = Field(..., pattern=r"^sentinel\-2\/[a-zA-Z0-9_\-]+\/B0[468]\.tif$")
    source_url: HttpUrl
    wkt_polygon: str
    cloud_cover: float = Field(..., ge=0.0, le=100.0)

    @field_validator('wkt_polygon')
    @classmethod
    def validate_wkt_format(cls, v: str) -> str:
        clean_v = v.strip().upper()
        if not clean_v.startswith("POLYGON"):
            raise ValueError("wkt_polygon must be a valid WKT Polygon string")
        return v

# 5. BUILT-IN DIAGNOSTIC TEST
if __name__ == "__main__":
    print("🔍 Testing Pydantic Data Contract Validation Rules...\n")
    
    # Valid Payload Test
    valid_sample = {
        "dataset_name": "DeepWeeds",
        "dataset_group": "Group 1: RGB Vision",
        "license_type": "CC BY 4.0",
        "attribution": "Published by Visualising Agriculture Dataset Archive.",
        "remote_url": "https://images.unsplash.com/photo-1593113598332-cd288d649433",
        "s3_target_key": "third-party-baseline/group-1-rgb-vision/deepweeds/weed_sample_01.jpg",
        "canonical_taxonomy_code": "ziziphus_mauritiana",
        "feature_type": "Weed",
        "confidence_score": 0.98,
        "polygon_wkt": "POLYGON ((450 800, 600 800, 600 950, 450 950, 450 800))"
    }

    try:
        validated = BaselineIngestionContract(**valid_sample)
        print("✅ Valid Sample Passed Contract Check successfully!")
        print(f"   ├─ Validated License: {validated.license_type}")
        print(f"   └─ Validated Taxonomy Code: {validated.canonical_taxonomy_code}\n")
    except Exception as err:
        print(f"❌ Test Unexpectedly Failed: {err}")

    # Invalid Payload Test (Simulating non-compliant data)
    invalid_sample = valid_sample.copy()
    invalid_sample["license_type"] = "GPL-3.0-RESTRICTED" # Invalid License
    invalid_sample["canonical_taxonomy_code"] = "Chinee Apple!!!" # Invalid Formatting

    try:
        BaselineIngestionContract(**invalid_sample)
        print("❌ Governance Check Failed: Invalid sample was improperly accepted!")
    except Exception as err:
        print("✅ Governance Catch Working! Rejected non-compliant payload with details:")
        print(f"   └─ {err}")
