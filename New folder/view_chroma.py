"""
Simple file-based ChromaDB viewer that shows the database structure
"""
import os
import sqlite3
import json

def view_chroma_files():
    db_path = "./chroma_db"
    
    if not os.path.exists(db_path):
        print("❌ ChromaDB database folder not found!")
        return
    
    print(f"📁 Database folder: {os.path.abspath(db_path)}")
    print("\n🗂️  Folder Structure:")
    
    # Show folder structure
    for root, dirs, files in os.walk(db_path):
        level = root.replace(db_path, '').count(os.sep)
        indent = ' ' * 2 * level
        print(f"{indent}📂 {os.path.basename(root)}/")
        subindent = ' ' * 2 * (level + 1)
        for file in files:
            size = os.path.getsize(os.path.join(root, file))
            print(f"{subindent}📄 {file} ({size} bytes)")
    
    # Try to read SQLite database
    sqlite_file = os.path.join(db_path, "chroma.sqlite3")
    if os.path.exists(sqlite_file):
        print(f"\n🗃️  SQLite Database: {sqlite_file}")
        try:
            conn = sqlite3.connect(sqlite_file)
            cursor = conn.cursor()
            
            # Get table names
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            
            print(f"📊 Found {len(tables)} tables:")
            for table in tables:
                table_name = table[0]
                print(f"\n📋 Table: {table_name}")
                
                # Get row count
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                print(f"   📊 Rows: {count}")
                
                if count > 0 and count < 10:  # Only show data if reasonable amount
                    cursor.execute(f"SELECT * FROM {table_name} LIMIT 5")
                    rows = cursor.fetchall()
                    
                    # Get column names
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    columns = [col[1] for col in cursor.fetchall()]
                    print(f"   📝 Columns: {columns}")
                    
                    for i, row in enumerate(rows):
                        print(f"   🔹 Row {i+1}: {dict(zip(columns, row))}")
            
            conn.close()
            print("\n✅ SQLite database inspection complete!")
            
        except Exception as e:
            print(f"❌ Error reading SQLite: {e}")
    
    print(f"\n📈 Total database size: {get_folder_size(db_path)} bytes")

def get_folder_size(folder_path):
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(folder_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)
    return total_size

if __name__ == "__main__":
    print("🗃️  ChromaDB File Structure Viewer")
    print("=" * 50)
    view_chroma_files()