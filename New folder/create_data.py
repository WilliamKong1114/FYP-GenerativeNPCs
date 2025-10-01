"""
Test script to create sample data in ChromaDB
"""
import chromadb
import uuid

def create_sample_data():
    print("🔧 Creating sample ChromaDB data...")
    
    # Use ChromaDB for persistent memory storage
    chroma_client = chromadb.PersistentClient(path="./chroma_db")
    user_collection = chroma_client.get_or_create_collection("user_info")
    memories_collection = chroma_client.get_or_create_collection("memories")
    
    print("📝 Adding sample user info...")
    # Add sample user info
    user_collection.upsert(
        ids=["user_1"],
        documents=["John is a software developer who loves Python and AI"],
        metadatas=[{"type": "user_info", "user_id": "user_1"}]
    )
    
    user_collection.upsert(
        ids=["user_2"], 
        documents=["Sarah is a data scientist working with machine learning models"],
        metadatas=[{"type": "user_info", "user_id": "user_2"}]
    )
    
    print("🧠 Adding sample memories...")
    # Add sample memories
    memories = [
        "User asked about Python programming basics",
        "User wanted to know about machine learning algorithms", 
        "User discussed their favorite foods: pizza and sushi",
        "User mentioned they work from home on Mondays",
        "User is interested in learning about LangGraph and LangChain"
    ]
    
    for i, memory in enumerate(memories):
        memory_id = str(uuid.uuid4())
        user_id = "user_1" if i < 3 else "user_2"
        
        memories_collection.add(
            ids=[memory_id],
            documents=[memory],
            metadatas=[{"type": "memory", "user_id": user_id}]
        )
    
    print("✅ Sample data created successfully!")
    print(f"👤 User info entries: {len(user_collection.get()['ids'])}")
    print(f"🧠 Memory entries: {len(memories_collection.get()['ids'])}")

#if __name__ == "__main__":
#    create_sample_data()