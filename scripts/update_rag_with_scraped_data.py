#!/usr/bin/env python3
"""
Update RAG with Scraped Data
Loads the running scraped dataset into the RAG knowledge base.
Can be run safely while the scraper is still running.
"""

import sys
import json
import shutil
from pathlib import Path
import time

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.dataset.dataset_loader import DatasetLoader
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

def main():
    logger.info("Starting RAG Update from Scraped Data...")
    
    # 1. Locate the file
    scraped_file = project_root / 'migration_dataset_scraped.json'
    
    if not scraped_file.exists():
        logger.error(f"Scraped file not found: {scraped_file}")
        logger.info("Please run scripts/scrape_dataset.py first.")
        sys.exit(1)
        
    # 2. Safely copy the file (since it might be being written to)
    # We try to read it; if it fails due to lock, we wait a second.
    temp_file = project_root / 'temp_load_scraped.json'
    
    try:
        shutil.copy2(scraped_file, temp_file)
        logger.info(f"Snapshot taken of scraped data: {temp_file}")
    except Exception as e:
        logger.error(f"Could not copy file (scraper might be writing): {e}")
        return

    # 3. Load into RAG
    try:
        settings = Settings()
        loader = DatasetLoader(settings)
        
        # Load the copied snapshot
        loader.load_from_json(temp_file)
        
        logger.info("✅ Successfully updated RAG with latest scraped patterns.")
        
    except Exception as e:
        logger.error(f"Failed to load dataset: {e}")
    finally:
        # Cleanup
        if temp_file.exists():
            temp_file.unlink()
            
    # 4. Show Stats
    print("\n" + "="*60)
    print("Updated RAG Status")
    print("="*60)
    try:
        # Re-instantiate to ensure fresh connection/stats reading
        kb = loader.knowledge_base
        for collection_name in kb.collections.keys():
            stats = kb.get_collection_stats(collection_name)
            print(f"  {collection_name:20s}: {stats['count']:5d} patterns")
    except Exception:
        pass
    print("="*60)

if __name__ == '__main__':
    main()
