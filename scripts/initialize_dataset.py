#!/usr/bin/env python3
"""
Initialize Dataset Script
Creates and loads migration patterns into ChromaDB
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.dataset.dataset_loader import DatasetLoader
from src.dataset.dataset_generator import DatasetGenerator
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def main():
    """Initialize the knowledge base with migration patterns"""
    logger.info("Initializing migration dataset...")
    
    # Initialize settings
    settings = Settings()
    settings.validate()
    
    # Create dataset file if it doesn't exist
    dataset_file = project_root / 'migration_dataset.json'
    
    if not dataset_file.exists():
        logger.info("Generating sample dataset...")
        generator = DatasetGenerator()
        generator.save_to_json(dataset_file)
        logger.info(f"Dataset generated: {dataset_file}")
    else:
        logger.info(f"Using existing dataset: {dataset_file}")
    
    # Load dataset into knowledge base
    loader = DatasetLoader(settings)
    loader.initialize_knowledge_base(dataset_file)
    
    logger.info("Dataset initialization completed!")
    
    # Print summary
    print("\n" + "="*60)
    print("Dataset Initialization Summary")
    print("="*60)
    for collection_name in loader.knowledge_base.collections.keys():
        stats = loader.knowledge_base.get_collection_stats(collection_name)
        print(f"  {collection_name:20s}: {stats['count']:4d} patterns")
    print("="*60)


if __name__ == '__main__':
    main()


