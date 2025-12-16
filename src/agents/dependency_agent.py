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
                
            # Add Helidon parent
            self._add_helidon_parent(root, ns)

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
                    # Migrate Spring dependency
                    helidon_dep = self._find_helidon_dependency(artifact_id)
                    
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
                        if artifact_id is not None and 'spring-boot-maven-plugin' in artifact_id.text:
                            plugins.remove(plugin)
                            logger.info("Removed Spring Boot Maven plugin")
            
            # Remove Spring references from POM metadata
            self._remove_spring_references(root, ns)
            
            # Update Java version based on Helidon requirements
            try:
                self._update_java_version(root, ns)
            except Exception as e:
                logger.error(f"Error updating Java version: {str(e)}")
            
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
    
    def _find_helidon_dependency(self, spring_artifact_id: str) -> Optional[Dict]:
        """
        Find Helidon MP equivalent for Spring Boot dependency using RAG
        
        Args:
            spring_artifact_id: Spring Boot artifact ID
            
        Returns:
            Dictionary with groupId, artifactId, and version, or None
        """
        try:
            helidon_version = getattr(self.settings, 'helidon_version', '4.0.0')
            
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
                    
                    # Parse groupId:artifactId format
                    if ':' in helidon_pattern:
                        parts = helidon_pattern.split(':')
                        if len(parts) >= 2:
                            return {
                                'groupId': parts[0],
                                'artifactId': parts[1],
                                'version': helidon_version  # Use user-specified version
                            }
                
                # Fallback: use first compatible result if no good match
                for result in results:
                    metadata = result.get('metadata', {})
                    if metadata.get('migration_type') != 'dependency':
                        continue
                    if self._is_version_compatible(metadata.get('helidon_version', ''), helidon_version):
                        helidon_pattern = metadata.get('helidon_pattern', '')
                        if ':' in helidon_pattern:
                            parts = helidon_pattern.split(':')
                            if len(parts) >= 2:
                                return {
                                    'groupId': parts[0],
                                    'artifactId': parts[1],
                                    'version': helidon_version
                                }
            
            # Fallback to LLM if RAG doesn't find a match
            return self._llm_fallback_dependency(spring_artifact_id, helidon_version)
            
        except Exception as e:
            logger.error(f"Error finding Helidon dependency: {str(e)}")
            return None
    
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
        
        logger.info(f"Updated Maven compiler plugin to use Java {jdk_to_use}")
    
    def _add_helidon_parent(self, root, ns):
        """Add Helidon parent POM if not present"""
        helidon_version = getattr(self.settings, 'helidon_version', '4.0.0')
        
        # Check if parent already exists
        parent = root.find('maven:parent', ns)
        if parent is not None:
            artifact_id = parent.find('maven:artifactId', ns)
            if artifact_id is not None and 'helidon' in artifact_id.text.lower():
                logger.info("Helidon parent POM already present")
                return
        
        # Add Helidon parent
        parent = ET.SubElement(root, '{http://maven.apache.org/POM/4.0.0}parent')
        
        group_id = ET.SubElement(parent, '{http://maven.apache.org/POM/4.0.0}groupId')
        group_id.text = 'io.helidon.microprofile.bundles'
        
        artifact_id = ET.SubElement(parent, '{http://maven.apache.org/POM/4.0.0}artifactId')
        artifact_id.text = 'helidon-microprofile-parent'
        
        version = ET.SubElement(parent, '{http://maven.apache.org/POM/4.0.0}version')
        version.text = helidon_version
        
        relative_path = ET.SubElement(parent, '{http://maven.apache.org/POM/4.0.0}relativePath')
        relative_path.text = ''
        
        logger.info(f"Added Helidon parent POM version {helidon_version}")
    
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
        
        return 'spring-boot' in artifact_id or 'springframework' in group_id
    
    def _write_clean_xml(self, tree: ET.ElementTree, output_path: Path):
        """Write XML without namespace prefixes (clean format)"""
        import xml.dom.minidom
        
        # Get root element
        root = tree.getroot()
        
        # Remove namespace prefixes from all elements
        for elem in root.iter():
            # Remove namespace prefix from tag
            if '}' in elem.tag:
                elem.tag = elem.tag.split('}')[1]
        
        # Write to string first
        xml_str = ET.tostring(root, encoding='unicode')
        
        # Parse with minidom for pretty printing
        dom = xml.dom.minidom.parseString(xml_str)
        
        # Write with proper formatting
        with open(output_path, 'w', encoding='utf-8') as f:
            # Add XML declaration and default namespace
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<project xmlns="http://maven.apache.org/POM/4.0.0"\n')
            f.write('         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n')
            f.write('         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 ')
            f.write('http://maven.apache.org/xsd/maven-4.0.0.xsd">\n')
            
            # Get children of root element
            for child in root:
                # Convert child to string and format
                child_str = ET.tostring(child, encoding='unicode')
                child_dom = xml.dom.minidom.parseString(f'<root>{child_str}</root>')
                child_xml = child_dom.documentElement.firstChild.toxml() if child_dom.documentElement.firstChild else ''
                
                # Add proper indentation (4 spaces)
                lines = child_xml.split('\n')
                for line in lines:
                    if line.strip():
                        f.write('    ' + line + '\n')
            
            f.write('</project>\n')
    
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

