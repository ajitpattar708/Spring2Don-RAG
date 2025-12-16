#!/usr/bin/env python3
"""
Add Hardcoded Mappings to Vector DB
Moves all hardcoded mappings to vector database for better maintainability
"""

import sys
import json
import uuid
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.dataset.dataset_loader import DatasetLoader
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def create_annotation_patterns():
    """Create annotation mapping patterns"""
    patterns = []
    
    annotation_mappings = [
        {'spring': '@RestController', 'helidon': '@Path', 'description': 'REST controller to JAX-RS path'},
        {'spring': '@GetMapping', 'helidon': '@GET', 'description': 'GET mapping to JAX-RS GET'},
        {'spring': '@PostMapping', 'helidon': '@POST', 'description': 'POST mapping to JAX-RS POST'},
        {'spring': '@PutMapping', 'helidon': '@PUT', 'description': 'PUT mapping to JAX-RS PUT'},
        {'spring': '@DeleteMapping', 'helidon': '@DELETE', 'description': 'DELETE mapping to JAX-RS DELETE'},
        {'spring': '@PatchMapping', 'helidon': '@PATCH', 'description': 'PATCH mapping to JAX-RS PATCH'},
        {'spring': '@Autowired', 'helidon': '@Inject', 'description': 'Spring autowire to CDI inject'},
        {'spring': '@Service', 'helidon': '@ApplicationScoped', 'description': 'Spring service to CDI application scoped'},
        {'spring': '@Component', 'helidon': '@ApplicationScoped', 'description': 'Spring component to CDI application scoped'},
        {'spring': '@Repository', 'helidon': '@ApplicationScoped', 'description': 'Spring repository to CDI application scoped'},
        {'spring': '@Value', 'helidon': '@ConfigProperty', 'description': 'Spring value to MicroProfile config property'},
        {'spring': '@PathVariable', 'helidon': '@PathParam', 'description': 'Path variable to JAX-RS path param'},
        {'spring': '@RequestParam', 'helidon': '@QueryParam', 'description': 'Request param to JAX-RS query param'},
        {'spring': '@RequestBody', 'helidon': '@Consumes', 'description': 'Request body to JAX-RS consumes'},
        {'spring': '@SpringBootApplication', 'helidon': '', 'description': 'Remove Spring Boot application annotation'},
        {'spring': '@RequestMapping', 'helidon': '@Path', 'description': 'Request mapping to JAX-RS path'},
        # JPA annotations (these stay the same in Jakarta EE)
        {'spring': '@Entity', 'helidon': '@Entity', 'description': 'JPA Entity (same in Jakarta)'},
        {'spring': '@Id', 'helidon': '@Id', 'description': 'JPA Id (same in Jakarta)'},
        {'spring': '@GeneratedValue', 'helidon': '@GeneratedValue', 'description': 'JPA GeneratedValue (same in Jakarta)'},
        {'spring': '@Table', 'helidon': '@Table', 'description': 'JPA Table (same in Jakarta)'},
        {'spring': '@Column', 'helidon': '@Column', 'description': 'JPA Column (same in Jakarta)'},
    ]
    
    for mapping in annotation_mappings:
        pattern = {
            'id': str(uuid.uuid4()),
            'migration_type': 'annotation',
            'spring_pattern': mapping['spring'],
            'helidon_pattern': mapping['helidon'],
            'spring_version': '3.4.5',
            'helidon_version': '4.3.2',
            'complexity': 'simple',
            'category': 'annotation',
            'description': mapping['description'],
            'text': f"Spring: {mapping['spring']} -> Helidon: {mapping['helidon']}"
        }
        patterns.append(pattern)
    
    return patterns


def create_config_patterns():
    """Create config property mapping patterns"""
    patterns = []
    
    config_mappings = [
        {'spring': 'server.port', 'helidon': 'server.port', 'description': 'Server port (same)'},
        {'spring': 'spring.datasource.url', 'helidon': 'javax.sql.DataSource.myDS.url', 'description': 'Database URL'},
        {'spring': 'spring.datasource.driver-class-name', 'helidon': 'javax.sql.DataSource.myDS.driverClassName', 'description': 'Database driver'},
        {'spring': 'spring.datasource.username', 'helidon': 'javax.sql.DataSource.myDS.username', 'description': 'Database username'},
        {'spring': 'spring.datasource.password', 'helidon': 'javax.sql.DataSource.myDS.password', 'description': 'Database password'},
        {'spring': 'spring.jpa.hibernate.ddl-auto', 'helidon': 'javax.persistence.schema-generation.database.action', 'description': 'JPA schema generation'},
        {'spring': 'spring.jpa.show-sql', 'helidon': 'javax.persistence.logging.level.sql', 'description': 'JPA SQL logging'},
        {'spring': 'logging.level.root', 'helidon': 'mp.logging.level.root', 'description': 'Root logging level'},
        {'spring': 'logging.level.com.example.demo', 'helidon': 'mp.logging.level.com.example.demo', 'description': 'Package logging level'},
    ]
    
    for mapping in config_mappings:
        pattern = {
            'id': str(uuid.uuid4()),
            'migration_type': 'config',
            'spring_pattern': mapping['spring'],
            'helidon_pattern': mapping['helidon'],
            'spring_version': '3.4.5',
            'helidon_version': '4.3.2',
            'complexity': 'simple',
            'category': 'config',
            'description': mapping['description'],
            'text': f"Spring Config: {mapping['spring']} -> Helidon Config: {mapping['helidon']}"
        }
        patterns.append(pattern)
    
    return patterns


def create_import_patterns():
    """Create import statement mapping patterns"""
    patterns = []
    
    import_mappings = [
        {'spring': 'org.springframework.web.bind.annotation.RestController', 'helidon': 'jakarta.ws.rs.Path'},
        {'spring': 'org.springframework.web.bind.annotation.GetMapping', 'helidon': 'jakarta.ws.rs.GET'},
        {'spring': 'org.springframework.web.bind.annotation.PostMapping', 'helidon': 'jakarta.ws.rs.POST'},
        {'spring': 'org.springframework.web.bind.annotation.PutMapping', 'helidon': 'jakarta.ws.rs.PUT'},
        {'spring': 'org.springframework.web.bind.annotation.DeleteMapping', 'helidon': 'jakarta.ws.rs.DELETE'},
        {'spring': 'org.springframework.web.bind.annotation.PatchMapping', 'helidon': 'jakarta.ws.rs.PATCH'},
        {'spring': 'org.springframework.web.bind.annotation.PathVariable', 'helidon': 'jakarta.ws.rs.PathParam'},
        {'spring': 'org.springframework.web.bind.annotation.RequestParam', 'helidon': 'jakarta.ws.rs.QueryParam'},
        {'spring': 'org.springframework.web.bind.annotation.RequestBody', 'helidon': 'jakarta.ws.rs.Consumes'},
        {'spring': 'org.springframework.beans.factory.annotation.Autowired', 'helidon': 'jakarta.inject.Inject'},
        {'spring': 'org.springframework.stereotype.Service', 'helidon': 'jakarta.enterprise.context.ApplicationScoped'},
        {'spring': 'org.springframework.stereotype.Component', 'helidon': 'jakarta.enterprise.context.ApplicationScoped'},
        {'spring': 'org.springframework.stereotype.Repository', 'helidon': 'jakarta.enterprise.context.ApplicationScoped'},
        {'spring': 'org.springframework.beans.factory.annotation.Value', 'helidon': 'org.eclipse.microprofile.config.inject.ConfigProperty'},
        {'spring': 'org.springframework.http.ResponseEntity', 'helidon': 'jakarta.ws.rs.core.Response'},
        {'spring': 'org.springframework.http.HttpStatus', 'helidon': 'jakarta.ws.rs.core.Response.Status'},
        {'spring': 'org.springframework.http.MediaType', 'helidon': 'jakarta.ws.rs.core.MediaType'},
        {'spring': 'org.springframework.boot.SpringApplication', 'helidon': '', 'description': 'Remove Spring Boot application'},
        {'spring': 'org.springframework.boot.autoconfigure.SpringBootApplication', 'helidon': '', 'description': 'Remove Spring Boot application'},
        {'spring': 'org.springframework.data.jpa.repository.JpaRepository', 'helidon': '', 'description': 'Remove Spring Data JPA'},
    ]
    
    for mapping in import_mappings:
        pattern = {
            'id': str(uuid.uuid4()),
            'migration_type': 'import',
            'spring_pattern': mapping['spring'],
            'helidon_pattern': mapping.get('helidon', ''),
            'spring_version': '3.4.5',
            'helidon_version': '4.3.2',
            'complexity': 'simple',
            'category': 'import',
            'description': mapping.get('description', f"Import: {mapping['spring']}"),
            'text': f"Spring Import: {mapping['spring']} -> Helidon: {mapping.get('helidon', 'REMOVE')}"
        }
        patterns.append(pattern)
    
    return patterns


def main():
    """Add mappings to vector database"""
    logger.info("Adding hardcoded mappings to vector database...")
    
    settings = Settings()
    
    # Create patterns
    all_patterns = []
    all_patterns.extend(create_annotation_patterns())
    all_patterns.extend(create_config_patterns())
    all_patterns.extend(create_import_patterns())
    
    logger.info(f"Created {len(all_patterns)} mapping patterns")
    
    # Save to JSON file first
    mappings_file = project_root / 'migration_dataset_mappings.json'
    with open(mappings_file, 'w', encoding='utf-8') as f:
        json.dump(all_patterns, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Saved mappings to: {mappings_file}")
    
    # Load into vector DB
    loader = DatasetLoader(settings)
    loader.load_from_json(mappings_file)
    
    logger.info("✅ All mappings added to vector database!")
    logger.info(f"   - Annotations: {len(create_annotation_patterns())}")
    logger.info(f"   - Config: {len(create_config_patterns())}")
    logger.info(f"   - Imports: {len(create_import_patterns())}")


if __name__ == '__main__':
    main()

