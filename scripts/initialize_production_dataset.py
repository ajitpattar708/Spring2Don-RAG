#!/usr/bin/env python3
"""
Production Dataset Initialization Script
Initializes the knowledge base with comprehensive migration patterns
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.dataset.production_dataset_generator import ProductionDatasetGenerator
from src.dataset.dataset_loader import DatasetLoader
from src.config.settings import Settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def main():
    """Initialize production dataset"""
    print("=" * 80)
    print("Spring Boot to Helidon MP - Production Dataset Initialization")
    print("=" * 80)
    
    settings = Settings()
    
    # Generate dataset
    dataset_file = project_root / "migration_dataset_production.json"
    
    print(f"\n[1/3] Generating production dataset...")
    generator = ProductionDatasetGenerator()
    
    # Generate comprehensive dataset (can take a while)
    print("   Generating patterns (this may take several minutes)...")
    generator.save_to_json(dataset_file, max_patterns=10000)  # Generate 10K patterns
    
    print(f"   ✓ Dataset generated: {dataset_file}")
    print(f"   ✓ File size: {dataset_file.stat().st_size / (1024*1024):.2f} MB")
    
    # Load dataset into ChromaDB
    print(f"\n[2/3] Loading dataset into ChromaDB...")
    loader = DatasetLoader(settings)
    
    try:
        loader.initialize_knowledge_base(dataset_file)
        print(f"   ✓ Dataset loaded into ChromaDB")
    except Exception as e:
        logger.error(f"Failed to load dataset: {str(e)}")
        print(f"   ✗ Failed to load dataset: {str(e)}")
        return 1
    
    # Print statistics
    print(f"\n[3/3] Dataset Statistics:")
    print(f"   Knowledge base path: {settings.chromadb_path}")
    
    for collection_name in ['annotations', 'dependencies', 'code_patterns', 'config', 'imports']:
        try:
            stats = loader.knowledge_base.get_collection_stats(collection_name)
            print(f"   - {collection_name}: {stats['count']} patterns")
        except Exception as e:
            logger.warning(f"Could not get stats for {collection_name}: {str(e)}")
    
    print("\n" + "=" * 80)
    print("✓ Production dataset initialization complete!")
    print("=" * 80)
    print("\nYou can now run migrations using:")
    print("  python migration_agent_main.py migrate <source> <target> --spring-version 3.4.5 --helidon-version 4.0.0")
    print()
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

