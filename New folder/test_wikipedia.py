import requests

def wikipedia_search(query: str) -> str:
    """Search Wikipedia for factual information."""
    try:
        # Add User-Agent header to avoid being blocked
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # First, search for page titles
        search_response = requests.get("https://en.wikipedia.org/w/api.php", 
            params={
                "action": "query",
                "format": "json",
                "list": "search", 
                "srsearch": query,
                "srlimit": 3
            }, 
            headers=headers,
            timeout=15
        )
        
        # Check if response is successful
        if search_response.status_code != 200:
            return f"Wikipedia search failed with status code: {search_response.status_code}"
        
        # Check if response contains valid JSON
        try:
            search_data = search_response.json()
        except ValueError:
            return "Wikipedia returned invalid response format."
        
        pages = search_data.get("query", {}).get("search", [])
        
        if not pages:
            return "No Wikipedia articles found for this query."
        
        # Get content for the first result
        page_title = pages[0]["title"]
        content_response = requests.get("https://en.wikipedia.org/w/api.php", 
            params={
                "action": "query",
                "format": "json",
                "prop": "extracts",
                "exintro": True,
                "explaintext": True,
                "titles": page_title
            }, 
            headers=headers,
            timeout=15
        )
        
        if content_response.status_code != 200:
            return f"Failed to fetch Wikipedia content with status code: {content_response.status_code}"
        
        try:
            content_data = content_response.json()
        except ValueError:
            return "Wikipedia content response is not valid JSON."
        
        pages_content = content_data.get("query", {}).get("pages", {})
        
        for page_id, page_info in pages_content.items():
            extract = page_info.get("extract", "")
            if extract:
                # Limit to first 800 characters for better readability
                summary = extract[:800] + "..." if len(extract) > 800 else extract
                return f"Wikipedia - {page_title}:\n\n{summary}"
        
        return "No content found in Wikipedia article."
        
    except requests.exceptions.Timeout:
        return "Wikipedia search timed out. Please try again."
    except requests.exceptions.ConnectionError:
        return "Could not connect to Wikipedia. Please check your internet connection."
    except requests.exceptions.RequestException as e:
        return f"Wikipedia search failed due to network error: {str(e)}"
    except Exception as e:
        return f"Wikipedia search error: {str(e)}"

# Test the Wikipedia search function
if __name__ == "__main__":
    print("=== Testing Wikipedia Search ===\n")
    
    test_queries = [
        "artificial intelligence",
        "Python programming language", 
        "machine learning",
        "Albert Einstein"
    ]
    
    for query in test_queries:
        print(f"🔍 Searching for: '{query}'")
        print("-" * 50)
        result = wikipedia_search(query)
        print(result)
        print("\n" + "="*50 + "\n")