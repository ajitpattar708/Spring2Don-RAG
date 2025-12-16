#!/usr/bin/env python3
"""
Dataset Scraper
Scrapes web sources to build comprehensive migration dataset
"""

import sys
import os
import argparse
import time
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.scraper.github_scraper import GitHubScraper
from src.scraper.stackoverflow_scraper import StackOverflowScraper
from src.scraper.documentation_scraper import DocumentationScraper
from src.scraper.pattern_extractor import PatternExtractor
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def load_existing_patterns(file_path: Path) -> List[Dict]:
    """Load existing patterns from file"""
    if file_path.exists():
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Could not load existing patterns from {file_path}, starting fresh.")
            return []
    return []


def save_patterns(patterns: List[Dict], file_path: Path):
    """Save patterns to file"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(patterns, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved {len(patterns)} patterns to {file_path}")


def scrape_github_data(scraper: GitHubScraper, extractor: PatternExtractor, target_count: int, collected_count: int) -> List[Dict]:
    """Scrape GitHub repositories (One batch/repo at a time)"""
    patterns = []
    
    # Scrape Spring Boot repos
    if collected_count < target_count:
        # We don't want to log this every single time if we call it in a tight loop
        # logger.info("\n1. Scraping Spring Boot repositories...")
        
        # Paginate through results
        # To avoid always starting from "spring-boot" page 1, we rely on random selection or deep pagination.
        # But for this simple script, let's pick a random topic or rely on the scraper's cache/state if it had one.
        # IMPROVEMENT: Use a static/global index or randomized topics to ensure variety.
        topics = ["spring-boot", "spring-framework", "spring-cloud", "microservices", "java-migration", "jakarta-ee"]
        
        # Simple hack: rotate topics based on collected count to vary search
        current_topic_idx = (collected_count // 50) % len(topics)
        topic = topics[current_topic_idx]
            
        logger.info(f"Searching for topic: {topic} (Offset: {collected_count})")
        # Increase page based on count to go deeper
        page = (collected_count // 100) + 1
        
        # We use a custom search that allows page param
        # Note: The scraper.search_repositories in this codebase doesn't expose 'page' arg in the public method signature shown in previous turns?
        # Check source: yes, it does: def search_repositories(..., page=1) inside the while loop but not exposed in arguments well?
        # Actually the GitHubScraper.search_repositories implementation loops internally.
        # We should probably just ask for a small number of results.
        
        repos = scraper.search_repositories(query=topic, language="Java", max_results=10)
        
        for repo in repos:
            if collected_count >= target_count:
                break
                
            owner = repo["owner"]["login"]
            repo_name = repo["name"]
            
            logger.info(f"  Processing {owner}/{repo_name}...")
            
            try:
                # Limit = 5 to be fast
                files = scraper.get_repository_files(owner, repo_name, file_extensions=['.java'], limit=5)
                
                repo_patterns = []
                for file_info in files:
                    content = scraper.get_file_content(owner, repo_name, file_info["path"])
                    if content:
                        extracted = extractor.extract_spring_patterns(content)
                        if extracted:
                            repo_patterns.extend(extracted)
                            logger.debug(f"    Extracted {len(extracted)} patterns")
                
                if repo_patterns:
                    patterns.extend(repo_patterns)
                    # RETURN IMMEDIATELY after one good repo to allow saving
                    return patterns
                            
                time.sleep(1) # Be nice to API
                
            except Exception as e:
                logger.error(f"    Error processing repo {repo_name}: {e}")
    
    return patterns


def scrape_stackoverflow_data(scraper: StackOverflowScraper, extractor: PatternExtractor, target_count: int, collected_count: int) -> List[Dict]:
    """Scrape Stack Overflow"""
    patterns = []
    
    if collected_count < target_count:
        logger.info("\n2. Scraping Stack Overflow...")
        
        # We need pairs, so we look for migration questions primarily
        questions = scraper.scrape_migration_questions(years_back=10)
        
        for question in questions:
            if collected_count >= target_count:
                break
                
            q_patterns = []
            
            # Body patterns
            body_codes = scraper.extract_code_blocks(question.get("body", ""))
            for code in body_codes:
                q_patterns.extend(extractor.extract_spring_patterns(code))
            
            # Answer patterns
            answers = question.get("answers", [])
            for answer in answers:
                ans_codes = scraper.extract_code_blocks(answer.get("body", ""))
                for code in ans_codes:
                    # Look for Helidon patterns in answers
                    hel_pats = extractor.extract_helidon_patterns(code)
                    if hel_pats and q_patterns:
                        # If we have spring in question and helidon in answer, that's a good pair candidate
                        # For raw collection, we just save them
                        patterns.extend(hel_pats)
            
            patterns.extend(q_patterns)
            collected_count += len(q_patterns) + len(patterns) # accurate increment
            
    return patterns


def main():
    parser = argparse.ArgumentParser(description="Scrape migration dataset")
    parser.add_argument("--count", type=int, default=1000, help="Target number of patterns to scrape")
    parser.add_argument("--output", type=str, default="migration_dataset_scraped.json", help="Output JSON file")
    parser.add_argument("--resume", action="store_true", help="Resume from existing output file")
    
    args = parser.parse_args()
    
    logger.info("="*60)
    logger.info(f"Dataset Scraper - Target: {args.count} patterns")
    logger.info("="*60)
    
    # Get API keys
    github_token = os.getenv('GITHUB_TOKEN')
    stackoverflow_key = os.getenv('STACKOVERFLOW_KEY')
    
    if not github_token:
        logger.warning("No GITHUB_TOKEN element in environment. API limits will be strict (60/hr).")
    if not stackoverflow_key:
        logger.warning("No STACKOVERFLOW_KEY in environment. API limits will be stricter.")
        
    scraper_gh = GitHubScraper(github_token=github_token)
    scraper_so = StackOverflowScraper(api_key=stackoverflow_key)
    scraper_doc = DocumentationScraper()
    extractor = PatternExtractor()
    
    output_file = project_root / args.output
    all_patterns = []
    
    if args.resume and output_file.exists():
        all_patterns = load_existing_patterns(output_file)
        logger.info(f"Resumed with {len(all_patterns)} existing patterns.")
    
    collected_count = len(all_patterns)
    
    try:
        while collected_count < args.count:
            # Cycle through sources
            
            # 1. GitHub
            new_gh = scrape_github_data(scraper_gh, extractor, args.count, collected_count)
            all_patterns.extend(new_gh)
            collected_count = len(all_patterns)
            save_patterns(all_patterns, output_file)
            
            if collected_count >= args.count:
                break
                
            # 2. Stack Overflow
            new_so = scrape_stackoverflow_data(scraper_so, extractor, args.count, collected_count)
            all_patterns.extend(new_so)
            collected_count = len(all_patterns)
            save_patterns(all_patterns, output_file)
            
            if collected_count >= args.count:
                break
            
            # 3. Documentation (usually small fixed set, but good to have)
            # Only do this once
            if not any(p.get('source') == 'documentation' for p in all_patterns):
                logger.info("\n3. Scraping Documentation...")
                doc_patterns = scraper_doc.scrape_spring_boot_docs() + scraper_doc.scrape_helidon_docs()
                all_patterns.extend(doc_patterns)
                collected_count = len(all_patterns)
                save_patterns(all_patterns, output_file)
            
            # If we went through all sources and didn't hit target, we might need to broaden search or wait
            logger.info("Cycle complete. Waiting before next cycle to respect rates...")
            time.sleep(10) 
            
            # Break if we aren't getting new data to avoid infinite loop in this simple script
            if not new_gh and not new_so:
                logger.info("No new patterns found in this cycle. Stopping.")
                break
                
    except KeyboardInterrupt:
        logger.info("\nScraping interrupted by user. Saving progress...")
        save_patterns(all_patterns, output_file)
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        save_patterns(all_patterns, output_file)
        sys.exit(1)
        
    logger.info("="*60)
    logger.info("Scraping Completed")
    logger.info(f"Total Patterns: {len(all_patterns)}")
    logger.info(f"Saved to: {output_file}")
    logger.info("="*60)

if __name__ == '__main__':
    main()
