#!/usr/bin/env python3
"""
Run Migration Example
Demonstrates end-to-end migration of example Spring Boot project
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.dataset.dataset_loader import DatasetLoader
from src.orchestrator.migration_orchestrator import MigrationOrchestrator
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def main():
    """Run example migration"""
    logger.info("="*60)
    logger.info("Spring Boot to Helidon MP Migration Example")
    logger.info("="*60)
    
    # Initialize settings
    settings = Settings()
    
    # Initialize dataset if needed
    logger.info("\nStep 1: Initializing knowledge base...")
    dataset_file = project_root / 'migration_dataset.json'
    loader = DatasetLoader(settings)
    loader.initialize_knowledge_base(dataset_file)
    
    # Run migration
    logger.info("\nStep 2: Running migration...")
    source_path = project_root / 'examples' / 'spring'
    target_path = project_root / 'examples' / 'helidon'
    
    orchestrator = MigrationOrchestrator(
        source_path=str(source_path),
        target_path=str(target_path),
        spring_version='3.4.5',
        helidon_version='4.0.0',
        settings=settings
    )
    
    result = orchestrator.migrate()
    
    # Print results
    logger.info("\n" + "="*60)
    logger.info("Migration Results")
    logger.info("="*60)
    logger.info(f"Success: {result.success}")
    logger.info(f"Files Migrated: {result.files_migrated}")
    logger.info(f"Transformations Applied: {result.transformations_applied}")
    
    if result.warnings:
        logger.info(f"Warnings: {len(result.warnings)}")
        for warning in result.warnings:
            logger.warning(f"  - {warning}")
    
    if not result.success:
        logger.error(f"Error: {result.error_message}")
        return 1
    
    logger.info("\nMigration completed successfully!")
    logger.info(f"Migrated project available at: {target_path}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())


