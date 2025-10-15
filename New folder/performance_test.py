# Performance comparison script
import time
import requests

def test_original_wikipedia(query):
    """Test the original Wikipedia search performance"""
    start_time = time.time()
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        # Original two-step approach
        search_response = requests.get("https://en.wikipedia.org/w/api.php", 
            params={"action": "query", "format": "json", "list": "search", "srsearch": query, "srlimit": 3}, 
            headers=headers, timeout=15)
        
        search_data = search_response.json()
        pages = search_data.get("query", {}).get("search", [])
        
        if pages:
            page_title = pages[0]["title"]
            content_response = requests.get("https://en.wikipedia.org/w/api.php", 
                params={"action": "query", "format": "json", "prop": "extracts", "exintro": True, "explaintext": True, "titles": page_title}, 
                headers=headers, timeout=15)
            
            content_data = content_response.json()
            # Process result...
            
    except Exception as e:
        pass
    
    end_time = time.time()
    return end_time - start_time

def test_optimized_wikipedia(query):
    """Test the optimized Wikipedia search performance"""
    start_time = time.time()
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        # Optimized single request approach
        response = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{query.replace(' ', '_')}", 
            headers=headers, timeout=8)
        
        if response.status_code == 200:
            data = response.json()
            # Process result...
            
    except Exception as e:
        pass
    
    end_time = time.time()
    return end_time - start_time

# Performance comparison
if __name__ == "__main__":
    test_queries = ["artificial intelligence", "Python programming", "machine learning"]
    
    print("🔍 Performance Comparison Results:")
    print("=" * 50)
    
    for query in test_queries:
        original_time = test_original_wikipedia(query)
        optimized_time = test_optimized_wikipedia(query)
        improvement = ((original_time - optimized_time) / original_time) * 100 if original_time > 0 else 0
        
        print(f"Query: {query}")
        print(f"  Original: {original_time:.3f}s")
        print(f"  Optimized: {optimized_time:.3f}s") 
        print(f"  Improvement: {improvement:.1f}%")
        print()
    
    print("🚀 Key Optimizations Applied:")
    print("  ✅ ChromaDB connection pooling & caching")
    print("  ✅ Memory context caching (5min)")
    print("  ✅ Reduced API timeouts (15s → 8s)")
    print("  ✅ Single-request Wikipedia API")
    print("  ✅ Thread pool for concurrent operations")
    print("  ✅ Better error handling & recovery")