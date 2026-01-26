"""Main processor for finding staff directory URLs."""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from .jina_client import JinaSearchClient
from .openai_selector import OpenAISelector


logger = logging.getLogger(__name__)


class StaffFinder:
    """Main class for finding staff directory URLs for schools."""
    
    def __init__(
        self,
        jina_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        openai_model: str = "gpt-4o-mini",
        max_concurrent: int = 5
    ):
        """Initialize the Staff Finder.
        
        Args:
            jina_api_key: Jina API key (optional, reads from env if not provided)
            openai_api_key: OpenAI API key (optional, reads from env if not provided)
            openai_model: OpenAI model to use (default: gpt-4o-mini)
            max_concurrent: Maximum number of concurrent requests (default: 5)
        """
        self.jina_client = JinaSearchClient(api_key=jina_api_key)
        self.openai_selector = OpenAISelector(api_key=openai_api_key, model=openai_model)
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def find_staff_url(self, school_record: Dict[str, Any]) -> Dict[str, Any]:
        """Find staff directory URL for a single school.
        
        Args:
            school_record: Dictionary with school information (name, city, state, etc.)
            
        Returns:
            Dictionary with school info and found staff URL (or None if not found)
        """
        async with self.semaphore:
            school_name = school_record.get("name", "")
            city = school_record.get("city", "")
            state = school_record.get("state", "")
            
            if not school_name:
                logger.warning("School record missing name, skipping")
                return {**school_record, "staff_url": None, "confidence": None, "reasoning": "Missing school name"}
            
            # Create search query
            query = f"{school_name} {city} {state} staff directory".strip()
            logger.info(f"Searching for: {query}")
            
            try:
                # Step 1: Get search results from Jina
                search_results = await self.jina_client.search(query, max_results=10)
                
                if not search_results:
                    logger.warning(f"No search results found for {school_name}")
                    return {
                        **school_record,
                        "staff_url": None,
                        "confidence": None,
                        "reasoning": "No search results found"
                    }
                
                logger.info(f"Found {len(search_results)} search results for {school_name}")
                
                # Step 2: Use OpenAI to select the best URL
                selection = await self.openai_selector.select_best_url(
                    school_name=school_name,
                    city=city,
                    state=state,
                    search_results=search_results
                )
                
                if selection:
                    logger.info(f"Selected URL for {school_name}: {selection['url']} (confidence: {selection['confidence']})")
                    return {
                        **school_record,
                        "staff_url": selection["url"],
                        "confidence": selection["confidence"],
                        "reasoning": selection["reasoning"]
                    }
                else:
                    logger.warning(f"No suitable staff directory URL found for {school_name}")
                    return {
                        **school_record,
                        "staff_url": None,
                        "confidence": None,
                        "reasoning": "No suitable staff directory URL found in results"
                    }
                    
            except Exception as e:
                logger.error(f"Error processing {school_name}: {str(e)}")
                return {
                    **school_record,
                    "staff_url": None,
                    "confidence": None,
                    "reasoning": f"Error: {str(e)}"
                }
    
    async def find_staff_urls_batch(self, school_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Find staff directory URLs for multiple schools concurrently.
        
        Args:
            school_records: List of school record dictionaries
            
        Returns:
            List of school records with staff URLs added
        """
        tasks = [self.find_staff_url(record) for record in school_records]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle any exceptions that occurred
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Task failed for record {i}: {str(result)}")
                processed_results.append({
                    **school_records[i],
                    "staff_url": None,
                    "confidence": None,
                    "reasoning": f"Task failed: {str(result)}"
                })
            else:
                processed_results.append(result)
        
        return processed_results
