"""
Simple ChromaDB viewer that handles the configuration correctly
"""
import chromadb
import json
import os

def view_database():
    # Check if database directory exists
    db_path = "./chroma_db"
    if not os.path.exists(db_path):
        print("❌ ChromaDB database not found!")
        print(f"📁 Looking for: {os.path.abspath(db_path)}")
        #print("💡 Run your chatbot script first to create the database.")
        return
    
    print(f"📁 Database location: {os.path.abspath(db_path)}")
    print("🔍 Connecting to ChromaDB...")
    
    try:
        # Use the same configuration as your main script
        import chromadb.config
        settings = chromadb.config.Settings(
            chroma_api_impl="chromadb.api.segment.SegmentAPI",
            chroma_sysdb_impl="chromadb.db.impl.sqlite.SqliteDB",
            chroma_producer_impl="chromadb.db.impl.sqlite.SqliteDB",
            chroma_consumer_impl="chromadb.db.impl.sqlite.SqliteDB",
            chroma_segment_manager_impl="chromadb.segment.impl.manager.local.LocalSegmentManager",
            allow_reset=True,
            anonymized_telemetry=False
        )
        
        chroma_client = chromadb.PersistentClient(path=db_path, settings=settings)
        
        # List collections
        collections = chroma_client.list_collections()
        print(f"\n📋 Collections found: {len(collections)}")
        
        for collection in collections:
            print(f"\n📦 Collection: {collection.name}")
            print("-" * 40)
            
            # Get all data from collection
            data = collection.get()
            
            if data['ids']:
                print(f"📊 Total items: {len(data['ids'])}")
                
                for i, item_id in enumerate(data['ids']):
                    print(f"\n🆔 ID: {item_id}")
                    
                    if i < len(data['documents']) and data['documents'][i]:
                        print(f"📄 Content: {data['documents'][i]}")
                    
                    if i < len(data['metadatas']) and data['metadatas'][i]:
                        print(f"📝 Metadata: {json.dumps(data['metadatas'][i], indent=2)}")
                    
                    print("-" * 20)
            else:
                print("❌ No data in this collection")
        
        print("\n✅ Database inspection complete!")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        print("💡 Try running your chatbot script first to create the database.")

if __name__ == "__main__":
    print("🗃️  ChromaDB Database Viewer (Simple)")
    print("=" * 50)
    view_database()