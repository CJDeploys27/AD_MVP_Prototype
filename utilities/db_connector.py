import os
import psycopg2
from contextlib import contextmanager
from dotenv import load_dotenv

# 1. LOAD ENVIRONMENT VARIABLES ONCE & SANITIZE WHITESPACE
load_dotenv()

DB_HOST = (os.getenv("DB_HOST") or "").strip()
DB_NAME = (os.getenv("DB_NAME", "geospatial_metadata") or "").strip()
DB_USER = (os.getenv("DB_USER") or "").strip()
DB_PASSWORD = (os.getenv("DB_PASSWORD") or "").strip()
DB_PORT = (os.getenv("DB_PORT", "5432") or "").strip()

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
        print(f"❌ Critical Error: Could not connect to the database. {e}")
        raise

@contextmanager
def get_db_cursor(commit=True):
    """
    A Python Context Manager for safe database transactions.
    It automatically handles creating cursors, committing data, 
    rolling back on errors, and closing connections so nothing leaks.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Yield gives the cursor to your main script to run SQL queries
        yield cursor
        
        # If the script finishes without crashing, save (commit) the changes
        if commit:
            conn.commit()
    except Exception as e:
        # If ANY error occurs in your main script, undo (rollback) the database changes
        conn.rollback()
        print(f"⚠️ Transaction failed. Changes rolled back. Error: {e}")
        raise
    finally:
        # Always close the doors when you leave, no matter what happened
        cursor.close()
        conn.close()

# 3. BUILT-IN DIAGNOSTIC TEST
if __name__ == "__main__":
    print("🔍 Testing connection to PostgreSQL/PostGIS database...")
    try:
        # We test the context manager by asking the database for its version
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
