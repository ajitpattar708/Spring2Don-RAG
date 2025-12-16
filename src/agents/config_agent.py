"""
Config Agent
Migrates configuration files from Spring Boot to Helidon MP
"""

from pathlib import Path
from typing import Dict, List
import yaml
import sys
import time
from src.config.settings import Settings
from src.rag.knowledge_base import KnowledgeBase
from src.rag.embeddings import EmbeddingModel
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class ConfigAgent:
    """Migrates configuration files from Spring Boot to Helidon MP"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.knowledge_base = KnowledgeBase(settings)
        self.embedding_model = EmbeddingModel(settings)
        self.source_path = None
        self.target_path = None
        
    def migrate(self, project_structure: Dict, source_path: Path = None, target_path: Path = None) -> Dict:
        """
        Migrate configuration files
        
        Args:
            project_structure: Project structure analysis result
            
        Returns:
            Migration result dictionary
        """
        logger.info("Starting configuration migration...")
        
        # Store paths
        if source_path:
            self.source_path = source_path
        if target_path:
            self.target_path = target_path
        
        config_files = project_structure.get('config_files', [])
        if not config_files:
            logger.warning("No configuration files found")
            return {'success': False, 'error': 'No configuration files found'}
        
        migrated_files = []
        total_configs = len(config_files)
        
        if total_configs > 0:
            print(f"   Found {total_configs} configuration file(s) to migrate")
            sys.stdout.flush()
        
        for idx, config_file in enumerate(config_files, 1):
            file_start_time = time.time()
            file_name = config_file.name
            
            try:
                print(f"   [{idx}/{total_configs}] Migrating: {file_name}...", end=' ', flush=True)
                sys.stdout.flush()
                
                result = self._migrate_config_file(config_file)
                file_time = time.time() - file_start_time
                
                if result['success']:
                    migrated_files.append(str(config_file))
                    print(f"[OK] ({file_time:.1f}s)")
                else:
                    error = result.get('error', 'Unknown error')
                    print(f"[FAIL] ({file_time:.1f}s)")
                    print(f"      Error: {error}")
                    logger.error(f"Error migrating {config_file}: {error}")
                    
            except Exception as e:
                file_time = time.time() - file_start_time
                print(f"[EXCEPTION] ({file_time:.1f}s)")
                print(f"      Exception: {type(e).__name__}: {str(e)}")
                logger.error(f"Exception migrating {config_file}: {str(e)}", exc_info=True)
        
        return {
            'success': True,
            'files_migrated': len(migrated_files)
        }
    
    def _migrate_config_file(self, config_file: Path) -> Dict:
        """
        Migrate a single configuration file
        
        Args:
            config_file: Path to configuration file
            
        Returns:
            Migration result for this file
        """
        logger.debug(f"Migrating config file: {config_file}")
        
        file_extension = config_file.suffix.lower()
        
        if file_extension == '.yml' or file_extension == '.yaml':
            return self._migrate_yaml(config_file)
        elif file_extension == '.properties':
            return self._migrate_properties(config_file)
        else:
            logger.warning(f"Unsupported config file format: {file_extension}")
            return {'success': False, 'error': f'Unsupported format: {file_extension}'}
    
    def _migrate_yaml(self, yaml_file: Path) -> Dict:
        """Migrate YAML configuration to MicroProfile Config properties"""
        try:
            # Read YAML file
            with open(yaml_file, 'r', encoding='utf-8') as f:
                yaml_data = yaml.safe_load(f)
            
            # Convert YAML to MicroProfile Config properties
            properties_lines = self._yaml_to_properties(yaml_data)
            properties_content = '\n'.join(properties_lines) if properties_lines else ''
            
            # Post-process
            properties_content = properties_content.replace('javax.persistence', 'jakarta.persistence')
            
            # Write properties file to target directory
            if self.target_path:
                target_resources = self.target_path / 'src' / 'main' / 'resources'
                target_resources.mkdir(parents=True, exist_ok=True)
                properties_file = target_resources / 'microprofile-config.properties'
                
                with open(properties_file, 'w', encoding='utf-8') as f:
                    f.write(properties_content)
                
                logger.info(f"Created MicroProfile Config: {properties_file}")
                
                # Remove original YAML file (Spring config)
                if yaml_file.exists():
                    try:
                        yaml_file.unlink()
                        logger.info(f"Removed Spring config file: {yaml_file}")
                    except Exception as e:
                        logger.warning(f"Could not remove Spring config file: {str(e)}")
            
            return {'success': True}
            
        except Exception as e:
            logger.error(f"Error migrating YAML file: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def _migrate_properties(self, properties_file: Path) -> Dict:
        """Migrate properties file to MicroProfile Config format"""
        try:
            # Read properties file
            with open(properties_file, 'r', encoding='utf-8') as f:
                properties_content = f.read()
            
            # TODO: Transform properties
            # 1. Map Spring Boot property keys to MicroProfile Config keys
            # 2. Use RAG for key mappings
            # 3. Update property values if needed
            
            transformed_properties = self._transform_properties(properties_content)
            
            # Post-process to ensure Jakarta namespaces
            transformed_properties = transformed_properties.replace('javax.', 'jakarta.')
            transformed_properties = transformed_properties.replace('jakarta.sql.DataSource', 'javax.sql.DataSource')  # Exception: DataSource config often still uses javax key in some MP implementations or at least check requirements. Wait, Helidon 4 uses Jakarta.
            # Actually, standard MP Config usually uses javax.sql.DataSource for specific datasource config in older versions, but in Helidon 4/Jakarta 10 it should be javax.sql.DataSource... wait.
            # Correction: Helidon 4 datasource config key is usually "javax.sql.DataSource.myDS..." because the class name itself is javax.sql.DataSource (part of JDK/Java SQL, not Jakarta EE).
            # Java SQL package IS part of the JDK and starts with javax.sql.
            # So 'javax.sql.DataSource' should remain 'javax.sql.DataSource'.
            # But 'javax.persistence' should be 'jakarta.persistence'.
            
            # Specific fixes
            transformed_properties = transformed_properties.replace('jakarta.sql.DataSource', 'javax.sql.DataSource')
            
            # Write transformed properties to target directory
            if self.target_path:
                target_resources = self.target_path / 'src' / 'main' / 'resources'
                target_resources.mkdir(parents=True, exist_ok=True)
                target_properties_file = target_resources / 'microprofile-config.properties'
                
                with open(target_properties_file, 'w', encoding='utf-8') as f:
                    f.write(transformed_properties)
                
                logger.info(f"Created MicroProfile Config: {target_properties_file}")
            
            return {'success': True}
            
        except Exception as e:
            logger.error(f"Error migrating properties file: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def _yaml_to_properties(self, yaml_data: dict, prefix: str = '') -> list:
        """Convert YAML structure to properties format - returns list of lines"""
        properties_lines = []
        
        if not yaml_data:
            return properties_lines
        
        for key, value in yaml_data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            
            if isinstance(value, dict):
                # Recursively process nested dictionaries
                nested_lines = self._yaml_to_properties(value, full_key)
                properties_lines.extend(nested_lines)
            elif isinstance(value, list):
                # Handle lists (convert to comma-separated or indexed)
                mapped_key = self._map_property_key(full_key)
                if value:
                    # Convert list to comma-separated string
                    list_value = ','.join(str(v) for v in value)
                    properties_lines.append(f"{mapped_key}={list_value}")
            else:
                # Map Spring Boot keys to MicroProfile Config keys
                mapped_key = self._map_property_key(full_key)
                # Only add if it's a meaningful mapping (not Spring-specific)
                if not full_key.startswith('spring.') or mapped_key != full_key:
                    properties_lines.append(f"{mapped_key}={value}")
        
        # Remove duplicates (keep last occurrence)
        seen = {}
        unique_lines = []
        for line in properties_lines:
            if '=' in line:
                key = line.split('=')[0].strip()
                seen[key] = line
            else:
                unique_lines.append(line)
        
        return list(seen.values()) + unique_lines
    
    def _map_property_key(self, spring_key: str) -> str:
        """
        Map Spring Boot property key to MicroProfile Config key
        
        Uses RAG to find the best mapping
        """
        try:
            # Generate embedding for property key
            query_text = f"Spring Boot property: {spring_key}"
            embedding = self.embedding_model.encode_single(query_text)
            
            # Search knowledge base
            # Search without filters, then filter in code
            results = self.knowledge_base.search(
                collection_name='config',
                query_embedding=embedding,
                top_k=5,
                filters=None  # Don't filter here, filter in code
            )
            
            if results and len(results) > 0:
                # Find best match with migration_type filter
                best_match = None
                for result in results:
                    metadata = result.get('metadata', {})
                    if metadata.get('migration_type') == 'config':
                        best_match = result
                        break
                
                if not best_match:
                    best_match = results[0]  # Fallback to first result
                
                metadata = best_match.get('metadata', {})
                spring_pattern = metadata.get('spring_pattern', '')
                
                # Check if this key matches the pattern
                if spring_pattern in spring_key or spring_key.startswith(spring_pattern.split('.')[0]):
                    helidon_pattern = metadata.get('helidon_pattern', '')
                    if helidon_pattern:
                        # Extract the mapped key
                        return helidon_pattern
            
            # Minimal fallback only if vector DB search completely fails
            # This should rarely happen if vector DB is properly initialized
            logger.warning(f"No mapping found in vector DB for: {spring_key}, using fallback")
            
            # Only keep critical fallbacks for common properties
            critical_fallbacks = {
                'server.port': 'server.port',  # Same in both
            }
            
            if spring_key in critical_fallbacks:
                return critical_fallbacks[spring_key]
            
            # Return original key if no mapping found (user can fix manually)
            return spring_key
            
        except Exception as e:
            logger.error(f"Error mapping property key: {str(e)}")
            return spring_key
    
    def _transform_properties(self, properties_content: str) -> str:
        """Transform properties content"""
        lines = properties_content.splitlines()
        transformed_lines = []
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                transformed_lines.append(line)
                continue
            
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                
                # Map key to MicroProfile Config
                mapped_key = self._map_property_key(key)
                transformed_lines.append(f"{mapped_key}={value}")
            else:
                transformed_lines.append(line)
                
        return '\n'.join(transformed_lines)

