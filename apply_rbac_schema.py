from utilities.db_connector import get_db_cursor

RBAC_SQL = """
-- 1. Safely Create Roles and Users (Idempotent: won't crash if they already exist)
DO $$
BEGIN
    -- Group Roles
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ds_reader') THEN
        CREATE ROLE ds_reader;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'daemon_writer') THEN
        CREATE ROLE daemon_writer;
    END IF;
    
    -- Login Users
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ds_team_01') THEN
        CREATE USER ds_team_01 WITH PASSWORD 'DataScience_Secure2026!';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'daemon_ingest_01') THEN
        CREATE USER daemon_ingest_01 WITH PASSWORD 'Daemon_Secure2026!';
    END IF;
END
$$;

-- 2. Grant Basic Schema Access
GRANT USAGE ON SCHEMA public TO ds_reader, daemon_writer;

-- ==========================================
-- 3. Configure Data Scientist (Read-Only)
-- ==========================================
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ds_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ds_reader;

-- ==========================================
-- 4. Configure Ingestion Daemon (Read/Write)
-- ==========================================
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO daemon_writer;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO daemon_writer;

ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO daemon_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO daemon_writer;

-- ==========================================
-- 5. Assign Roles to Users
-- ==========================================
GRANT ds_reader TO ds_team_01;
GRANT daemon_writer TO daemon_ingest_01;
"""

def apply_security_roles():
    print("🔐 Applying Role-Based Access Control to PostGIS...")
    try:
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(RBAC_SQL)
        print("✅ Database roles and permissions applied successfully!")
        print("   ├─ Created Read-Only Data Science identity (ds_team_01).")
        print("   └─ Created Read/Write Daemon identity (daemon_ingest_01).")
    except Exception as e:
        print(f"❌ Failed to apply RBAC: {e}")

if __name__ == "__main__":
    apply_security_roles()