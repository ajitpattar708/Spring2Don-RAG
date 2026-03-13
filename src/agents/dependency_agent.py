"""
Dependency Agent
Handles Maven/Gradle dependency migration from Spring Boot to Helidon MP
"""

from pathlib import Path
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET
import sys
import time
from src.config.settings import Settings
from src.rag.knowledge_base import KnowledgeBase
from src.rag.embeddings import EmbeddingModel
from src.rag.llm_provider import LLMProviderFactory
from src.utils.logger import setup_logger
from src.utils.version_compatibility import VersionCompatibility

logger = setup_logger(__name__)

LOMBOK_VERSION = "1.18.42"


class DependencyAgent:
    """Migrates build dependencies from Spring Boot to Helidon MP"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.knowledge_base = KnowledgeBase(settings)
        self.embedding_model = EmbeddingModel(settings)
        self.llm_provider = LLMProviderFactory.create(settings)
        
    def migrate(self, project_structure: Dict) -> Dict:
        """
        Migrate dependencies in build files
        
        Args:
            project_structure: Project structure analysis result
            
        Returns:
            Migration result dictionary
        """
        logger.info("Starting dependency migration...")
        
        if project_structure['build_tool'] == 'maven':
            return self._migrate_maven(project_structure)
        elif project_structure['build_tool'] == 'gradle':
            return self._migrate_gradle(project_structure)
        else:
            logger.warning("No build tool detected")
            return {'success': False, 'error': 'No build tool detected'}
    
    def _migrate_maven(self, project_structure: Dict) -> Dict:
        """Migrate Maven POM file"""
        pom_file = project_structure.get('pom_file')
        if not pom_file:
            return {'success': False, 'error': 'POM file not found'}
        
        logger.info(f"Migrating Maven POM: {pom_file}")
        
        try:
            # Parse POM XML
            tree = ET.parse(pom_file)
            root = tree.getroot()
            
            # Define namespace
            ns = {'maven': 'http://maven.apache.org/POM/4.0.0'}
            
            # 1. Handle Parent and Project Coordinates
            # If we remove parent, we might lose inherited groupId/version.
            # So check and copy them to project level if missing.
            parent = root.find('maven:parent', ns)
            project_group_id = root.find('maven:groupId', ns)
            project_version = root.find('maven:version', ns)
            
            if parent is not None:
                parent_group_id = parent.find('maven:groupId', ns)
                parent_version = parent.find('maven:version', ns)
                
                if project_group_id is None and parent_group_id is not None:
                    # Promote groupId
                    new_group_id = ET.Element('{http://maven.apache.org/POM/4.0.0}groupId')
                    new_group_id.text = parent_group_id.text
                    # Insert after modelVersion (index 1 usually)
                    root.insert(1, new_group_id)
                
                if project_version is None and parent_version is not None:
                    # Promote version
                    new_version = ET.Element('{http://maven.apache.org/POM/4.0.0}version')
                    new_version.text = parent_version.text
                    # Insert after artifactId
                    root.insert(3, new_version) # Approx location
                    
                # Remove the old parent
                root.remove(parent)
                logger.info("Removed existing parent POM")
                
            # Helidon MP 4.x should not rely on a synthetic parent POM here.
            # We keep the project as a normal Maven module and manage Helidon
            # versions explicitly via the helidon.version property.

            # 2. Dependency Migration
            dependencies_modified = 0
            
            # Find dependencies container
            deps_container = root.find('maven:dependencies', ns)
            if deps_container is None:
                deps_container = ET.SubElement(root, '{http://maven.apache.org/POM/4.0.0}dependencies')

            # Get all current dependencies
            current_deps = list(deps_container.findall('maven:dependency', ns))
            total_deps = len(current_deps)
            
            # We will rebuild the list of dependencies to handle duplicates cleanly
            new_deps_map = {} # Key: groupId:artifactId -> Element
            
            for dep in current_deps:
                group_id_elem = dep.find('maven:groupId', ns)
                artifact_id_elem = dep.find('maven:artifactId', ns)
                
                if group_id_elem is None or artifact_id_elem is None:
                    continue
                    
                group_id = group_id_elem.text
                artifact_id = artifact_id_elem.text
                
                if self._is_spring_dependency(dep, ns):
                    if self._should_remove_spring_dependency(artifact_id):
                        logger.info(f"Removing Spring-only dependency with no Helidon runtime equivalent: {artifact_id}")
                        continue

                    # Migrate Spring dependency
                    scope_elem = dep.find('maven:scope', ns)
                    dependency_scope = scope_elem.text.strip() if scope_elem is not None and scope_elem.text else None
                    helidon_dep = self._find_helidon_dependency(artifact_id, dependency_scope)
                    
                    if helidon_dep:
                        # Update dependency info
                        group_id_elem.text = helidon_dep['groupId']
                        artifact_id_elem.text = helidon_dep['artifactId']
                        
                        # Handle version
                        version_elem = dep.find('maven:version', ns)
                        if helidon_dep.get('version'):
                            if version_elem is None:
                                version_elem = ET.SubElement(dep, '{http://maven.apache.org/POM/4.0.0}version')
                            version_elem.text = helidon_dep['version']
                        elif version_elem is not None:
                             # Remove explicit version if managed by parent
                             dep.remove(version_elem)

                        # Normalize dependency metadata to avoid carrying Spring-specific test/BOM shape forward.
                        type_elem = dep.find('maven:type', ns)
                        if helidon_dep.get('type'):
                            if type_elem is None:
                                type_elem = ET.SubElement(dep, '{http://maven.apache.org/POM/4.0.0}type')
                            type_elem.text = helidon_dep['type']
                        elif type_elem is not None:
                            dep.remove(type_elem)

                        if helidon_dep.get('scope'):
                            if scope_elem is None:
                                scope_elem = ET.SubElement(dep, '{http://maven.apache.org/POM/4.0.0}scope')
                            scope_elem.text = helidon_dep['scope']
                        elif scope_elem is not None and (scope_elem.text or '').strip() != 'test':
                            dep.remove(scope_elem)

                        exclusions_elem = dep.find('maven:exclusions', ns)
                        if (
                            exclusions_elem is not None
                            and not helidon_dep.get('preserve_exclusions')
                            and not self._is_inhouse_dependency(group_id)
                        ):
                            dep.remove(exclusions_elem)
                        
                        dependencies_modified += 1
                        logger.info(f"Migrated: {artifact_id} -> {helidon_dep['artifactId']}")
                        
                        # Store in map (overwriting previous if duplicate key, which achieves deduplication)
                        key = f"{helidon_dep['groupId']}:{helidon_dep['artifactId']}"
                        new_deps_map[key] = dep
                    else:
                         logger.warning(f"Removing unmapped Spring dependency: {artifact_id}")
                         # Don't add to map, effectively removing it
                else:
                    # Keep non-Spring dependency
                    if group_id == 'org.projectlombok' and artifact_id == 'lombok':
                        version_elem = dep.find('maven:version', ns)
                        if version_elem is None:
                            version_elem = ET.SubElement(dep, '{http://maven.apache.org/POM/4.0.0}version')
                        version_elem.text = LOMBOK_VERSION
                        logger.info(f"Updated Lombok dependency to {LOMBOK_VERSION}")
                    key = f"{group_id}:{artifact_id}"
                    new_deps_map[key] = dep

            # Clear current dependencies
            for dep in list(deps_container):
                deps_container.remove(dep)
                
            # Add back unique dependencies
            # Also ensure Core Helidon bundle is present
            helidon_version = getattr(self.settings, 'helidon_version', '4.3.2')
            core_key = 'io.helidon.microprofile.bundles:helidon-microprofile'
            if core_key not in new_deps_map:
                # Add it
                core_dep = ET.Element('{http://maven.apache.org/POM/4.0.0}dependency')
                g = ET.SubElement(core_dep, '{http://maven.apache.org/POM/4.0.0}groupId')
                g.text = 'io.helidon.microprofile.bundles'
                a = ET.SubElement(core_dep, '{http://maven.apache.org/POM/4.0.0}artifactId')
                a.text = 'helidon-microprofile'
                # Version managed by parent usually, but valid to add if needed
                # v = ET.SubElement(core_dep, '{http://maven.apache.org/POM/4.0.0}version')
                # v.text = helidon_version
                new_deps_map[core_key] = core_dep
                logger.info("Added missing helidon-microprofile core dependency")

            # Ensure Helidon datasource + Hikari is present when Spring JDBC/Hikari was used
            spring_datasource_keys = {
                'spring-boot-starter-jdbc',
                'spring-boot-starter-data-jpa'
            }
            used_spring_datasource = any(
                (dep.find('maven:artifactId', ns) is not None and
                 dep.find('maven:artifactId', ns).text in spring_datasource_keys)
                for dep in current_deps
            )
            if used_spring_datasource:
                ds_key = 'io.helidon.integrations.cdi:helidon-integrations-cdi-datasource'
                if ds_key not in new_deps_map:
                    ds_dep = ET.Element('{http://maven.apache.org/POM/4.0.0}dependency')
                    g = ET.SubElement(ds_dep, '{http://maven.apache.org/POM/4.0.0}groupId')
                    g.text = 'io.helidon.integrations.cdi'
                    a = ET.SubElement(ds_dep, '{http://maven.apache.org/POM/4.0.0}artifactId')
                    a.text = 'helidon-integrations-cdi-datasource'
                    new_deps_map[ds_key] = ds_dep
                    logger.info("Added Helidon datasource integration dependency")

                hikari_key = 'com.zaxxer:HikariCP'
                if hikari_key not in new_deps_map:
                    hikari_dep = ET.Element('{http://maven.apache.org/POM/4.0.0}dependency')
                    g = ET.SubElement(hikari_dep, '{http://maven.apache.org/POM/4.0.0}groupId')
                    g.text = 'com.zaxxer'
                    a = ET.SubElement(hikari_dep, '{http://maven.apache.org/POM/4.0.0}artifactId')
                    a.text = 'HikariCP'
                    new_deps_map[hikari_key] = hikari_dep
                    logger.info("Added HikariCP dependency for datasource support")
            
            # Sort dependencies (optional but nice)
            sorted_keys = sorted(new_deps_map.keys())
            for key in sorted_keys:
                deps_container.append(new_deps_map[key])

            
            # 3. Cleanup Build Plugins
            build = root.find('maven:build', ns)
            if build is not None:
                plugins = build.find('maven:plugins', ns)
                if plugins is not None:
                    for plugin in list(plugins.findall('maven:plugin', ns)):
                        artifact_id = plugin.find('maven:artifactId', ns)
                        if artifact_id is not None and (
                            'spring-boot-maven-plugin' in artifact_id.text
                            or artifact_id.text == 'jacoco-maven-plugin'
                            or artifact_id.text == 'dockerfile-maven-plugin'
                            or artifact_id.text == 'maven-dependency-plugin'
                        ):
                            plugins.remove(plugin)
                            if artifact_id.text == 'jacoco-maven-plugin':
                                logger.info("Removed JaCoCo Maven plugin")
                            elif artifact_id.text == 'dockerfile-maven-plugin':
                                logger.info("Removed Dockerfile Maven plugin")
                            elif artifact_id.text == 'maven-dependency-plugin':
                                logger.info("Removed Maven dependency plugin")
                            else:
                                logger.info("Removed Spring Boot Maven plugin")
            
            # Remove Spring references from POM metadata
            self._remove_spring_references(root, ns)
            
            # Update Java version based on Helidon requirements
            try:
                self._update_java_version(root, ns)
            except Exception as e:
                logger.error(f"Error updating Java version: {str(e)}")

            # Ensure helidon.version property is present for visibility
            try:
                self._ensure_helidon_version_property(root, ns)
            except Exception as e:
                logger.error(f"Error setting helidon.version property: {str(e)}")

            try:
                self._ensure_helidon_dependency_versions(root, ns)
            except Exception as e:
                logger.error(f"Error setting Helidon dependency versions: {str(e)}")

            try:
                self._ensure_maven_central_repository(root, ns)
            except Exception as e:
                logger.error(f"Error ensuring Maven Central repository: {str(e)}")
            
            # Update Maven compiler plugin with correct Java version
            try:
                self._update_maven_compiler_plugin(root, ns)
            except Exception as e:
                logger.error(f"Error updating Maven compiler plugin: {str(e)}")
            
            # Save modified POM
            try:
                self._write_clean_xml(tree, pom_file)
                logger.info(f"Saved migrated POM: {pom_file}")
            except Exception as e:
                logger.error(f"Error saving POM file: {str(e)}")
                raise
            
            return {
                'success': True,
                'files_modified': [str(pom_file)],
                'dependencies_migrated': dependencies_modified
            }
            
        except Exception as e:
            logger.error(f"Error migrating Maven POM: {str(e)}")
            # import traceback
            # traceback.print_exc()
            return {'success': False, 'error': str(e)}
    
    def _migrate_gradle(self, project_structure: Dict) -> Dict:
        """Migrate Gradle build file"""
        build_gradle = project_structure.get('build_gradle')
        if not build_gradle:
            return {'success': False, 'error': 'build.gradle not found'}
        
        logger.info(f"Migrating Gradle build: {build_gradle}")
        
        # TODO: Implement Gradle build migration
        # 1. Parse build.gradle
        # 2. Find Spring Boot dependencies
        # 3. Replace with Helidon MP equivalents
        
        return {'success': True, 'files_modified': [str(build_gradle)]}
    
    def _find_helidon_dependency(self, spring_artifact_id: str, dependency_scope: Optional[str] = None) -> Optional[Dict]:
        """
        Find Helidon MP equivalent for Spring Boot dependency using RAG
        
        Args:
            spring_artifact_id: Spring Boot artifact ID
            
        Returns:
            Dictionary with groupId, artifactId, and version, or None
        """
        try:
            helidon_version = getattr(self.settings, 'helidon_version', '4.0.0')

            deterministic_match = self._deterministic_dependency_mapping(
                spring_artifact_id,
                dependency_scope,
                helidon_version,
            )
            if deterministic_match is not None:
                return deterministic_match
            
            # Generate embedding for the Spring dependency
            query_text = f"Spring Boot dependency: {spring_artifact_id} to Helidon {helidon_version}"
            embedding = self.embedding_model.encode_single(query_text)
            
            # Search knowledge base - search without filters first for better matching
            # Then filter results by migration_type and version compatibility
            results = self.knowledge_base.search(
                collection_name='dependencies',
                query_embedding=embedding,
                top_k=10,  # Get more results for better matching
                filters=None  # Don't filter here, filter in code
            )
            
            if results and len(results) > 0:
                # Find best match with version compatibility
                # Prioritize exact artifact matches and avoid test dependencies
                best_match = None
                best_score = 0
                
                for result in results:
                    metadata = result.get('metadata', {})
                    
                    # Filter by migration_type
                    migration_type = metadata.get('migration_type', '')
                    if migration_type != 'dependency':
                        continue
                    
                    result_helidon_version = metadata.get('helidon_version', '')
                    
                    # Check if version matches or is compatible
                    if not self._is_version_compatible(result_helidon_version, helidon_version):
                        continue
                    
                    helidon_pattern = metadata.get('helidon_pattern', '')
                    spring_pattern = metadata.get('spring_pattern', '')

                    candidate = self._parse_dependency_pattern(helidon_pattern, helidon_version)
                    if not candidate or not self._is_valid_helidon_dependency_candidate(
                        spring_artifact_id,
                        candidate,
                        dependency_scope,
                    ):
                        continue
                    
                    # Score the match (higher is better)
                    score = 0
                    
                    # Exact artifact ID match gets highest score
                    if spring_artifact_id.lower() in spring_pattern.lower():
                        score += 100
                    
                    # Avoid test dependencies unless it's actually a test dependency
                    if 'test' in helidon_pattern.lower() and 'test' not in spring_artifact_id.lower():
                        score -= 50  # Penalize test dependencies for non-test artifacts
                    
                    # Prefer main dependencies
                    if 'helidon-microprofile' in helidon_pattern and 'test' not in helidon_pattern:
                        score += 20
                    
                    if score > best_score:
                        best_score = score
                        best_match = result
                
                # Use best match if found
                if best_match and best_score > 0:
                    metadata = best_match.get('metadata', {})
                    helidon_pattern = metadata.get('helidon_pattern', '')
                    candidate = self._parse_dependency_pattern(helidon_pattern, helidon_version)
                    if candidate and self._is_valid_helidon_dependency_candidate(
                        spring_artifact_id,
                        candidate,
                        dependency_scope,
                    ):
                        return candidate
                
                # Fallback: use first compatible result if no good match
                for result in results:
                    metadata = result.get('metadata', {})
                    if metadata.get('migration_type') != 'dependency':
                        continue
                    if self._is_version_compatible(metadata.get('helidon_version', ''), helidon_version):
                        helidon_pattern = metadata.get('helidon_pattern', '')
                        candidate = self._parse_dependency_pattern(helidon_pattern, helidon_version)
                        if candidate and self._is_valid_helidon_dependency_candidate(
                            spring_artifact_id,
                            candidate,
                            dependency_scope,
                        ):
                            return candidate
            
            # Fallback to LLM if RAG doesn't find a match
            llm_candidate = self._llm_fallback_dependency(spring_artifact_id, helidon_version)
            if self._is_valid_helidon_dependency_candidate(
                spring_artifact_id,
                llm_candidate,
                dependency_scope,
            ):
                return llm_candidate
            return None
            
        except Exception as e:
            logger.error(f"Error finding Helidon dependency: {str(e)}")
            return None

    def _deterministic_dependency_mapping(
        self,
        spring_artifact_id: str,
        dependency_scope: Optional[str],
        helidon_version: str,
    ) -> Optional[Dict]:
        """Return curated production-safe mappings for high-volume Spring dependencies."""
        artifact = (spring_artifact_id or '').strip().lower()
        scope = (dependency_scope or '').strip().lower()

        if artifact in {'spring-boot-starter-test', 'spring-boot-test', 'spring-boot-test-autoconfigure'}:
            return {
                'groupId': 'io.helidon.microprofile.testing',
                'artifactId': 'helidon-microprofile-testing-junit5',
                'version': '${helidon.version}',
                'scope': 'test',
            }

        runtime_starters = {
            'spring-boot-starter',
            'spring-boot-starter-actuator',
            'spring-boot-starter-aop',
            'spring-boot-starter-data-jpa',
            'spring-boot-starter-jdbc',
            'spring-boot-starter-validation',
            'spring-boot-starter-web',
            'spring-boot-starter-webflux',
            'spring-cloud-gateway-mvc',
            'spring-cloud-starter-gateway',
        }
        if artifact in runtime_starters:
            return {
                'groupId': 'io.helidon.microprofile.bundles',
                'artifactId': 'helidon-microprofile',
                'version': '${helidon.version}',
            }

        if scope == 'test':
            return {
                'groupId': 'io.helidon.microprofile.testing',
                'artifactId': 'helidon-microprofile-testing-junit5',
                'version': '${helidon.version}',
                'scope': 'test',
            }

        return None

    def _should_remove_spring_dependency(self, spring_artifact_id: str) -> bool:
        """Identify Spring helper/BOM artifacts that should be dropped instead of remapped."""
        artifact = (spring_artifact_id or '').strip().lower()
        return artifact in {
            'spring-boot-properties-migrator',
            'spring-cloud-gateway-dependencies',
        }

    def _parse_dependency_pattern(self, helidon_pattern: str, helidon_version: str) -> Optional[Dict]:
        """Parse a groupId:artifactId[:version] pattern into a dependency dict."""
        if ':' not in (helidon_pattern or ''):
            return None
        parts = helidon_pattern.split(':')
        if len(parts) < 2:
            return None
        return {
            'groupId': parts[0],
            'artifactId': parts[1],
            'version': parts[2] if len(parts) > 2 and parts[2] else helidon_version,
        }

    def _is_valid_helidon_dependency_candidate(
        self,
        spring_artifact_id: str,
        candidate: Optional[Dict],
        dependency_scope: Optional[str],
    ) -> bool:
        """Reject obviously unsafe dependency mappings for production migration."""
        if not candidate:
            return False

        scope = (dependency_scope or '').strip().lower()
        is_test_dependency = scope == 'test' or 'test' in (spring_artifact_id or '').lower()
        candidate_artifact = (candidate.get('artifactId') or '').lower()
        candidate_group = (candidate.get('groupId') or '').lower()

        if not is_test_dependency and 'test' in candidate_artifact:
            return False

        if not is_test_dependency and candidate.get('type') == 'pom':
            return False

        if not candidate_group.startswith('io.helidon') and not candidate_group.startswith('jakarta'):
            return False

        return True
    
    def _llm_fallback_dependency(self, spring_artifact_id: str, helidon_version: str = '4.0.0') -> Optional[Dict]:
        """Use LLM to find dependency mapping when RAG fails"""
        try:
            prompt = f"""Find the Helidon MP {helidon_version} equivalent dependency for Spring Boot dependency: {spring_artifact_id}

Return the response in format: groupId:artifactId:version
Example: io.helidon.microprofile.bundles:helidon-microprofile:{helidon_version}

Important: Use Helidon version {helidon_version} in the response."""
            
            response = self.llm_provider.generate(prompt)
            
            # Parse response
            if ':' in response:
                parts = response.strip().split(':')
                if len(parts) >= 2:
                    return {
                        'groupId': parts[0],
                        'artifactId': parts[1],
                        'version': parts[2] if len(parts) > 2 else helidon_version
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"LLM fallback failed: {str(e)}")
            return None
    
    def _update_java_version(self, root, ns):
        """Update Java version in POM based on Helidon requirements
        Defaults to production JDK (LTS) for stability"""
        helidon_version = getattr(self.settings, 'helidon_version', '4.0.0')
        # Use production JDK (LTS) by default for stability
        # Users can override if they need performance JDK
        production_jdk = VersionCompatibility.get_production_jdk(helidon_version)
        required_jdk = VersionCompatibility.get_required_jdk(helidon_version)
        performance_jdk = VersionCompatibility.get_recommended_jdk(helidon_version)
        
        # Default to production JDK (LTS) - safer for production
        jdk_to_use = production_jdk
        
        # Update properties section
        properties = root.find('maven:properties', ns)
        if properties is None:
            properties = ET.SubElement(root, '{http://maven.apache.org/POM/4.0.0}properties')
        
        # Set Java version
        java_source_elem = properties.find('maven:maven.compiler.source', ns)
        if java_source_elem is None:
            java_source_elem = ET.SubElement(properties, '{http://maven.apache.org/POM/4.0.0}maven.compiler.source')
        java_source_elem.text = jdk_to_use
        
        java_target_elem = properties.find('maven:maven.compiler.target', ns)
        if java_target_elem is None:
            java_target_elem = ET.SubElement(properties, '{http://maven.apache.org/POM/4.0.0}maven.compiler.target')
        java_target_elem.text = jdk_to_use
        
        jdk_message = f"Updated Java version to {jdk_to_use} (LTS - recommended for production with Helidon {helidon_version})"
        if performance_jdk and performance_jdk != jdk_to_use:
            jdk_message += f". Note: Java {performance_jdk} available for performance-critical applications"
        logger.info(jdk_message)
    
    def _update_maven_compiler_plugin(self, root, ns):
        """Update Maven compiler plugin with correct Java version"""
        helidon_version = getattr(self.settings, 'helidon_version', '4.0.0')
        # Use production JDK (LTS) by default for stability
        jdk_to_use = VersionCompatibility.get_production_jdk(helidon_version)
        
        # Find or create build section
        build = root.find('maven:build', ns)
        if build is None:
            build = ET.SubElement(root, '{http://maven.apache.org/POM/4.0.0}build')
        
        # Find or create plugins section
        plugins = build.find('maven:plugins', ns)
        if plugins is None:
            plugins = ET.SubElement(build, '{http://maven.apache.org/POM/4.0.0}plugins')
        
        # Find compiler plugin
        compiler_plugin = None
        for plugin in plugins.findall('maven:plugin', ns):
            artifact_id = plugin.find('maven:artifactId', ns)
            if artifact_id is not None and artifact_id.text == 'maven-compiler-plugin':
                compiler_plugin = plugin
                break
        
        # Create compiler plugin if not found
        if compiler_plugin is None:
            compiler_plugin = ET.SubElement(plugins, '{http://maven.apache.org/POM/4.0.0}plugin')
            
            group_id = ET.SubElement(compiler_plugin, '{http://maven.apache.org/POM/4.0.0}groupId')
            group_id.text = 'org.apache.maven.plugins'
            
            artifact_id = ET.SubElement(compiler_plugin, '{http://maven.apache.org/POM/4.0.0}artifactId')
            artifact_id.text = 'maven-compiler-plugin'
            
            version = ET.SubElement(compiler_plugin, '{http://maven.apache.org/POM/4.0.0}version')
            version.text = '3.11.0'
        
        # Update configuration
        configuration = compiler_plugin.find('maven:configuration', ns)
        if configuration is None:
            configuration = ET.SubElement(compiler_plugin, '{http://maven.apache.org/POM/4.0.0}configuration')
        
        source = configuration.find('maven:source', ns)
        if source is None:
            source = ET.SubElement(configuration, '{http://maven.apache.org/POM/4.0.0}source')
        source.text = jdk_to_use
        
        target = configuration.find('maven:target', ns)
        if target is None:
            target = ET.SubElement(configuration, '{http://maven.apache.org/POM/4.0.0}target')
        target.text = jdk_to_use

        if self._has_dependency(root, ns, 'org.projectlombok', 'lombok'):
            annotation_processor_paths = configuration.find('maven:annotationProcessorPaths', ns)
            if annotation_processor_paths is None:
                annotation_processor_paths = ET.SubElement(configuration, '{http://maven.apache.org/POM/4.0.0}annotationProcessorPaths')

            lombok_path = None
            for path in annotation_processor_paths.findall('maven:path', ns):
                group_id = path.find('maven:groupId', ns)
                artifact_id = path.find('maven:artifactId', ns)
                if group_id is not None and artifact_id is not None and group_id.text == 'org.projectlombok' and artifact_id.text == 'lombok':
                    lombok_path = path
                    break

            if lombok_path is None:
                lombok_path = ET.SubElement(annotation_processor_paths, '{http://maven.apache.org/POM/4.0.0}path')
                group_id = ET.SubElement(lombok_path, '{http://maven.apache.org/POM/4.0.0}groupId')
                group_id.text = 'org.projectlombok'
                artifact_id = ET.SubElement(lombok_path, '{http://maven.apache.org/POM/4.0.0}artifactId')
                artifact_id.text = 'lombok'
                version = ET.SubElement(lombok_path, '{http://maven.apache.org/POM/4.0.0}version')
                version.text = LOMBOK_VERSION
            else:
                version = lombok_path.find('maven:version', ns)
                if version is None:
                    version = ET.SubElement(lombok_path, '{http://maven.apache.org/POM/4.0.0}version')
                version.text = LOMBOK_VERSION
            logger.info(f"Configured Lombok annotation processor path {LOMBOK_VERSION}")
        
        logger.info(f"Updated Maven compiler plugin to use Java {jdk_to_use}")

    def _has_dependency(self, root, ns, group_id_text: str, artifact_id_text: str) -> bool:
        deps_container = root.find('maven:dependencies', ns)
        if deps_container is None:
            return False
        for dep in deps_container.findall('maven:dependency', ns):
            group_id = dep.find('maven:groupId', ns)
            artifact_id = dep.find('maven:artifactId', ns)
            if group_id is not None and artifact_id is not None:
                if (group_id.text or '').strip() == group_id_text and (artifact_id.text or '').strip() == artifact_id_text:
                    return True
        return False

    def _ensure_helidon_version_property(self, root, ns):
        """Ensure helidon.version property is set for visibility"""
        helidon_version = getattr(self.settings, 'helidon_version', '4.0.0')
        properties = root.find('maven:properties', ns)
        if properties is None:
            properties = ET.SubElement(root, '{http://maven.apache.org/POM/4.0.0}properties')

        helidon_prop = properties.find('maven:helidon.version', ns)
        if helidon_prop is None:
            helidon_prop = ET.SubElement(properties, '{http://maven.apache.org/POM/4.0.0}helidon.version')
        helidon_prop.text = helidon_version

    def _ensure_helidon_dependency_versions(self, root, ns):
        """Ensure all Helidon dependencies resolve without relying on a synthetic parent."""
        deps_container = root.find('maven:dependencies', ns)
        if deps_container is None:
            return

        for dep in deps_container.findall('maven:dependency', ns):
            group_id_elem = dep.find('maven:groupId', ns)
            artifact_id_elem = dep.find('maven:artifactId', ns)
            if group_id_elem is None or artifact_id_elem is None:
                continue

            group_id = (group_id_elem.text or '').strip()
            if not group_id.startswith('io.helidon.'):
                continue

            version_elem = dep.find('maven:version', ns)
            if version_elem is None:
                version_elem = ET.SubElement(dep, '{http://maven.apache.org/POM/4.0.0}version')
            if not (version_elem.text or '').strip():
                version_elem.text = '${helidon.version}'
            elif (version_elem.text or '').strip() == getattr(self.settings, 'helidon_version', '4.0.0'):
                version_elem.text = '${helidon.version}'

        logger.info("Ensured explicit Helidon dependency versions via ${helidon.version}")

    def _ensure_maven_central_repository(self, root, ns):
        """Ensure the generated POM can resolve public Helidon artifacts."""
        repositories = root.find('maven:repositories', ns)
        if repositories is None:
            repositories = ET.SubElement(root, '{http://maven.apache.org/POM/4.0.0}repositories')

        for repo in repositories.findall('maven:repository', ns):
            url = repo.find('maven:url', ns)
            if url is not None and 'repo.maven.apache.org/maven2' in (url.text or ''):
                return

        repository = ET.SubElement(repositories, '{http://maven.apache.org/POM/4.0.0}repository')
        repo_id = ET.SubElement(repository, '{http://maven.apache.org/POM/4.0.0}id')
        repo_id.text = 'maven-central'
        name = ET.SubElement(repository, '{http://maven.apache.org/POM/4.0.0}name')
        name.text = 'Maven Central'
        url = ET.SubElement(repository, '{http://maven.apache.org/POM/4.0.0}url')
        url.text = 'https://repo.maven.apache.org/maven2'
        logger.info("Added Maven Central repository for Helidon artifact resolution")
    
    def _remove_spring_references(self, root, ns):
        """Remove all Spring references from POM metadata"""
        # Remove Spring from name
        name_elem = root.find('maven:name', ns)
        if name_elem is not None:
            name_text = name_elem.text or ''
            # Remove "Spring Boot" or "Spring" from name
            name_text = name_text.replace('Spring Boot', '').replace('Spring', '').strip()
            if name_text:
                name_elem.text = name_text
            else:
                # Remove name element if empty
                root.remove(name_elem)
                logger.info("Removed Spring reference from POM name")
        
        # Remove Spring from description
        desc_elem = root.find('maven:description', ns)
        if desc_elem is not None:
            desc_text = desc_elem.text or ''
            # Remove "Spring Boot" or "Spring" from description
            desc_text = desc_text.replace('Spring Boot', 'Helidon MP').replace('Spring', 'Helidon').strip()
            if desc_text:
                desc_elem.text = desc_text
            else:
                # Update to generic description
                desc_elem.text = 'Helidon MP application'
        
        # Remove java.version property (use maven.compiler.source/target instead)
        properties = root.find('maven:properties', ns)
        if properties is not None:
            java_version_elem = properties.find('maven:java.version', ns)
            if java_version_elem is not None:
                properties.remove(java_version_elem)
                logger.info("Removed java.version property (using maven.compiler.source/target instead)")
        
        logger.info("Removed all Spring references from POM")
    
    def _is_spring_dependency(self, dep, ns) -> bool:
        """Check if a dependency is a Spring Boot dependency"""
        group_id_elem = dep.find('maven:groupId', ns)
        artifact_id_elem = dep.find('maven:artifactId', ns)
        
        if group_id_elem is None or artifact_id_elem is None:
            return False
        
        group_id = group_id_elem.text or ''
        artifact_id = artifact_id_elem.text or ''
        
        return (
            artifact_id.startswith('spring-')
            or 'spring-boot' in artifact_id
            or group_id.startswith('org.springframework')
            or 'springframework' in group_id
        )

    def _is_inhouse_dependency(self, group_id: Optional[str]) -> bool:
        """Identify organization-owned dependencies whose exclusions should be preserved."""
        normalized = (group_id or '').strip()
        return normalized.startswith('com.oracle.')
    
    def _write_clean_xml(self, tree: ET.ElementTree, output_path: Path):
        """Write XML with stable Maven namespaces and readable indentation."""
        ET.register_namespace('', 'http://maven.apache.org/POM/4.0.0')
        ET.register_namespace('xsi', 'http://www.w3.org/2001/XMLSchema-instance')

        try:
            ET.indent(tree, space='    ')
        except AttributeError:
            self._indent_xml(tree.getroot())

        tree.write(output_path, encoding='UTF-8', xml_declaration=True)

    def _indent_xml(self, elem, level: int = 0):
        """Compatibility pretty-printer for Python versions without ET.indent."""
        indent = "\n" + ("    " * level)
        child_indent = "\n" + ("    " * (level + 1))

        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = child_indent
            for child in elem:
                self._indent_xml(child, level + 1)
                if not child.tail or not child.tail.strip():
                    child.tail = child_indent
            if not elem[-1].tail or not elem[-1].tail.strip():
                elem[-1].tail = indent
        elif level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent
    
    def _is_version_compatible(self, pattern_version: str, target_version: str) -> bool:
        """
        Check if pattern version is compatible with target version
        Handles both exact versions (e.g., "4.3.2") and version ranges (e.g., "4.0.0-4.3.2")
        """
        # Exact match
        if pattern_version == target_version:
            return True
        
        # Check if pattern_version is a range (e.g., "4.0.0-4.3.2")
        if '-' in pattern_version:
            try:
                min_version, max_version = pattern_version.split('-')
                # Check if target_version is within range
                if self._is_version_in_range(target_version, min_version, max_version):
                    return True
            except:
                pass
        
        # Extract major.minor versions for compatibility check
        try:
            pattern_parts = pattern_version.split('.')
            target_parts = target_version.split('.')
            
            # Same major.minor is compatible (e.g., 4.0.x, 4.1.x, 4.2.x, 4.3.x)
            if pattern_parts[0] == target_parts[0] and pattern_parts[1] == target_parts[1]:
                return True
            
            # Same major version might be compatible
            if pattern_parts[0] == target_parts[0]:
                return True
        except:
            pass
        
        return False
    
    def _is_version_in_range(self, version: str, min_version: str, max_version: str) -> bool:
        """Check if version is within min-max range"""
        try:
            version_parts = [int(x) for x in version.split('.')]
            min_parts = [int(x) for x in min_version.split('.')]
            max_parts = [int(x) for x in max_version.split('.')]
            
            # Compare version components
            for i in range(max(len(version_parts), len(min_parts), len(max_parts))):
                v = version_parts[i] if i < len(version_parts) else 0
                min_v = min_parts[i] if i < len(min_parts) else 0
                max_v = max_parts[i] if i < len(max_parts) else 0
                
                if v < min_v:
                    return False
                if v > max_v:
                    return False
                if v > min_v and v < max_v:
                    return True
            
            # Check exact boundaries
            return (version >= min_version and version <= max_version)
        except:
            return False
