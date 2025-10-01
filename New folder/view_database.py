import chromadb
import json

def view_chromadb():
    """View all data stored in the ChromaDB database"""
    
    print("🔍 Connecting to ChromaDB...")
    chroma_client = chromadb.PersistentClient(path="./chroma_db")
    
    # Get all collections
    collections = chroma_client.list_collections()
    print(f"\n📋 Found {len(collections)} collections:")
    for collection in collections:
        print(f"  - {collection.name}")
    
    print("\n" + "="*60)
    
    # View user_info collection
    try:
        user_collection = chroma_client.get_collection("user_info")
        print("\n👤 USER_INFO COLLECTION:")
        print("-" * 30)
        
        # Get all user info
        user_data = user_collection.get()
        
        if user_data['ids']:
            print(f"📊 Total users: {len(user_data['ids'])}")
            for i, user_id in enumerate(user_data['ids']):
                document = user_data['documents'][i] if i < len(user_data['documents']) else "No document"
                metadata = user_data['metadatas'][i] if i < len(user_data['metadatas']) else {}
                
                print(f"\n🆔 User ID: {user_id}")
                print(f"📄 Info: {document}")
                print(f"📝 Metadata: {json.dumps(metadata, indent=2)}")
        else:
            print("❌ No user data found")
            
    except Exception as e:
        print(f"❌ Error accessing user_info collection: {e}")
    
    print("\n" + "="*60)
    
    # View memories collection
    try:
        memories_collection = chroma_client.get_collection("memories")
        print("\n🧠 MEMORIES COLLECTION:")
        print("-" * 30)
        
        # Get all memories
        memories_data = memories_collection.get()
        
        if memories_data['ids']:
            print(f"📊 Total memories: {len(memories_data['ids'])}")
            for i, memory_id in enumerate(memories_data['ids']):
                document = memories_data['documents'][i] if i < len(memories_data['documents']) else "No document"
                metadata = memories_data['metadatas'][i] if i < len(memories_data['metadatas']) else {}
                
                print(f"\n🆔 Memory ID: {memory_id}")
                print(f"📄 Content: {document}")
                print(f"📝 Metadata: {json.dumps(metadata, indent=2)}")
        else:
            print("❌ No memories found")
            
    except Exception as e:
        print(f"❌ Error accessing memories collection: {e}")
    
    print("\n" + "="*60)
    print("✅ Database inspection complete!")

def search_memories(query):
    """Search memories by query"""
    print(f"\n🔎 Searching memories for: '{query}'")
    
    chroma_client = chromadb.PersistentClient(path="./chroma_db")
    
    try:
        memories_collection = chroma_client.get_collection("memories")
        results = memories_collection.query(
            query_texts=[query],
            n_results=5
        )
        
        if results['documents'] and len(results['documents'][0]) > 0:
            print(f"📊 Found {len(results['documents'][0])} matches:")
            for i, doc in enumerate(results['documents'][0]):
                distance = results['distances'][0][i] if results['distances'] else 'N/A'
                metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                print(f"\n{i+1}. 📄 {doc}")
                print(f"   📏 Distance: {distance}")
                print(f"   📝 Metadata: {json.dumps(metadata, indent=6)}")
        else:
            print("❌ No matching memories found")
            
    except Exception as e:
        print(f"❌ Error searching memories: {e}")

if __name__ == "__main__":
    print("🗃️  ChromaDB Database Viewer")
    print("="*60)
    
    # View all data
    view_chromadb()
    
    # Interactive search
    print("\n🔍 INTERACTIVE SEARCH MODE")
    print("Type a query to search memories, or 'quit' to exit:")
    
    while True:
        try:
            query = input("\n🔎 Search query: ").strip()
            if query.lower() in ['quit', 'exit', 'q']:
                print("👋 Goodbye!")
                break
            if query:
                search_memories(query)
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")