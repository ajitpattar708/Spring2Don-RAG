#!/usr/bin/env python3
"""
Spring Boot to Helidon MP Migration Agent
Main entry point for the migration tool

Based on Spring2Naut-RAG architecture
"""

import argparse
import sys
import os
from pathlib import Path
import xml.etree.ElementTree as ET

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.orchestrator.migration_orchestrator import MigrationOrchestrator
from src.utils.logger import setup_logger
from src.config.settings import Settings
from src.utils.version_compatibility import VersionCompatibility

logger = setup_logger(__name__)


def detect_spring_version(source_path: str) -> str:
    """Detect Spring Boot version from pom.xml if not provided"""
    pom_path = Path(source_path) / 'pom.xml'
    if not pom_path.exists():
        return '3.4.5'  # Default fallback
    
    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()
        
        # Get namespace from root element (handle both prefixed and default namespaces)
        namespace = root.tag.split('}')[0].strip('{') if '}' in root.tag else ''
        ns = {'maven': namespace} if namespace else {}
        
        # Try with namespace first
        parent = root.find('maven:parent', ns) if ns else root.find('parent')
        if parent is None and not ns:
            # Try with default namespace
            parent = root.find('{http://maven.apache.org/POM/4.0.0}parent')
        
        if parent is not None:
            artifact_id = parent.find('maven:artifactId', ns) if ns else parent.find('artifactId')
            if artifact_id is None and not ns:
                artifact_id = parent.find('{http://maven.apache.org/POM/4.0.0}artifactId')
            
            version_elem = parent.find('maven:version', ns) if ns else parent.find('version')
            if version_elem is None and not ns:
                version_elem = parent.find('{http://maven.apache.org/POM/4.0.0}version')
            
            if artifact_id is not None and version_elem is not None:
                artifact_text = artifact_id.text or ''
                if 'spring-boot-starter-parent' in artifact_text:
                    version = version_elem.text.strip()
                    logger.info(f"Detected Spring Boot version from pom.xml: {version}")
                    return version
        
        # Check for spring.boot.version property
        properties = root.find('maven:properties', ns) if ns else root.find('properties')
        if properties is None and not ns:
            properties = root.find('{http://maven.apache.org/POM/4.0.0}properties')
        
        if properties is not None:
            spring_version_prop = properties.find('maven:spring.boot.version', ns) if ns else properties.find('spring.boot.version')
            if spring_version_prop is None and not ns:
                spring_version_prop = properties.find('{http://maven.apache.org/POM/4.0.0}spring.boot.version')
            
            if spring_version_prop is not None:
                version = spring_version_prop.text.strip()
                logger.info(f"Detected Spring Boot version from properties: {version}")
                return version
    except Exception as e:
        logger.warning(f"Could not detect Spring Boot version from pom.xml: {str(e)}")
    
    return '3.4.5'  # Default fallback


def migrate_command(args):
    """Execute migration command"""
    try:
        # Set default versions if not provided
        spring_version = args.spring_version or detect_spring_version(args.source)
        helidon_version = args.helidon_version or '4.3.2'
        
        print("--- MIGRATION AGENT STARTING ---", flush=True)
        logger.info(f"Starting migration from {args.source} to {args.target}")
        logger.info(f"Spring Boot version: {spring_version}")
        logger.info(f"Helidon MP version: {helidon_version}")
        
        # Validate version compatibility
        is_compatible, error_msg = VersionCompatibility.validate_compatibility(
            spring_version, helidon_version
        )
        if not is_compatible:
            logger.warning(f"⚠️  Version Compatibility Warning: {error_msg}")
            print(f"\n⚠️  WARNING: {error_msg}\n", flush=True)
        
        # Get version requirements
        version_info = VersionCompatibility.get_version_info(helidon_version)
        print(f"\nHelidon {helidon_version} Requirements:", flush=True)
        
        # Show JDK options
        required_jdk = version_info['required_jdk']
        production_jdk = version_info.get('production_jdk', required_jdk)  # LTS for production
        performance_jdk = version_info.get('recommended_jdk')  # For performance
        
        jdk_info = f"{required_jdk}+ (minimum required)"
        if production_jdk != required_jdk:
            jdk_info += f", {production_jdk} (LTS - recommended for production)"
        if performance_jdk:
            jdk_info += f", {performance_jdk} (for optimal performance, non-LTS)"
        
        print(f"   - JDK: {jdk_info}", flush=True)
        print(f"   - Maven: {version_info['required_maven']}+ (recommended)", flush=True)
        print(f"   - Jakarta EE: {version_info['jakarta_ee_version']}", flush=True)
        print(f"   - MicroProfile: {version_info['microprofile_version']}", flush=True)
        print(f"\nProduction Tip: Use Java {production_jdk} (LTS) for production stability", flush=True)
        if performance_jdk:
            print(f"   Consider Java {performance_jdk} for performance-critical applications\n", flush=True)
        
        # Initialize settings
        settings = Settings()
        
        # Create orchestrator
        orchestrator = MigrationOrchestrator(
            source_path=args.source,
            target_path=args.target,
            spring_version=spring_version,
            helidon_version=helidon_version,
            settings=settings
        )
        
        # Execute migration
        result = orchestrator.migrate()
        
        if result.success:
            logger.info("Migration completed successfully!")
            logger.info(f"Migrated files: {result.files_migrated}")
            logger.info(f"Total transformations: {result.transformations_applied}")
            return 0
        else:
            logger.error(f"Migration failed: {result.error_message}")
            return 1
            
    except Exception as e:
        logger.error(f"Migration error: {str(e)}", exc_info=True)
        return 1


def init_command(args):
    """Initialize production dataset"""
    try:
        print("Initializing production dataset...")
        from scripts.initialize_production_dataset import main as init_main
        return init_main()
    except Exception as e:
        logger.error(f"Initialization error: {str(e)}", exc_info=True)
        return 1


def test_command(args):
    """Execute test command"""
    try:
        logger.info("Running migration agent tests...")
        
        # Test with example project
        example_spring = project_root / "examples" / "spring"
        example_helidon = project_root / "examples" / "helidon"
        
        if not example_spring.exists():
            logger.error(f"Example Spring project not found: {example_spring}")
            return 1
        
        logger.info("Running test migration on example project...")
        settings = Settings()
        
        # Use default versions (detect Spring version, use Helidon 4.3.2)
        spring_version = detect_spring_version(str(example_spring))
        helidon_version = "4.3.2"
        
        orchestrator = MigrationOrchestrator(
            source_path=str(example_spring),
            target_path=str(example_helidon),
            spring_version=spring_version,
            helidon_version=helidon_version,
            settings=settings
        )
        
        result = orchestrator.migrate()
        
        if result.success:
            logger.info("✓ Test migration completed successfully!")
            logger.info(f"  Migrated files: {result.files_migrated}")
            logger.info(f"  Transformations: {result.transformations_applied}")
            return 0
        else:
            logger.error(f"✗ Test migration failed: {result.error_message}")
            return 1
        
    except Exception as e:
        logger.error(f"Test error: {str(e)}", exc_info=True)
        return 1


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Spring Boot to Helidon MP Migration Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize production dataset (first time setup)
  python migration_agent_main.py init

  # Migrate a Spring Boot project (with versions)
  python migration_agent_main.py migrate \\
      /path/to/spring/project \\
      /path/to/output/helidon/project \\
      --spring-version 3.4.5 \\
      --helidon-version 4.3.2

  # Migrate using defaults (Spring version detected from pom.xml, Helidon 4.3.2)
  python migration_agent_main.py migrate \\
      /path/to/spring/project \\
      /path/to/output/helidon/project

  # Run tests
  python migration_agent_main.py test
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Migrate command
    migrate_parser = subparsers.add_parser('migrate', help='Migrate Spring Boot project to Helidon MP')
    migrate_parser.add_argument('source', help='Source Spring Boot project path')
    migrate_parser.add_argument('target', help='Target Helidon MP project path')
    migrate_parser.add_argument('--spring-version', default=None, help='Spring Boot version (e.g., 3.4.5). If not provided, will be detected from pom.xml or default to 3.4.5')
    migrate_parser.add_argument('--helidon-version', default='4.3.2', help='Helidon MP version (default: 4.3.2, e.g., 4.0.0)')
    migrate_parser.add_argument('--dry-run', action='store_true', help='Preview changes without applying')
    migrate_parser.set_defaults(func=migrate_command)
    
    # Init command
    init_parser = subparsers.add_parser('init', help='Initialize production dataset')
    init_parser.set_defaults(func=init_command)
    
    # Test command
    test_parser = subparsers.add_parser('test', help='Run migration agent tests')
    test_parser.set_defaults(func=test_command)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())

