"""
GitHub Scraper
Scrapes Spring Boot and Helidon MP repositories for migration patterns
"""

import requests
import time
import base64
from typing import List, Dict, Optional
from pathlib import Path
import json
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class GitHubScraper:
    """Scrapes GitHub repositories for code examples"""
    
    def __init__(self, github_token: Optional[str] = None):
        self.github_token = github_token
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github.v3+json"
        }
        if github_token:
            self.headers["Authorization"] = f"token {github_token}"
    
    def search_repositories(
        self,
        query: str,
        language: str = "Java",
        sort: str = "stars",
        order: str = "desc",
        per_page: int = 100,
        max_results: int = 1000
    ) -> List[Dict]:
        """
        Search GitHub repositories
        
        Args:
            query: Search query (e.g., "spring-boot", "helidon")
            language: Programming language filter
            sort: Sort by (stars, forks, updated)
            order: Order (asc, desc)
            per_page: Results per page (max 100)
            max_results: Maximum total results
            
        Returns:
            List of repository information
        """
        repositories = []
        page = 1
        
        while len(repositories) < max_results:
            try:
                url = f"{self.base_url}/search/repositories"
                params = {
                    "q": f"{query} language:{language}",
                    "sort": sort,
                    "order": order,
                    "per_page": min(per_page, 100),
                    "page": page
                }
                
                response = requests.get(url, headers=self.headers, params=params, timeout=30)
                response.raise_for_status()
                
                data = response.json()
                items = data.get("items", [])
                
                if not items:
                    break
                
                repositories.extend(items)
                logger.info(f"Found {len(repositories)} repositories (page {page})")
                
                # Rate limiting
                if "X-RateLimit-Remaining" in response.headers:
                    remaining = int(response.headers["X-RateLimit-Remaining"])
                    if remaining < 10:
                        logger.warning("Rate limit approaching, waiting...")
                        time.sleep(60)
                
                page += 1
                time.sleep(1)  # Be respectful
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Error searching repositories: {str(e)}")
                break
        
        return repositories[:max_results]
    
    def get_repository_files(
        self,
        owner: str,
        repo: str,
        path: str = "",
        file_extensions: List[str] = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get files from a repository
        
        Args:
            owner: Repository owner
            repo: Repository name
            path: Path within repository
            file_extensions: Filter by file extensions (e.g., ['.java', '.xml'])
            limit: Maximum number of files to return (to avoid huge trees)
            
        Returns:
            List of file information
        """
        if file_extensions is None:
            file_extensions = ['.java', '.xml', '.yml', '.properties']
        
        files = []
        
        try:
            url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path}"
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            items = response.json()
            
            # If not a list (e.g. single file), handle it
            if not isinstance(items, list):
                items = [items]
            
            # Shuffle items to get random variety if we limit? 
            # Ideally we'd just take the first N, but let's just proceed linearly.
            
            for item in items:
                if len(files) >= limit:
                    break
                    
                if item["type"] == "file":
                    if any(item["name"].endswith(ext) for ext in file_extensions):
                        files.append(item)
                elif item["type"] == "dir":
                    # Recursively get files from subdirectories
                    # Reduce limit by what we already have
                    remaining_limit = limit - len(files)
                    if remaining_limit > 0:
                        sub_files = self.get_repository_files(
                            owner, repo, item["path"], file_extensions, limit=remaining_limit
                        )
                        files.extend(sub_files)
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting files from {owner}/{repo}: {str(e)}")
        
        return files
    
    def get_file_content(self, owner: str, repo: str, path: str) -> Optional[str]:
        """Get content of a file from repository"""
        try:
            url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path}"
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            if data.get("encoding") == "base64":
                content = base64.b64decode(data["content"]).decode("utf-8")
                return content
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting file content: {str(e)}")
        
        return None
    
    def scrape_spring_boot_repos(self, max_repos: int = 500) -> List[Dict]:
        """Scrape Spring Boot repositories"""
        logger.info("Searching for Spring Boot repositories...")
        
        queries = [
            "spring-boot",
            "spring boot",
            "springboot",
            "spring framework"
        ]
        
        all_repos = []
        for query in queries:
            repos = self.search_repositories(
                query=query,
                language="Java",
                max_results=max_repos // len(queries)
            )
            all_repos.extend(repos)
        
        # Remove duplicates
        seen = set()
        unique_repos = []
        for repo in all_repos:
            full_name = repo["full_name"]
            if full_name not in seen:
                seen.add(full_name)
                unique_repos.append(repo)
        
        logger.info(f"Found {len(unique_repos)} unique Spring Boot repositories")
        return unique_repos
    
    def scrape_helidon_repos(self, max_repos: int = 200) -> List[Dict]:
        """Scrape Helidon MP repositories"""
        logger.info("Searching for Helidon MP repositories...")
        
        queries = [
            "helidon",
            "helidon-microprofile",
            "helidon mp"
        ]
        
        all_repos = []
        for query in queries:
            repos = self.search_repositories(
                query=query,
                language="Java",
                max_results=max_repos // len(queries)
            )
            all_repos.extend(repos)
        
        # Remove duplicates
        seen = set()
        unique_repos = []
        for repo in all_repos:
            full_name = repo["full_name"]
            if full_name not in seen:
                seen.add(full_name)
                unique_repos.append(repo)
        
        logger.info(f"Found {len(unique_repos)} unique Helidon repositories")
        return unique_repos
    
    def extract_code_patterns(self, content: str, file_type: str) -> List[Dict]:
        """Extract code patterns from file content"""
        patterns = []
        
        if file_type == '.java':
            # Extract class definitions, annotations, etc.
            import re
            
            # Find classes with Spring annotations
            class_pattern = r'@(\w+)\s*\n.*?class\s+(\w+)'
            matches = re.finditer(class_pattern, content, re.MULTILINE | re.DOTALL)
            
            for match in matches:
                annotation = match.group(1)
                class_name = match.group(2)
                
                # Extract class code
                class_start = match.start()
                # Find class end (simplified)
                brace_count = 0
                class_end = class_start
                for i, char in enumerate(content[class_start:], class_start):
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            class_end = i + 1
                            break
                
                class_code = content[class_start:class_end]
                
                patterns.append({
                    'type': 'class',
                    'annotation': annotation,
                    'class_name': class_name,
                    'code': class_code
                })
        
        return patterns

