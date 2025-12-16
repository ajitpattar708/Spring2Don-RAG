#!/usr/bin/env python3
"""
Load Web Dataset Script
Loads the curated web-scraped dataset into the knowledge base.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.dataset.dataset_loader import DatasetLoader
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

def main():
    logger.info("Loading web-sourced migration dataset...")
    
    settings = Settings()
    loader = DatasetLoader(settings)
    
    dataset_file = project_root / 'migration_dataset_real_web.json'
    
    if dataset_file.exists():
        loader.load_from_json(dataset_file)
        logger.info(f"Successfully loaded web patterns from {dataset_file}")
    else:
        logger.error(f"Dataset file not found: {dataset_file}")

    # Load the new Manual Builder dataset
    manual_builder_path = project_root / 'migration_dataset_helidon_manual.json'
    if manual_builder_path.exists():
        logger.info(f"Loading manual builder dataset: {manual_builder_path}")
        loader.load_from_json(manual_builder_path)
    if not dataset_file.exists() and not manual_builder_path.exists():
        logger.error("No dataset files found.")
        sys.exit(1)

if __name__ == '__main__':
    main()
