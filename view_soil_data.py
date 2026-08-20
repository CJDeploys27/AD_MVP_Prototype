import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utilities.db_connector import get_db_cursor

def view_soils():
    query = """
    SELECT mukey, mapunit_name, organic_matter_pct, ph_water, texture_class 
    FROM farm_soil_properties;
    """
    with get_db_cursor(commit=False) as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()
        
        print("\n" + "="*80)
        print(f"{'MUKEY':<10} | {'MAP UNIT NAME':<35} | {'OM %':<6} | {'pH':<5} | {'TEXTURE'}")
        print("="*80)
        for r in rows:
            mukey, name, om, ph, texture = r
            print(f"{str(mukey):<10} | {str(name)[:35]:<35} | {str(om):<6} | {str(ph):<5} | {str(texture)}")
        print("="*80 + "\n")

if __name__ == "__main__":
    view_soils()