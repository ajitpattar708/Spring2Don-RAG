"""
Stack Overflow Scraper
Scrapes Stack Overflow for migration questions and answers
"""

import requests
from typing import List, Dict, Optional
import time
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class StackOverflowScraper:
    """Scrapes Stack Overflow for migration patterns"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.base_url = "https://api.stackexchange.com/2.3"
        self.site = "stackoverflow.com"
    
    def search_questions(
        self,
        query: str,
        tags: List[str] = None,
        max_results: int = 1000,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None
    ) -> List[Dict]:
        """
        Search Stack Overflow questions
        
        Args:
            query: Search query
            tags: Filter by tags
            max_results: Maximum results
            from_date: Unix timestamp (start date)
            to_date: Unix timestamp (end date)
            
        Returns:
            List of questions
        """
        questions = []
        page = 1
        page_size = 100
        
        while len(questions) < max_results:
            try:
                url = f"{self.base_url}/search"
                params = {
                    "order": "desc",
                    "sort": "relevance",
                    "intitle": query,
                    "site": self.site,
                    "pagesize": min(page_size, 100),
                    "page": page
                }
                
                if tags:
                    params["tagged"] = ";".join(tags)
                
                if from_date:
                    params["fromdate"] = from_date
                
                if to_date:
                    params["todate"] = to_date
                
                if self.api_key:
                    params["key"] = self.api_key
                
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                
                data = response.json()
                items = data.get("items", [])
                
                if not items:
                    break
                
                questions.extend(items)
                logger.info(f"Found {len(questions)} questions (page {page})")
                
                # Check if we have more pages
                if not data.get("has_more", False):
                    break
                
                page += 1
                time.sleep(0.5)  # Rate limiting
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Error searching questions: {str(e)}")
                break
        
        return questions[:max_results]
    
    def get_question_answers(self, question_id: int) -> List[Dict]:
        """Get answers for a question"""
        try:
            url = f"{self.base_url}/questions/{question_id}/answers"
            params = {
                "order": "desc",
                "sort": "votes",
                "site": self.site,
                "filter": "withbody"
            }
            
            if self.api_key:
                params["key"] = self.api_key
            
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            return data.get("items", [])
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting answers: {str(e)}")
            return []
    
    def scrape_migration_questions(
        self,
        years_back: int = 10
    ) -> List[Dict]:
        """Scrape migration-related questions"""
        from datetime import datetime, timedelta
        
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=years_back * 365)
        
        from_timestamp = int(start_date.timestamp())
        to_timestamp = int(end_date.timestamp())
        
        queries = [
            "spring boot migrate helidon",
            "spring boot to helidon",
            "spring boot helidon migration",
            "spring boot microprofile",
            "spring boot jakarta",
            "spring boot jax-rs",
            "spring boot cdi",
            "@RestController migrate",
            "@Autowired migrate",
            "spring dependency injection helidon"
        ]
        
        all_questions = []
        
        for query in queries:
            logger.info(f"Searching for: {query}")
            questions = self.search_questions(
                query=query,
                tags=["java", "spring-boot"],
                max_results=100,
                from_date=from_timestamp,
                to_date=to_timestamp
            )
            
            # Get answers for each question
            for question in questions:
                question_id = question.get("question_id")
                if question_id:
                    answers = self.get_question_answers(question_id)
                    question["answers"] = answers
                    time.sleep(0.5)  # Rate limiting
            
            all_questions.extend(questions)
            time.sleep(1)
        
        logger.info(f"Found {len(all_questions)} migration-related questions")
        return all_questions
    
    def extract_code_blocks(self, text: str) -> List[str]:
        """Extract code blocks from text"""
        import re
        
        # Match code blocks (```code``` or <code>code</code>)
        patterns = [
            r'```(?:java|xml|yaml|properties)?\n(.*?)```',
            r'<code>(.*?)</code>',
            r'`([^`]+)`'
        ]
        
        code_blocks = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
            code_blocks.extend(matches)
        
        return code_blocks


