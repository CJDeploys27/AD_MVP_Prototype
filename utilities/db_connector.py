import os
import psycopg2
from contextlib import contextmanager
from dotenv import load_dotenv

# Load local .env for local computer execution
load_dotenv()

def get_setting(key, default=""):
    """Fetches credentials from Streamlit Cloud Secrets first, then falls back to local .env"""
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key]).strip().strip('"').strip("'")
    except Exception:
        pass
    return (os.getenv(key) or default).strip().strip('"').strip("'")

DB_HOST = get_setting("DB_HOST")
DB_NAME = get_setting("DB_NAME", "geospatial_metadata")
DB_USER = get_setting("DB_USER", "cloud_admin")
DB_PASSWORD = get_setting("DB_PASSWORD")
DB_PORT = get_setting("DB_PORT", "5432")

def get_connection():
    """
    Establishes and returns a single connection to the PostgreSQL database.
    """
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT,
            sslmode="require", # Enforces SSL connection to AWS RDS
            connect_timeout=10 # Prevents the script from hanging indefinitely 
        )
        return conn
    except psycopg2.OperationalError as e:
        print(f"❌ Critical Error: Could not connect to database at host '{DB_HOST}'. {e}")
        raise

@contextmanager
def get_db_cursor(commit=True):
    """
    Context Manager for safe database transactions.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        yield cursor
        if commit:
            conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"⚠️ Transaction failed. Changes rolled back. Error: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    print("🔍 Testing connection to PostgreSQL/PostGIS database...")
    try:
        with get_db_cursor(commit=False) as test_cursor:
            test_cursor.execute("SELECT version();")
            pg_version = test_cursor.fetchone()[0]
            
            test_cursor.execute("SELECT PostGIS_Version();")
            postgis_version = test_cursor.fetchone()[0]
            
        print(f"✅ Connection successful!")
        print(f"🐘 PostgreSQL: {pg_version.split(',')[0]}")
        print(f"🗺️  PostGIS: {postgis_version}")
    except Exception as err:
        print(f"❌ Test Failed: {err}")
