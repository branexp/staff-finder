"""OpenAI API integration for intelligent staff directory URL selection."""

import os
import json
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI


class OpenAISelector:
    """Client for using OpenAI to select the best staff directory URL."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        """Initialize the OpenAI selector.
        
        Args:
            api_key: OpenAI API key. If not provided, reads from OPENAI_API_KEY env var.
            model: OpenAI model to use for reasoning (default: gpt-4o-mini)
        """
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY environment variable.")
        
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
    
    async def select_best_url(
        self, 
        school_name: str,
        city: str,
        state: str,
        search_results: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Select the best staff directory URL from search results.
        
        Args:
            school_name: Name of the school
            city: City where the school is located
            state: State where the school is located
            search_results: List of search results from Jina API
            
        Returns:
            Dictionary with selected URL and reasoning, or None if no suitable URL found
        """
        if not search_results:
            return None
        
        # Format search results for the prompt
        results_text = ""
        for i, result in enumerate(search_results, 1):
            results_text += f"\n{i}. URL: {result.get('url', 'N/A')}\n"
            results_text += f"   Title: {result.get('title', 'N/A')}\n"
            results_text += f"   Description: {result.get('description', 'N/A')}\n"
        
        prompt = f"""You are an expert at identifying staff directory pages for K-12 schools.

School Information:
- Name: {school_name}
- City: {city}
- State: {state}

Search Results:
{results_text}

Task: Select the BEST URL that is most likely to be the staff directory page for this school.

A good staff directory URL typically:
- Contains words like "staff", "faculty", "directory", "employees", "personnel", "team", "our-staff"
- Is from the school's official website (usually .edu, .org, or k12.*.us domain)
- Lists multiple staff members with their contact information
- Is not a job posting, calendar, or news page

Respond with a JSON object in this exact format:
{{
    "selected_index": <number from 1 to {len(search_results)} or 0 if none are suitable>,
    "selected_url": "<the full URL or null if none are suitable>",
    "confidence": "<high/medium/low>",
    "reasoning": "<brief explanation of why this URL was selected or why none were suitable>"
}}

Important: Only return the JSON object, nothing else."""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert at identifying staff directory pages for K-12 schools. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=500
            )
            
            content = response.choices[0].message.content.strip()
            
            # Parse JSON response
            # Remove markdown code blocks if present
            if content.startswith("```"):
                parts = content.split("```")
                if len(parts) >= 2:
                    content = parts[1]
                    if content.startswith("json"):
                        content = content[4:]
                    content = content.strip()
            
            result = json.loads(content)
            
            # Validate response
            if result.get("selected_index", 0) > 0 and result.get("selected_url"):
                return {
                    "url": result["selected_url"],
                    "confidence": result.get("confidence", "unknown"),
                    "reasoning": result.get("reasoning", ""),
                    "selected_index": result.get("selected_index", 0)
                }
            else:
                return None
                
        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse OpenAI response as JSON: {str(e)}\nResponse: {content}")
        except Exception as e:
            raise Exception(f"OpenAI API error: {str(e)}")
