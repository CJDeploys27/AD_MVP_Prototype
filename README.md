# Geospatial AI Data Moat & Ingestion Engine

A production-ready, compliance-first geospatial data pipeline designed for agricultural machine learning applications. Built on **AWS RDS (PostgreSQL + PostGIS)** and **AWS S3**, this platform enforces strict data governance, micro/macro provenance tracking, spatial topology validity, and role-based access control (RBAC).

---

## 🏛️ System Architecture Overview

```text
AWS Database (Project Root)
├── .env                              # Managed AWS & Database Credentials
├── README.md                         # Architecture & Developer Documentation
├── apply_governance_schema.py        # Database Schema & Constraint Migration Script
├── apply_rbac.py                     # PostgreSQL Role-Based Access Control Migration
├── ingestion/                        # Automated Data Stream Daemons
│   ├── deepweeds_daemon.py           # Baseline Computer Vision Ingestion + S3 Tagging
│   └── sentinel2_ndre_ingest.py      # Multispectral Satellite STAC Stream + S3 Tagging
└── utilities/                        # Core Shared Framework Modules
    ├── db_connector.py               # Self-Healing PostgreSQL Context Manager
    └── data_contract.py              # Pydantic (v2) In-Memory Data Governance Contracts
    
## Core Governance & Security Features
1. Database Schema Standards (apply_governance_schema.py)
Taxonomy Standardization (taxonomy_catalog): Replaces unstandardized labels with centralized, lowercase snake_case taxonomy codes (e.g., ziziphus_mauritiana). Tags cross-reference international FAO AGROVOC identifiers.
Dual Bounding Box Support: Standardizes spatial geometries using PostGIS native POLYGON objects (ST_GeomFromText) alongside normalized ratio coordinates (0.0–1.0) for AI frameworks (YOLO, PyTorch).
Topological Accuracy: Enforces ST_IsValid() PostGIS check constraints on spatial extent geometries to prevent corrupt or self-intersecting polygons from entering the database.
Lineage & Metadata Provenance: Tracks macro legal attributes (license_type, commercial_use_allowed, terms_of_service_url) and micro asset lineage (source_url, ingested_by_daemon, raw_metadata_json stored as JSONB).
2. Cloud-Level S3 Governance
AWS S3 Object Tagging: Every uploaded binary asset is tagged at the AWS cloud layer using boto3 URL-encoded parameters (License, Taxonomy, FeatureType, CommercialUseAllowed).
Tagging Utility: Enables AWS IAM bucket policies to physically restrict asset access based on governance tags independent of the database layer.
3. Role-Based Access Control / RBAC (apply_rbac.py)
ds_reader (ds_team_01): Read-only role designed for Data Science teams training AI models (SELECT access only).
daemon_writer (daemon_ingest_01): Restricted ingestion role for automated daemons (SELECT, INSERT, UPDATE). Physically blocked from executing DROP TABLE or DELETE operations.
Master Admin: Reserved for administrative schema migrations and infrastructure updates.
4. Python Data Contracts (utilities/data_contract.py)
Built with Pydantic (v2) to validate incoming payloads in-memory prior to any network transactions.
Rejects non-whitelisted licenses, malformed taxonomy codes, invalid HTTP URLs, and coordinate bounds outside of strict geometric ranges before touching AWS S3 or PostGIS.
🚀 Ingestion Daemons
1. Third-Party Baseline Ingestion (ingestion/deepweeds_daemon.py)
Streams RGB imagery into memory, generates SHA-256 cryptographic fingerprints for deduplication, uploads unique files to S3 with governance tags, and links annotations to the taxonomy_catalog.
2. Live Satellite STAC Stream (ingestion/sentinel2_ndre_ingest.py)
Interfaces with the Element 84 STAC API to search Sentinel-2 L2A collections (<15% cloud cover).
Direct-streams required spectral bands (B04/Red, B06/Red Edge, B08/NIR) straight from ESA servers into S3 without local disk caching, saving up to 80% bandwidth.