"""
Documentation Scraper
Scrapes official documentation for migration patterns
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlparse
import time
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class DocumentationScraper:
    """Scrapes documentation websites"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
    
    def scrape_spring_boot_docs(self) -> List[Dict]:
        """Scrape Spring Boot documentation"""
        logger.info("Scraping Spring Boot documentation...")
        
        base_urls = [
            "https://docs.spring.io/spring-boot/docs/current/reference/html/",
            "https://spring.io/guides",
            "https://spring.io/blog"
        ]
        
        patterns = []
        
        for base_url in base_urls:
            try:
                response = self.session.get(base_url, timeout=30)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Extract code examples
                code_blocks = soup.find_all(['code', 'pre'])
                for code_block in code_blocks:
                    code_text = code_block.get_text()
                    if 'spring' in code_text.lower() and '@' in code_text:
                        patterns.append({
                            'source': base_url,
                            'type': 'documentation',
                            'code': code_text,
                            'url': base_url
                        })
                
                time.sleep(1)  # Be respectful
                
            except Exception as e:
                logger.error(f"Error scraping {base_url}: {str(e)}")
        
        logger.info(f"Found {len(patterns)} patterns from Spring Boot docs")
        return patterns
    
    def scrape_helidon_docs(self) -> List[Dict]:
        """Scrape Helidon MP documentation"""
        logger.info("Scraping Helidon MP documentation...")
        
        base_urls = [
            "https://helidon.io/docs/v4/",
            "https://helidon.io/docs/v4/#/guides",
            "https://helidon.io/native-image/mp/guides"
        ]
        
        patterns = []
        
        for base_url in base_urls:
            try:
                response = self.session.get(base_url, timeout=30)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Extract code examples
                code_blocks = soup.find_all(['code', 'pre'])
                for code_block in code_blocks:
                    code_text = code_block.get_text()
                    if ('helidon' in code_text.lower() or 'jakarta' in code_text.lower()) and '@' in code_text:
                        patterns.append({
                            'source': base_url,
                            'type': 'documentation',
                            'code': code_text,
                            'url': base_url
                        })
                
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error scraping {base_url}: {str(e)}")
        
        logger.info(f"Found {len(patterns)} patterns from Helidon docs")
        return patterns
    
    def scrape_blog_posts(self, keywords: List[str], max_posts: int = 100) -> List[Dict]:
        """Scrape blog posts about migration"""
        logger.info("Scraping blog posts...")
        
        # Common blog platforms
        search_urls = [
            f"https://www.google.com/search?q={'+'.join(keywords)}",
            f"https://medium.com/search?q={'+'.join(keywords)}",
        ]
        
        patterns = []
        
        # Note: This is a simplified version
        # In production, you'd use proper search APIs or web scraping tools
        
        logger.info(f"Found {len(patterns)} patterns from blog posts")
        return patterns


