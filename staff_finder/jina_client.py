"""Jina Search API integration for retrieving search engine results."""

import os
from typing import List, Dict, Any, Optional
from urllib.parse import quote
import aiohttp


class JinaSearchClient:
    """Client for interacting with Jina Search API."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Jina Search client.
        
        Args:
            api_key: Jina API key. If not provided, reads from JINA_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("JINA_API_KEY")
        self.base_url = "https://s.jina.ai"
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    async def close(self):
        """Close the aiohttp session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
    
    async def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search for a query using Jina Search API.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return
            
        Returns:
            List of search results with URL, title, and description
        """
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        # URL-encode the query to handle spaces and special characters
        encoded_query = quote(query, safe='')
        url = f"{self.base_url}/{encoded_query}"
        
        session = await self._get_session()
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    # Parse the response - Jina returns markdown-formatted results
                    text = await response.text()
                    results = self._parse_jina_response(text, max_results)
                    return results
                else:
                    error_text = await response.text()
                    raise Exception(f"Jina API error {response.status}: {error_text}")
        except Exception as e:
            raise Exception(f"Failed to search with Jina API: {str(e)}") from e
    
    def _parse_jina_response(self, text: str, max_results: int) -> List[Dict[str, Any]]:
        """Parse Jina's markdown response into structured results.
        
        Args:
            text: Raw markdown text from Jina API
            max_results: Maximum number of results to return
            
        Returns:
            List of search result dictionaries
        """
        results = []
        lines = text.split("\n")
        
        current_result = {}
        for line in lines:
            line = line.strip()
            
            # Extract URLs from markdown links [text](url)
            if line.startswith("Title:"):
                if current_result and "url" in current_result:
                    results.append(current_result)
                    if len(results) >= max_results:
                        break
                current_result = {"title": line.replace("Title:", "").strip()}
            elif line.startswith("URL:"):
                url = line.replace("URL:", "").strip()
                current_result["url"] = url
            elif line.startswith("Description:"):
                current_result["description"] = line.replace("Description:", "").strip()
            elif line and current_result and "description" in current_result:
                # Continuation of description
                current_result["description"] += " " + line
        
        # Add last result
        if current_result and "url" in current_result and len(results) < max_results:
            results.append(current_result)
        
        return results
