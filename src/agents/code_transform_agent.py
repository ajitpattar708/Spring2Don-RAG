"""
Code Transform Agent
Transforms Java source code from Spring Boot to Helidon MP
"""

from pathlib import Path
from typing import Dict, List
import re
import sys
import time
import json
import uuid
from datetime import datetime
from src.config.settings import Settings
from src.rag.knowledge_base import KnowledgeBase
from src.rag.embeddings import EmbeddingModel
from src.rag.llm_provider import LLMProviderFactory
from src.utils.logger import color_text, setup_logger

logger = setup_logger(__name__)


class CodeTransformAgent:
    """Transforms Java code from Spring Boot to Helidon MP"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.knowledge_base = KnowledgeBase(settings)
        self.embedding_model = EmbeddingModel(settings)
        self.llm_provider = LLMProviderFactory.create(settings)
        self._last_transform_profile = {}
        self.fallback_stats = {
            'embedding_failures': 0,
            'rag_failures': 0,
            'llm_failures': 0,
            'llm_validation_failures': 0,
            'regex_fallbacks': 0
        }
        
    def migrate(self, project_structure: Dict, source_path: Path = None, target_path: Path = None) -> Dict:
        """
        Migrate Java source files
        
        Args:
            project_structure: Project structure analysis result
            
        Returns:
            Migration result dictionary
        """
        logger.info("Starting code transformation...")
        
        java_files = project_structure.get('java_files', [])
        if not java_files:
            logger.warning("No Java files found")
            return {'success': False, 'error': 'No Java files found'}
        
        # Store paths for file migration
        if source_path:
            self.source_path = source_path
        if target_path:
            self.target_path = target_path
        
        migrated_files = []
        transformations_applied = 0
        total_files = len(java_files)
        
        print(color_text(f"   Found {total_files} Java file(s) to migrate", "info"))
        sys.stdout.flush()
        
        for idx, java_file in enumerate(java_files, 1):
            file_start_time = time.time()
            file_name = java_file.name
            file_path = str(java_file.relative_to(self.target_path) if hasattr(self, 'target_path') else java_file)
            
            try:
                print(color_text(f"   [{idx}/{total_files}] Migrating: {file_name}...", "info"), end=' ', flush=True)
                sys.stdout.flush()
                
                result = self._migrate_file(java_file)
                file_time = time.time() - file_start_time
                
                if result['success']:
                    migrated_files.append(str(java_file))
                    transformations = result.get('transformations', 0)
                    transformations_applied += transformations
                    print(color_text(f"[OK] ({file_time:.1f}s, {transformations} transformations)", "ok"))
                else:
                    error = result.get('error', 'Unknown error')
                    print(color_text(f"[FAIL] ({file_time:.1f}s)", "error"))
                    print(color_text(f"      Error: {error}", "error"))
                    logger.error(f"Error migrating {java_file}: {error}")
                    
            except Exception as e:
                file_time = time.time() - file_start_time
                print(color_text(f"[EXCEPTION] ({file_time:.1f}s)", "error"))
                print(color_text(f"      Exception: {type(e).__name__}: {str(e)}", "error"))
                logger.error(f"Exception migrating {java_file}: {str(e)}", exc_info=True)
        
        return {
            'success': True,
            'files_migrated': len(migrated_files),
            'transformations_applied': transformations_applied,
            'fallback_stats': self.fallback_stats
        }
    
    def _migrate_file(self, java_file: Path) -> Dict:
        """
        Migrate a single Java file
        
        Args:
            java_file: Path to Java source file
            
        Returns:
            Migration result for this file
        """
        try:
            # Read source file
            with open(java_file, 'r', encoding='utf-8') as f:
                source_code = f.read()
            
            # Transform code
            transform_start = time.time()
            transformed_code, transformations = self._transform_code(source_code)
            transform_time = time.time() - transform_start
            if transform_time >= 5.0:
                logger.warning(
                    "Slow migration step for %s took %.1fs (%s)",
                    java_file.name,
                    transform_time,
                    self._format_transform_profile(),
                )
            
            # Write transformed code to target location
            if hasattr(self, 'source_path') and hasattr(self, 'target_path'):
                # Calculate relative path from source
                try:
                    relative_path = java_file.relative_to(self.source_path)
                    target_file = self.target_path / relative_path
                except ValueError:
                    # If not relative, use same structure
                    target_file = self.target_path / java_file.name
                
                # Ensure target directory exists
                target_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(target_file, 'w', encoding='utf-8') as f:
                    f.write(transformed_code)
                
                logger.debug(f"Wrote migrated file: {target_file}")
            
            return {
                'success': True,
                'transformations': transformations
            }
            
        except Exception as e:
            logger.error(f"Error migrating file {java_file}: {str(e)}")
            return {'success': False, 'error': str(e), 'transformations': 0}
    
    def _transform_code(self, source_code: str) -> tuple[str, int]:
        """
        Transform Spring Boot code to Helidon MP using Agentic RAG
        
        WORKFLOW:
        1. Search Vector DB for similar patterns
        2. If high similarity (>0.9): Use pattern directly (FAST PATH)
        3. If medium similarity (0.7-0.9): Use pattern as context for LLM
        4. If low/no similarity (<0.7): Use LLM with general knowledge
        5. Post-process: Fix javax->jakarta, clean up code
        """
        try:
            self._last_transform_profile = {'path': 'start', 'stages': {}}
            # 1. Retrieve Context (RAG)
            # Search for relevant patterns based on the code content
            try:
                embedding_start = time.time()
                embedding = self.embedding_model.encode_single(source_code[:1000]) # Embed first 1000 chars context
                self._record_transform_stage('embedding', time.time() - embedding_start)
            except Exception as e:
                logger.warning(f"Embedding generation failed, using fallback: {str(e)}")
                self.fallback_stats['embedding_failures'] += 1
                self.fallback_stats['regex_fallbacks'] += 1
                self._last_transform_profile['path'] = 'fallback_embedding_failure'
                # Fallback to regex transformation if embedding fails
                return self._fallback_regex_transform(source_code)
            
            # Search in code patterns and annotations
            try:
                search_start = time.time()
                code_results = self.knowledge_base.search('code_patterns', query_embedding=embedding, top_k=3)
                anno_results = self.knowledge_base.search('annotations', query_embedding=embedding, top_k=5)
                self._record_transform_stage('rag_search', time.time() - search_start)
            except Exception as e:
                logger.warning(f"Knowledge base search failed, using fallback: {str(e)}")
                self.fallback_stats['rag_failures'] += 1
                self.fallback_stats['regex_fallbacks'] += 1
                self._last_transform_profile['path'] = 'fallback_rag_failure'
                # Fallback to regex transformation if RAG search fails
                return self._fallback_regex_transform(source_code)
            
            all_results = code_results + anno_results
            best_match = None
            best_similarity = 0.0
            
            # Find best matching pattern
            for res in all_results:
                if res.get('similarity', 0) > best_similarity:
                    best_similarity = res.get('similarity', 0)
                    best_match = res
            
            # FAST PATH: If we have a very high similarity match (>0.9), use regex transform with vector DB mappings
            if best_match and best_similarity > 0.9:
                logger.info(f"Using direct pattern match (similarity: {best_similarity:.2f})")
                self._last_transform_profile['path'] = 'direct_pattern_match'
                self._last_transform_profile['similarity'] = round(best_similarity, 4)
                # Use regex transform which now uses vector DB for all mappings
                regex_start = time.time()
                migrated_code, _ = self._fallback_regex_transform(source_code)
                self._record_transform_stage('regex_transform', time.time() - regex_start)
                post_process_start = time.time()
                migrated_code = self._post_process_jakarta(migrated_code)
                self._record_transform_stage('post_process_jakarta', time.time() - post_process_start)
                if self._needs_llm_spring_api_remediation(migrated_code):
                    remediation_start = time.time()
                    migrated_code = self._llm_remediate_spring_apis(migrated_code)
                    self._record_transform_stage('llm_remediation', time.time() - remediation_start)
                return migrated_code, 1
            
            # MEDIUM PATH: Use patterns as context for LLM (similarity 0.7-0.9)
            context_examples = []
            for res in all_results:
                if res['similarity'] > 0.7: # Only relevant matches
                    text = res['text']
                    context_examples.append(f"--- Example Pattern ---\n{text}\n")
            
            context_str = "\n".join(context_examples) if context_examples else "No similar patterns found."
            self._last_transform_profile['path'] = 'llm_primary'
            self._last_transform_profile['similarity'] = round(best_similarity, 4)
            
            # 2. Construct Optimized Prompt for LLM (shorter, more focused)
            helidon_version = self.settings.helidon_version or "4.3.2"
            prompt = f"""Migrate Spring Boot to Helidon MP {helidon_version}. Return ONLY Java code.

RULES:
- Use jakarta.* imports (NOT javax.*)
- @RestController → @Path + @ApplicationScoped
- @Autowired → @Inject
- ResponseEntity → Response
- Keep business logic identical

{'PATTERNS:' + context_str if context_examples else ''}

SOURCE:
```java
{source_code}
```

MIGRATED CODE:"""
            
            # 3. Call LLM only if needed
            logger.info("Generating code via LLM...")
            try:
                llm_start = time.time()
                migrated_code = self.llm_provider.generate(prompt)
                self._record_transform_stage('llm_generate', time.time() - llm_start)
            except Exception as e:
                logger.warning(f"LLM generation failed: {str(e)}, using fallback")
                self.fallback_stats['llm_failures'] += 1
                self.fallback_stats['regex_fallbacks'] += 1
                self._last_transform_profile['path'] = 'fallback_llm_failure'
                return self._fallback_regex_transform(source_code)
            
            # 4. Cleanup response
            if migrated_code:
                match = re.search(r'```java\n(.*?)\n```', migrated_code, re.DOTALL)
                if match:
                    migrated_code = match.group(1)
                elif migrated_code.strip().startswith("```"):
                    migrated_code = migrated_code.strip().strip("`")
                    if migrated_code.startswith("java"):
                        migrated_code = migrated_code[4:].strip()
                
                # Validate migrated code is not empty
                if self._validate_llm_output(migrated_code, source_code):
                    # Post-process: Fix javax->jakarta
                    post_process_start = time.time()
                    migrated_code = self._post_process_jakarta(migrated_code)
                    self._record_transform_stage('post_process_jakarta', time.time() - post_process_start)

                    # LLM remediation pass for any remaining Spring-only APIs
                    if self._needs_llm_spring_api_remediation(migrated_code):
                        remediation_start = time.time()
                        migrated_code = self._llm_remediate_spring_apis(migrated_code)
                        self._record_transform_stage('llm_remediation', time.time() - remediation_start)
                    
                    # ENVIRONMENT LEARNING: Save new pattern if LLM generated it (no high similarity match)
                    if best_similarity < 0.9:
                        save_start = time.time()
                        self._save_new_pattern(source_code, migrated_code)
                        self._record_transform_stage('save_pattern', time.time() - save_start)
                    
                    return migrated_code, 1
                else:
                    logger.warning("LLM returned empty or invalid code, using fallback")
                    self.fallback_stats['llm_validation_failures'] += 1
                    self.fallback_stats['regex_fallbacks'] += 1
                    self._last_transform_profile['path'] = 'fallback_llm_validation'
                    return self._fallback_regex_transform(source_code)
            else:
                logger.warning("LLM returned None, using fallback")
                self.fallback_stats['llm_validation_failures'] += 1
                self.fallback_stats['regex_fallbacks'] += 1
                self._last_transform_profile['path'] = 'fallback_llm_empty'
                return self._fallback_regex_transform(source_code)
            
        except Exception as e:
            logger.error(f"LLM migration failed: {e}", exc_info=True)
            # Fallback to regex transformation if LLM fails
            logger.info("Falling back to regex transformation...")
            self.fallback_stats['llm_failures'] += 1
            self.fallback_stats['regex_fallbacks'] += 1
            self._last_transform_profile['path'] = 'fallback_exception'
            fallback_code, fallback_count = self._fallback_regex_transform(source_code)
            if self._needs_llm_spring_api_remediation(fallback_code):
                remediation_start = time.time()
                fallback_code = self._llm_remediate_spring_apis(fallback_code)
                self._record_transform_stage('llm_remediation', time.time() - remediation_start)
            return fallback_code, fallback_count

    def _record_transform_stage(self, stage_name: str, duration_seconds: float) -> None:
        """Record per-stage timing so slow migrations can be diagnosed from logs."""
        self._last_transform_profile.setdefault('stages', {})[stage_name] = round(duration_seconds, 3)

    def _format_transform_profile(self) -> str:
        """Render the latest transform profile into a compact log string."""
        if not self._last_transform_profile:
            return 'no transform profile captured'

        path_name = self._last_transform_profile.get('path', 'unknown')
        similarity = self._last_transform_profile.get('similarity')
        stages = self._last_transform_profile.get('stages', {})
        stage_parts = [f"{name}={duration:.3f}s" for name, duration in stages.items()]

        profile_parts = [f"path={path_name}"]
        if similarity is not None:
            profile_parts.append(f"similarity={similarity:.2f}")
        if stage_parts:
            profile_parts.append(", ".join(stage_parts))

        return "; ".join(profile_parts)

    def _needs_llm_spring_api_remediation(self, code: str) -> bool:
        """Only invoke slow LLM remediation when deterministic passes left real Spring APIs behind."""
        spring_marker_patterns = [
            r'\bimplements\s+ResponseErrorHandler\b',
            r'\bResponseErrorHandler\b',
            r'\bClientHttpResponse\b',
            r'\bRestTemplateBuilder\b',
            r'\bProxyProperties\b',
            r'import\s+org\.springframework\.',
            r'\bHttpStatus\.',
            r'\bHttpMethod\.',
        ]
        return any(re.search(pattern, code) for pattern in spring_marker_patterns)

    def _llm_remediate_spring_apis(self, code: str) -> str:
        """LLM remediation pass to replace remaining Spring-only APIs with Helidon/JAX-RS equivalents."""
        if not self._needs_llm_spring_api_remediation(code):
            return code

        helidon_version = self.settings.helidon_version or "4.3.2"
        prompt = f"""You are migrating Spring Boot code to Helidon MP {helidon_version}.
Rewrite the code to remove any remaining Spring-only APIs (ResponseErrorHandler, RestTemplateBuilder,
ProxyProperties, ClientHttpResponse, HttpStatus, HttpHeaders, HttpMethod). Use JAX-RS ClientResponseFilter
or Helidon-compatible alternatives. Return ONLY valid Java code with no Spring imports.

SOURCE:
```java
{code}
```

MIGRATED CODE:"""

        try:
            remediated = self.llm_provider.generate(prompt)
            if remediated:
                match = re.search(r'```java\n(.*?)\n```', remediated, re.DOTALL)
                if match:
                    remediated = match.group(1)
                elif remediated.strip().startswith("```"):
                    remediated = remediated.strip().strip("`")
                    if remediated.startswith("java"):
                        remediated = remediated[4:].strip()

                if self._validate_llm_output(remediated, code):
                    return self._post_process_jakarta(remediated)
        except Exception as e:
            logger.warning(f"LLM remediation failed: {str(e)}")

        # Deterministic fallback if LLM fails to remove Spring error handler
        if 'ResponseErrorHandler' in code:
            code = self._transform_response_error_handler(code)

        return code

    def _validate_llm_output(self, migrated_code: str, source_code: str) -> bool:
        """Validate LLM output for basic GA guardrails"""
        if not migrated_code or not migrated_code.strip():
            return False

        # Must include a class or interface
        if not re.search(r'\b(class|interface)\s+\w+', migrated_code):
            return False

        if self.settings.llm_validation_strict:
            # Avoid returning the exact source unchanged
            if migrated_code.strip() == source_code.strip():
                return False
            # Should not include Spring imports in strict mode
            if 'org.springframework' in migrated_code:
                return False
        return True

    def _deterministic_annotation_rewrite(self, code: str, ann_name: str) -> tuple[str, bool]:
        """Apply correctness-critical Spring annotation rewrites without relying on RAG."""
        replacements = {
            'Autowired': '@Inject',
            'Component': '@ApplicationScoped',
            'Configuration': '@ApplicationScoped',
            'Repository': '@ApplicationScoped',
            'RestController': '@ApplicationScoped',
            'Service': '@ApplicationScoped',
        }

        if ann_name in replacements:
            code = re.sub(
                rf'@{re.escape(ann_name)}(?:\([^)]*\))?',
                replacements[ann_name],
                code
            )
            return code, True

        if ann_name == 'Qualifier':
            code = re.sub(
                r'@Qualifier\s*\(\s*"([^"]+)"\s*\)',
                r'@Named("\1")',
                code
            )
            return code, True

        if ann_name == 'Value':
            code = re.sub(
                r'@Value\s*\(\s*"\#\{\'\$\{([^}:]+)(?::([^}]*))?\}\'\.split\(\'\,\'\)\}"\s*\)',
                lambda m: (
                    f'@ConfigProperty(name = "{m.group(1)}", defaultValue = "{(m.group(2) or "").strip()}")'
                ),
                code
            )
            code = re.sub(
                r'@Value\s*\(\s*"\$\{([^}:]+):([^}]+)\}"\s*\)',
                r'@ConfigProperty(name = "\1", defaultValue = "\2")',
                code
            )
            code = re.sub(
                r'@Value\s*\(\s*"\$\{([^}]+)\}"\s*\)',
                r'@ConfigProperty(name = "\1")',
                code
            )
            return code, True

        return code, False

    def _deterministic_import_rewrite(self, spring_import: str) -> str | None:
        """Map high-volume Spring imports to deterministic Jakarta/CDI imports."""
        replacements = {
            'org.springframework.beans.factory.annotation.Autowired': 'jakarta.inject.Inject',
            'org.springframework.beans.factory.annotation.Qualifier': 'jakarta.inject.Named',
            'org.springframework.beans.factory.annotation.Value': 'org.eclipse.microprofile.config.inject.ConfigProperty',
            'org.springframework.boot.context.properties.ConfigurationProperties': 'org.eclipse.microprofile.config.inject.ConfigProperties',
            'org.springframework.context.annotation.Configuration': 'jakarta.enterprise.context.ApplicationScoped',
            'org.springframework.stereotype.Component': 'jakarta.enterprise.context.ApplicationScoped',
            'org.springframework.stereotype.Repository': 'jakarta.enterprise.context.ApplicationScoped',
            'org.springframework.stereotype.Service': 'jakarta.enterprise.context.ApplicationScoped',
            'org.springframework.web.bind.annotation.PathVariable': 'jakarta.ws.rs.PathParam',
            'org.springframework.web.bind.annotation.RequestHeader': 'jakarta.ws.rs.HeaderParam',
            'org.springframework.web.bind.annotation.RequestMapping': 'jakarta.ws.rs.Path',
            'org.springframework.web.bind.annotation.RequestParam': 'jakarta.ws.rs.QueryParam',
            'org.springframework.web.util.UriComponentsBuilder': 'jakarta.ws.rs.core.UriBuilder',
        }
        return replacements.get(spring_import)
    
    def _apply_pattern_directly(self, source_code: str, pattern_match: dict) -> str:
        """
        Apply pattern directly from vector DB to source code (for high similarity matches)
        
        Uses the actual Helidon pattern from vector DB metadata instead of fallback
        """
        metadata = pattern_match.get('metadata', {})
        helidon_pattern = metadata.get('helidon_pattern', '')
        spring_pattern = metadata.get('spring_pattern', '')
        pattern_text = pattern_match.get('text', '')
        migration_type = metadata.get('migration_type', '')
        
        # If we have a complete Helidon code pattern, use it as template
        if migration_type == 'code_pattern' and helidon_pattern and len(helidon_pattern) > 100:
            # This is a full code pattern - extract the Helidon code
            # Pattern text format: "Spring: ...\nHelidon: ..."
            if 'Helidon:' in pattern_text:
                helidon_code = pattern_text.split('Helidon:')[1].strip()
                # Use this as base and adapt to our source code structure
                # Extract class name, package, etc. from source
                source_package_match = re.search(r'package\s+([^;]+);', source_code)
                source_class_match = re.search(r'(?:public\s+)?(?:class|interface)\s+(\w+)', source_code)
                
                if source_package_match and source_class_match:
                    package_name = source_package_match.group(1)
                    class_name = source_class_match.group(1)
                    
                    # Replace package and class name in pattern
                    helidon_code = re.sub(r'package\s+[^;]+;', f'package {package_name};', helidon_code)
                    helidon_code = re.sub(r'(?:public\s+)?(?:class|interface)\s+\w+', 
                                         lambda m: m.group(0).replace(re.search(r'\w+$', m.group(0)).group(0), class_name) 
                                         if re.search(r'\w+$', m.group(0)) else m.group(0), 
                                         helidon_code)
                    
                    # Apply post-processing
                    helidon_code = self._post_process_jakarta(helidon_code)
                    helidon_code = self._transform_main_class(helidon_code)
                    helidon_code = self._transform_repository(helidon_code)
                    
                    return helidon_code
        
        # If pattern is annotation/import/config mapping, use regex transform but with pattern guidance
        # Still use regex transform but it will use vector DB for mappings
        transformed_code, _ = self._fallback_regex_transform(source_code)
        transformed_code = self._transform_main_class(transformed_code)
        transformed_code = self._transform_repository(transformed_code)
        
        return transformed_code
    
    def _post_process_jakarta(self, code: str) -> str:
        """Post-process: Convert all javax.* to jakarta.* for Helidon 4.x"""
        # Convert javax imports to jakarta
        jakarta_replacements = {
            'javax.inject.': 'jakarta.inject.',
            'javax.ws.rs.': 'jakarta.ws.rs.',
            'javax.enterprise.context.': 'jakarta.enterprise.context.',
            'javax.persistence.': 'jakarta.persistence.',
            'javax.annotation.': 'jakarta.annotation.',
            'javax.transaction.': 'jakarta.transaction.',
            # javax.sql. remains javax.sql. as it is JDK
        }
        
        for javax_prefix, jakarta_prefix in jakarta_replacements.items():
            code = code.replace(javax_prefix, jakarta_prefix)
        
        # Also fix in import statements
        code = re.sub(r'import\s+javax\.(inject|ws|enterprise|persistence|annotation)\.', 
                      lambda m: f"import jakarta.{m.group(1)}.", code)
        
        return code
    
    def _save_new_pattern(self, source_code: str, migrated_code: str):
        """Save new migration pattern to dataset JSON and vector DB (Environment Learning)"""
        try:
            helidon_version = getattr(self.settings, 'helidon_version', '4.3.2')
            spring_version = getattr(self.settings, 'spring_version', '3.4.5')
            
            # Create pattern entry
            pattern_id = str(uuid.uuid4())
            pattern_entry = {
                'id': pattern_id,
                'spring_pattern': source_code[:500],  # First 500 chars for context
                'helidon_pattern': migrated_code[:500],
                'migration_type': 'code_pattern',
                'spring_version': spring_version,
                'helidon_version': helidon_version,
                'created_at': datetime.now().isoformat(),
                'source': 'llm_generated'
            }
            
            # Save to dataset JSON file
            dataset_file = Path(self.settings.chromadb_path).parent / 'migration_dataset_learned.json'
            patterns = []
            if dataset_file.exists():
                try:
                    with open(dataset_file, 'r', encoding='utf-8') as f:
                        patterns = json.load(f)
                except:
                    patterns = []
            
            patterns.append(pattern_entry)
            
            with open(dataset_file, 'w', encoding='utf-8') as f:
                json.dump(patterns, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved new pattern to dataset: {pattern_id}")
            
            # Add to vector DB
            try:
                embedding = self.embedding_model.encode_single(source_code[:1000])
                self.knowledge_base.add_patterns('code_patterns', [{
                    'id': pattern_id,
                    'text': f"Spring: {source_code[:300]}\nHelidon: {migrated_code[:300]}",
                    'embedding': embedding.tolist() if hasattr(embedding, 'tolist') else embedding,
                    'metadata': {
                        'migration_type': 'code_pattern',
                        'spring_version': spring_version,
                        'helidon_version': helidon_version,
                        'source': 'llm_generated'
                    }
                }])
                logger.info(f"Added new pattern to vector DB: {pattern_id}")
            except Exception as e:
                logger.warning(f"Could not add pattern to vector DB: {str(e)}")
                
        except Exception as e:
            logger.warning(f"Failed to save new pattern: {str(e)}")

    def _fallback_regex_transform(self, source_code: str) -> tuple[str, int]:
        """Original regex-based transformation (Fallback + Type Cleanup)"""
        transformed_code = source_code
        count = 0
        
        # 1. Specific Framework Transformations (BEFORE general cleanup)
        # Transform Spring Cloud Gateway (creates side-effect files)
        transformed_code = self._transform_cloud_gateway(transformed_code)
        transformed_code = self._transform_microprofile_configproperty(transformed_code)
        
        # 2. General Transformations
        t_code, c1 = self._transform_annotations(transformed_code)
        t_code, c2 = self._transform_imports(t_code)
        t_code, c3 = self._transform_types(t_code) # New: Type transformation
        
        # Apply main class and repository transformations
        t_code = self._transform_main_class(t_code)
        t_code = self._transform_repository(t_code)
        t_code = self._transform_spring_configuration(t_code)
        t_code = self._transform_response_error_handler(t_code)
        t_code = self._transform_web_signatures(t_code)
        t_code = self._transform_helidon_se_controller(t_code)
        t_code = self._transform_http_utilities(t_code)
        t_code = self._transform_bean_utils_copy(t_code)
        t_code = self._transform_request_abstractions(t_code)
        t_code = self._transform_keystone_router_proxy_forwarding(t_code)
        t_code = self._normalize_uri_exception_signatures(t_code)
        t_code = self._cleanup_obsolete_uri_exception_blocks(t_code)
        t_code = self._stabilize_admin_service_proxy_methods(t_code)
        t_code = self._normalize_generic_exception_usage(t_code)
        t_code = self._transform_parameter_annotation_aspects(t_code)
        t_code = self._transform_test_support(t_code)
        t_code = self._finalize_response_builders(t_code)
        t_code = self._normalize_resource_shapes(t_code)
        t_code = self._ensure_bean_scope_annotations(t_code)
        t_code = self._inject_custom_response_error_handler(t_code)
        t_code = self._transform_microprofile_configproperty(t_code)
        t_code = self._transform_http_utilities(t_code)
        t_code = self._transform_request_abstractions(t_code)
        t_code = self._remove_unused_private_fields(t_code)
        t_code = self._cleanup_generated_code(t_code)
        t_code = self._materialize_lombok_features(t_code)
        
        # Ensure imports are present (FINAL SAFETY CHECK)
        t_code = self._ensure_imports(t_code)
        t_code = self._remove_unused_imports(t_code)
        t_code = self._reindent_java_code(t_code)
        
        return t_code, c1 + c2 + c3

    def _transform_microprofile_configproperty(self, code: str) -> str:
        """Convert Spring-style ConfigProperty placeholders to MicroProfile style"""
        code = re.sub(
            r'@ConfigProperty\(\s*"\$\{([^}:]+):([^}]+)\}"\s*\)',
            r'@ConfigProperty(name = "\1", defaultValue = "\2")',
            code
        )
        # @ConfigProperty("${key}") -> @ConfigProperty(name = "key")
        code = re.sub(
            r'@ConfigProperty\(\s*"\$\{([^}]+)\}"\s*\)',
            r'@ConfigProperty(name = "\1")',
            code
        )
        # @ConfigProperty("key") -> @ConfigProperty(name = "key")
        code = re.sub(
            r'@ConfigProperty\(\s*"([^"]+)"\s*\)',
            r'@ConfigProperty(name = "\1")',
            code
        )
        # Spring EL list split -> plain MicroProfile property name
        code = re.sub(
            r'@ConfigProperty\(\s*"#\{\'\$\{([^}:]+)(?::[^}]*)?\}\'\.split\(\'\,\'\)\}"\s*\)',
            r'@ConfigProperty(name = "\1")',
            code
        )
        code = re.sub(
            r'@ConfigProperty\(\s*name\s*=\s*"#\{\'\$\{([^}:]+)(?::[^}]*)?\}\'\.split\(\'\,\'\)\}"\s*\)',
            r'@ConfigProperty(name = "\1")',
            code
        )
        code = re.sub(
            r'@ConfigProperty\(\s*name\s*=\s*"\$\{([^}]+)\}"\s*\)',
            r'@ConfigProperty(name = "\1")',
            code
        )
        code = re.sub(
            r'@ConfigProperty\(\s*name\s*=\s*"\$\{([^}:]+):([^}]+)\}"\s*\)',
            r'@ConfigProperty(name = "\1", defaultValue = "\2")',
            code
        )
        return code

    def _transform_web_signatures(self, code: str) -> str:
        """Normalize Spring web annotations and path syntax to JAX-RS forms."""
        replacements = {
            'import org.springframework.web.bind.annotation.RequestMapping;\n': '',
            'import org.springframework.web.bind.annotation.GetMapping;\n': '',
            'import org.springframework.web.bind.annotation.PostMapping;\n': '',
            'import org.springframework.web.bind.annotation.PutMapping;\n': '',
            'import org.springframework.web.bind.annotation.DeleteMapping;\n': '',
            'import org.springframework.web.bind.annotation.PatchMapping;\n': '',
            'import org.springframework.web.bind.annotation.RequestHeader;\n': '',
            'import org.springframework.web.bind.annotation.RequestParam;\n': '',
            'import org.springframework.web.bind.annotation.RequestBody;\n': '',
            'import org.springframework.web.bind.annotation.PathVariable;\n': '',
            'import org.springframework.web.bind.annotation.RequestMethod;\n': '',
            'import org.springframework.util.MultiValueMap;\n': '',
        }
        for old, new in replacements.items():
            code = code.replace(old, new)

        code = re.sub(
            r'@RequestHeader\s*\(\s*value\s*=\s*([^,)\n]+)(?:,\s*required\s*=\s*(?:true|false))?\s*\)',
            r'@HeaderParam(\1)',
            code
        )
        code = re.sub(
            r'@RequestHeader\s*\(\s*([^,)\n]+)(?:,\s*required\s*=\s*(?:true|false))?\s*\)',
            r'@HeaderParam(\1)',
            code
        )
        code = re.sub(r'@RequestHeader\b', '@HeaderParam', code)
        code = re.sub(
            r'@RequestParam\s*\(\s*value\s*=\s*([^,)\n]+)(?:,\s*required\s*=\s*(?:true|false))?\s*\)',
            r'@QueryParam(\1)',
            code
        )
        code = re.sub(
            r'@RequestParam\s*\(\s*([^,)\n]+)(?:,\s*required\s*=\s*(?:true|false))?\s*\)',
            r'@QueryParam(\1)',
            code
        )
        code = re.sub(r'@RequestParam\b', '@QueryParam', code)
        code = re.sub(
            r'@PathVariable\s*\(\s*value\s*=\s*([^,)\n]+)\s*\)',
            r'@PathParam(\1)',
            code
        )
        code = re.sub(
            r'@PathVariable\s*\(\s*([^,)\n]+)\s*\)',
            r'@PathParam(\1)',
            code
        )
        code = re.sub(
            r'@PathVariable\b',
            '@PathParam',
            code
        )
        code = re.sub(r'@RequestBody\b\s*', '', code)

        def replace_request_mapping(match):
            args = match.group(1)
            annotations = []
            method_match = re.search(r'method\s*=\s*RequestMethod\.([A-Z]+)', args)
            if method_match:
                annotations.append(f"@{method_match.group(1)}")

            consumes_match = re.search(r'consumes\s*=\s*([A-Za-z0-9_\.]+)', args)
            if consumes_match:
                consumes_value = consumes_match.group(1)
                consumes_value = consumes_value.replace('APPLICATION_FORM_URLENCODED_VALUE', 'APPLICATION_FORM_URLENCODED')
                annotations.append(f"@Consumes({consumes_value})")

            path_literals = re.findall(r'"[^"]+"', args)
            if len(path_literals) > 1:
                annotations.append(self._collapse_path_array_from_literals(path_literals))
            elif path_literals:
                annotations.append(f"@Path({path_literals[0]})")
            else:
                single_path_match = re.search(r'value\s*=\s*([^,]+)', args)
                if single_path_match:
                    annotations.append(f"@Path({single_path_match.group(1).strip()})")
                elif args.strip():
                    annotations.append(f"@Path({args.strip()})")
                else:
                    annotations.append("@Path")

            return '\n'.join(annotations)

        def replace_http_mapping_annotation(http_verb: str):
            def replacer(match):
                args = match.group(1) or ''
                path_literals = re.findall(r'"[^"]+"', args)
                annotations = [f'@{http_verb}']

                consumes_match = re.search(r'consumes\s*=\s*([A-Za-z0-9_\.]+)', args)
                if consumes_match:
                    consumes_value = consumes_match.group(1)
                    consumes_value = consumes_value.replace('APPLICATION_FORM_URLENCODED_VALUE', 'APPLICATION_FORM_URLENCODED')
                    annotations.append(f"@Consumes({consumes_value})")

                if len(path_literals) > 1:
                    annotations.append(self._collapse_path_array_from_literals(path_literals))
                elif path_literals:
                    annotations.append(f"@Path({path_literals[0]})")
                elif args.strip():
                    annotations.append(f"@Path({args.strip()})")

                return '\n'.join(annotations)
            return replacer

        code = re.sub(r'@GetMapping(?:\s*\(([^)]*)\))?', replace_http_mapping_annotation('GET'), code)
        code = re.sub(r'@PostMapping(?:\s*\(([^)]*)\))?', replace_http_mapping_annotation('POST'), code)
        code = re.sub(r'@PutMapping(?:\s*\(([^)]*)\))?', replace_http_mapping_annotation('PUT'), code)
        code = re.sub(r'@DeleteMapping(?:\s*\(([^)]*)\))?', replace_http_mapping_annotation('DELETE'), code)
        code = re.sub(r'@PatchMapping(?:\s*\(([^)]*)\))?', replace_http_mapping_annotation('PATCH'), code)
        code = re.sub(r'@RequestMapping\s*\(([^)]*)\)', replace_request_mapping, code)
        code = self._normalize_jaxrs_http_value_annotations(code)
        code = re.sub(r'@Path\s*\(\s*value\s*=\s*', '@Path(', code)
        code = re.sub(
            r'@Path\s*\(\s*\{\s*(.*?)\s*\}\s*\)',
            self._collapse_path_array,
            code
            , flags=re.DOTALL
        )
        code = re.sub(
            r'@Path\s*\(\s*value\s*=\s*\{\s*(.*?)\s*\}\s*\)',
            self._collapse_path_array,
            code
            , flags=re.DOTALL
        )
        code = self._normalize_wildcard_path_literals(code)
        code = re.sub(
            r'@Consumes\(MediaType\.APPLICATION_FORM_URLENCODED\)\s*\n(\s*public\s+[^{(]+\([^)]*)@QueryParam\s+MultivaluedMap<String,\s*String>\s+(\w+)',
            r'@Consumes(MediaType.APPLICATION_FORM_URLENCODED)\n\1MultivaluedMap<String, String> \2',
            code
        )
        code = self._add_inferred_http_methods(code)
        return code

    def _normalize_jaxrs_http_value_annotations(self, code: str) -> str:
        """Normalize invalid JAX-RS verb annotations that still carry Spring-style value/consumes args."""
        def replacer(http_verb: str):
            pattern = re.compile(rf'@{http_verb}\s*\(([^)]*)\)')

            def replace(match):
                args = match.group(1) or ''
                annotations = [f'@{http_verb}']
                path_literals = re.findall(r'"[^"]+"', args)
                consumes_match = re.search(r'consumes\s*=\s*([A-Za-z0-9_\.]+)', args)
                if consumes_match:
                    consumes_value = consumes_match.group(1).replace(
                        'APPLICATION_FORM_URLENCODED_VALUE',
                        'APPLICATION_FORM_URLENCODED'
                    )
                    annotations.append(f'@Consumes({consumes_value})')

                if len(path_literals) > 1:
                    annotations.append(self._collapse_path_array_from_literals(path_literals))
                elif path_literals:
                    annotations.append(f'@Path({path_literals[0]})')
                else:
                    value_match = re.search(r'value\s*=\s*([^,]+)', args)
                    if value_match:
                        annotations.append(f'@Path({value_match.group(1).strip()})')

                return '\n'.join(annotations)

            return pattern.sub(replace, code)

        for verb in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']:
            code = replacer(verb)
        code = self._normalize_invalid_jaxrs_path_annotations(code)
        return code

    def _normalize_invalid_jaxrs_path_annotations(self, code: str) -> str:
        """Convert stray Spring-style arguments that leaked into @Path annotations."""
        pattern = re.compile(r'@Path\s*\(([^)]*)\)')

        def replace(match):
            args = match.group(1) or ''
            if 'method=' not in args and 'consumes' not in args and 'value=' not in args:
                return match.group(0)

            annotations: List[str] = []
            consumes_match = re.search(r'consumes\s*=\s*([A-Za-z0-9_\.]+)', args)
            if consumes_match:
                consumes_value = consumes_match.group(1).replace(
                    'APPLICATION_FORM_URLENCODED_VALUE',
                    'APPLICATION_FORM_URLENCODED'
                )
                annotations.append(f'@Consumes({consumes_value})')

            path_literals = re.findall(r'"([^"]+)"', args)
            if path_literals:
                if len(path_literals) > 1:
                    annotations.append(self._collapse_path_array_from_literals([f'"{path}"' for path in path_literals]))
                else:
                    annotations.append(f'@Path("{self._normalize_single_path_literal(path_literals[0])}")')
                return '\n'.join(annotations)

            return match.group(0)

        return pattern.sub(replace, code)

    def _collapse_path_array(self, match) -> str:
        """Collapse multi-path Spring/JAX-RS arrays into a single, most permissive JAX-RS path."""
        raw_paths = re.findall(r'"([^"]+)"', match.group(1))
        return self._collapse_path_array_from_literals([f'"{path}"' for path in raw_paths])

    def _collapse_path_array_from_literals(self, path_literals: List[str]) -> str:
        """Collapse a list of quoted path literals into one JAX-RS path."""
        raw_paths = [literal.strip('"') for literal in path_literals]
        if not raw_paths:
            return '@Path'
        if len(raw_paths) == 2:
            base = next((path for path in raw_paths if '/**' not in path), None)
            wildcard = next((path for path in raw_paths if path.endswith('/**')), None)
            if base and wildcard and wildcard[:-3] == base:
                return f'@Path("{self._spring_wildcard_path_to_jaxrs(wildcard)}")'
            optional_middle = self._collapse_optional_middle_path(raw_paths[0], raw_paths[1])
            if optional_middle:
                return f'@Path("{optional_middle}")'
        chosen = next((path for path in raw_paths if '/**' in path), raw_paths[0])
        chosen = self._spring_wildcard_path_to_jaxrs(chosen)
        return f'@Path("{chosen}")'

    def _spring_wildcard_path_to_jaxrs(self, path: str) -> str:
        """Convert Spring /** paths into a single JAX-RS-compatible catch-all path."""
        if path == '/**':
            return '/{path: .*}'
        if path.endswith('/**'):
            return f'{path[:-3]}{{path: (/.*)?}}'
        return path

    def _normalize_single_path_literal(self, path: str) -> str:
        """Normalize Spring/JAX-RS catch-all path literals to the preferred Helidon MP shape."""
        if path == '/**' or path.endswith('/**'):
            return self._spring_wildcard_path_to_jaxrs(path)
        if path.endswith('/{path: .*}') and path != '/{path: .*}':
            return f'{path[:-len("/{path: .*}")]}{{path: (/.*)?}}'
        return path

    def _normalize_wildcard_path_literals(self, code: str) -> str:
        """Normalize wildcard path literals that appear inside @Path annotations."""
        def replace(match):
            path = match.group(1)
            return f'@Path("{self._normalize_single_path_literal(path)}")'

        return re.sub(r'@Path\(\s*"([^"\n]+)"\s*\)', replace, code)

    def _collapse_optional_middle_path(self, left_path: str, right_path: str) -> str | None:
        """Collapse two paths that differ only by an optional middle segment."""
        left_tokens = [token for token in left_path.split('/') if token]
        right_tokens = [token for token in right_path.split('/') if token]
        if not left_tokens or not right_tokens:
            return None

        prefix_len = 0
        while (
            prefix_len < len(left_tokens)
            and prefix_len < len(right_tokens)
            and left_tokens[prefix_len] == right_tokens[prefix_len]
        ):
            prefix_len += 1

        suffix_len = 0
        while (
            suffix_len < (len(left_tokens) - prefix_len)
            and suffix_len < (len(right_tokens) - prefix_len)
            and left_tokens[-(suffix_len + 1)] == right_tokens[-(suffix_len + 1)]
        ):
            suffix_len += 1

        left_middle = left_tokens[prefix_len:len(left_tokens) - suffix_len if suffix_len else len(left_tokens)]
        right_middle = right_tokens[prefix_len:len(right_tokens) - suffix_len if suffix_len else len(right_tokens)]
        if bool(left_middle) == bool(right_middle):
            return None

        optional_tokens = left_middle or right_middle
        if not optional_tokens:
            return None

        prefix = ''.join(f'/{token}' for token in left_tokens[:prefix_len])
        suffix_tokens = left_tokens[len(left_tokens) - suffix_len:] if suffix_len else []
        suffix = ''.join(f'/{token}' for token in suffix_tokens)
        optional_regex = ''.join(self._path_token_to_regex(token) for token in optional_tokens)
        return f'{prefix}{{optionalPath: (?:{optional_regex})?}}{suffix}'

    def _path_token_to_regex(self, token: str) -> str:
        """Convert a path token into a safe JAX-RS regex fragment."""
        if re.fullmatch(r'\{[^}]+\}', token):
            return '/[^/]+'
        return '/' + re.escape(token)

    def _add_inferred_http_methods(self, code: str) -> str:
        """Add HTTP method annotations when method names make the intent deterministic."""
        method_pattern = re.compile(
            r'(@Path\([^\n]+\)\s*\n)((?:(?!@(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b)[^\n]*\n)*?\s*(public|protected|private)\s+[^{]+\s+(\w+)\s*\()',
            re.MULTILINE
        )

        def replace(match):
            path_annotation = match.group(1)
            signature_block = match.group(2)
            method_name = match.group(5)
            lowered = method_name.lower()
            inferred = None
            if lowered.startswith(('get', 'find', 'list', 'read', 'fetch')):
                inferred = '@GET'
            elif lowered.startswith(('create', 'post')):
                inferred = '@POST'
            elif lowered.startswith(('update', 'put')):
                inferred = '@PUT'
            elif lowered.startswith(('delete', 'remove')):
                inferred = '@DELETE'
            elif lowered.startswith('patch'):
                inferred = '@PATCH'
            if not inferred:
                return match.group(0)
            return f'{inferred}\n{path_annotation}{signature_block}'

        return method_pattern.sub(replace, code)

    def _finalize_response_builders(self, code: str) -> str:
        """Ensure JAX-RS response builders are completed with build()."""
        code = re.sub(
            r'Response\.ok\(\)\.entity\(\)\.entity\((.+?)\)',
            r'Response.ok().entity(\1)',
            code
        )
        code = re.sub(
            r'Response\.ok\(\)\.entity\((.+?)\)(?!\.build\(\));',
            r'Response.ok().entity(\1).build();',
            code
        )
        code = re.sub(
            r'Response\.status\((.+?)\)\.entity\((.+?)\)(?!\.build\(\));',
            r'Response.status(\1).entity(\2).build();',
            code
        )
        code = code.replace('.build().build()', '.build()')
        return code

    def _cleanup_generated_code(self, code: str) -> str:
        """Normalize formatting and invalid API remnants after transformation."""
        code = self._remove_duplicate_logger_annotations(code)
        code = self._cleanup_local_proxy_calls(code)
        code = self._normalize_http_response_fallbacks(code)
        code = self._remove_stale_checked_encoding_exceptions(code)
        code = self._normalize_slf4j_placeholders(code)
        code = re.sub(r'(\*/)(?=@)', r'\1\n', code)
        code = re.sub(r'(\})\s*(?=@)', r'\1\n', code)
        code = re.sub(r'@([A-Z]+)\s*\+\s*@\1', r'@\1', code)
        code = re.sub(r'@([A-Z]+)\s*\+\s*@([A-Z]+)', r'@\1\n@\2', code)
        code = re.sub(r'^\s*@Path\s*\n(?=\s*@Path\()', '', code, flags=re.MULTILINE)
        code = re.sub(r'(\*/)\s*@', r'\1\n@', code)
        code = re.sub(r'(@[A-Za-z_][\w]*(?:\([^)]*\))?)\s*(?=@[A-Za-z_])', r'\1\n', code)
        code = re.sub(
            r'(^\s*@(?:GET|POST|PUT|DELETE|PATCH|Path|Produces|Consumes|ApplicationScoped|RequestScoped|Inject|Named|ConfigProperty|HeaderParam|PathParam|QueryParam|Context)\b[^\n]*\n)(?=[^\s@])',
            r'\1    ',
            code,
            flags=re.MULTILINE
        )
        code = re.sub(
            r'Response\.Status\.([A-Z_]+)\.value\(\)',
            r'Response.Status.\1.getStatusCode()',
            code
        )
        code = re.sub(
            r'Response\.Status\.valueOf\(([^)]+)\)',
            r'Response.Status.fromStatusCode(\1)',
            code
        )
        code = re.sub(
            r'@PathParam\s+([A-Za-z0-9_<>,\[\]\.? ]+)\s+([A-Za-z_]\w*)',
            r'@PathParam("\2") \1 \2',
            code
        )
        code = re.sub(
            r'@HeaderParam\s+([A-Za-z0-9_<>,\[\]\.? ]+)\s+([A-Za-z_]\w*)',
            r'@HeaderParam("\2") \1 \2',
            code
        )
        code = re.sub(
            r'@QueryParam\s+([A-Za-z0-9_<>,\[\]\.? ]+)\s+([A-Za-z_]\w*)',
            r'@QueryParam("\2") \1 \2',
            code
        )
        code = self._dedupe_consecutive_annotations(code)
        code = re.sub(r'(\})(?=\s*@)', r'\1\n', code)
        code = re.sub(r'(\*/)(?=\s*@)', r'\1\n', code)
        code = re.sub(r'(\*/)\n\s*\n(?=@)', r'\1\n', code)
        code = re.sub(r'(\})\n\s*\n(?=@)', r'\1\n', code)
        code = re.sub(r'\n{3,}', '\n\n', code)
        return code

    def _normalize_http_response_fallbacks(self, code: str) -> str:
        """Avoid null fallback responses in generated HTTP dispatch code."""
        code = re.sub(
            r'(default:\s*)(?:\r?\n)(\s*)response\s*=\s*null\s*;',
            r'\1\n\2response = Response.status(Response.Status.METHOD_NOT_ALLOWED).build();',
            code
        )
        code = re.sub(
            r'(default:\s*)(?:\r?\n)(\s*)return\s+null\s*;',
            r'\1\n\2return Response.status(Response.Status.METHOD_NOT_ALLOWED).build();',
            code
        )
        return code

    def _remove_stale_checked_encoding_exceptions(self, code: str) -> str:
        """Drop UnsupportedEncodingException declarations when migration removed checked encoding APIs."""
        if 'UnsupportedEncodingException' not in code:
            return code

        if 'throw new UnsupportedEncodingException' in code:
            return code

        code = re.sub(
            r'\s*,\s*UnsupportedEncodingException\b',
            '',
            code
        )
        code = re.sub(
            r'throws\s+UnsupportedEncodingException\s*,\s*',
            'throws ',
            code
        )
        code = re.sub(
            r'\s*throws\s+UnsupportedEncodingException\b',
            '',
            code
        )

        remaining_non_import_usage = any(
            'UnsupportedEncodingException' in line and not line.strip().startswith('import ')
            for line in code.splitlines()
        )
        if not remaining_non_import_usage:
            code = re.sub(r'import\s+java\.io\.UnsupportedEncodingException;\s*\n?', '', code)

        return code

    def _cleanup_local_proxy_calls(self, code: str) -> str:
        """Remove stale proxy arguments from same-class method calls after field injection."""
        method_pattern = re.compile(
            r'(?:public|protected|private)\s+[A-Za-z_][\w<>,\[\]\.? ]*\s+([A-Za-z_]\w*)\s*\(([^)]*)\)',
            re.MULTILINE
        )
        local_methods_without_proxy = set()
        for match in method_pattern.finditer(code):
            method_name = match.group(1)
            params = match.group(2)
            if 'ProxyExchange' not in params:
                local_methods_without_proxy.add(method_name)

        for method_name in local_methods_without_proxy:
            code = re.sub(
                rf'(?<![\w\.]){re.escape(method_name)}\(\s*proxy\s*,\s*',
                f'{method_name}(',
                code
            )
            code = re.sub(
                rf'(?<![\w\.]){re.escape(method_name)}\(([^)]*?),\s*proxy\s*\)',
                rf'{method_name}(\1)',
                code
            )

        return code

    def _normalize_slf4j_placeholders(self, code: str) -> str:
        """Normalize malformed SLF4J placeholder usage without changing control flow."""
        code = re.sub(r'\{\s*\}', '{}', code)
        code = re.sub(r'(?<=[A-Za-z0-9:])\{\}', ' {}', code)

        def split_args(args_text: str) -> List[str]:
            args: List[str] = []
            current: List[str] = []
            depth = 0
            in_string = False
            escaped = False
            for char in args_text:
                if in_string:
                    current.append(char)
                    if escaped:
                        escaped = False
                    elif char == '\\':
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue

                if char == '"':
                    in_string = True
                    current.append(char)
                    continue
                if char in '([{<':
                    depth += 1
                    current.append(char)
                    continue
                if char in ')]}>':
                    depth = max(0, depth - 1)
                    current.append(char)
                    continue
                if char == ',' and depth == 0:
                    arg = ''.join(current).strip()
                    if arg:
                        args.append(arg)
                    current = []
                    continue
                current.append(char)

            tail = ''.join(current).strip()
            if tail:
                args.append(tail)
            return args

        concat_with_args_pattern = re.compile(
            r'log\.(trace|debug|info|warn|error)\(\s*"([^"\n]*)"\s*\+\s*([^,\n\)]+?)\s*,\s*(.+?)\s*\);'
        )

        def replace_concat_with_args(match) -> str:
            level = match.group(1)
            message = match.group(2).rstrip()
            first_arg = match.group(3).strip()
            remaining_args_text = match.group(4).strip()
            remaining_args = split_args(remaining_args_text)
            all_args = [first_arg] + remaining_args

            if message.count('{}') >= len(all_args):
                normalized_message = message
            else:
                missing = len(all_args) - message.count('{}')
                normalized_message = f'{message} {" ".join(["{}"] * missing)}'.strip()

            return f'log.{level}("{normalized_message}", {", ".join(all_args)});'

        code = concat_with_args_pattern.sub(replace_concat_with_args, code)

        concat_only_pattern = re.compile(
            r'log\.(trace|debug|info|warn|error)\(\s*"([^"\n]*)"\s*\+\s*([^)]+?)\s*\);'
        )

        def replace_concat_only(match) -> str:
            level = match.group(1)
            message = match.group(2).rstrip()
            arg = match.group(3).strip()
            normalized_message = f'{message} {{}}'.strip()
            return f'log.{level}("{normalized_message}", {arg});'

        code = concat_only_pattern.sub(replace_concat_only, code)

        log_pattern = re.compile(
            r'log\.(trace|debug|info|warn|error)\(\s*"([^"\n]*)"\s*,\s*(.+?)\s*\);'
        )

        def replace_log_call(match) -> str:
            level = match.group(1)
            message = match.group(2)
            args_text = match.group(3)
            if '{}' in message:
                return match.group(0)

            args = split_args(args_text)
            if not args:
                return match.group(0)

            normalized_message = message.rstrip()
            placeholder_text = ', '.join(['{}'] * len(args))
            normalized_message = f'{normalized_message} {placeholder_text}'.strip()
            return f'log.{level}("{normalized_message}", {args_text});'

        code = log_pattern.sub(replace_log_call, code)
        code = re.sub(r'(\bproxy)\.entity\(([^)]*getBytes\([^)]*\)[^)]*)\);', r'\1.body(\2);', code)
        return code

    def _remove_unused_private_fields(self, code: str) -> str:
        """Drop unused injected private fields that became dead after deterministic rewrites."""
        field_pattern = re.compile(
            r'((?:\s*@\w+(?:\([^)]*\))?\s*\n)*)\s*private\s+([A-Za-z_][\w<>,\[\]\.? ]*)\s+([A-Za-z_]\w*)\s*;\n',
            re.MULTILINE
        )

        cursor = 0
        rewritten = []
        while True:
            match = field_pattern.search(code, cursor)
            if not match:
                rewritten.append(code[cursor:])
                break

            field_block = match.group(0)
            field_name = match.group(3)
            occurrences = len(re.findall(rf'\b{re.escape(field_name)}\b', code))

            rewritten.append(code[cursor:match.start()])
            annotations = match.group(1)
            if occurrences > 1 or '@Inject' not in annotations:
                rewritten.append(field_block)
            cursor = match.end()

        return ''.join(rewritten)

    def _remove_duplicate_logger_annotations(self, code: str) -> str:
        """Avoid Lombok logger annotations when they are redundant or unused."""
        has_explicit_logger = bool(
            re.search(r'(private|protected|public)\s+static\s+final\s+Logger\s+log\s*=', code)
        )
        uses_logger = 'log.' in code
        if not has_explicit_logger and uses_logger:
            return code

        code = re.sub(r'^\s*@Slf4j\s*\n', '', code, flags=re.MULTILINE)
        code = re.sub(r'import\s+lombok\.extern\.slf4j\.Slf4j;\s*\n?', '', code)
        return code

    def _dedupe_consecutive_annotations(self, code: str) -> str:
        """Remove immediately repeated duplicate annotations after expansion rewrites."""
        lines = code.splitlines()
        deduped: List[str] = []
        previous_annotation: str | None = None
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('@'):
                if stripped == previous_annotation:
                    continue
                previous_annotation = stripped
            elif stripped:
                previous_annotation = None
            deduped.append(line)
        code = '\n'.join(deduped)

        block_pattern = re.compile(
            r'((?:\s*@[\w.]+(?:\((?:[^()\n]|\([^()\n]*\))*\))?\s*\n)+)'
            r'(\s*(?:public|protected|private)\s+[A-Za-z_][\w<>,\[\]\.? ]*\s+\w+\s*\()',
            re.MULTILINE
        )

        def replace(match):
            annotations_block = match.group(1)
            signature = match.group(2)
            seen = set()
            ordered: List[str] = []
            for line in annotations_block.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped in seen:
                    continue
                seen.add(stripped)
                ordered.append(line if line.endswith('\n') else f'{line}')
            return '\n'.join(ordered) + '\n' + signature

        return block_pattern.sub(replace, code)

    def _normalize_resource_shapes(self, code: str) -> str:
        """Normalize JAX-RS resource classes after individual rewrites."""
        if not any(marker in code for marker in ['@Path', 'ProxyExchange', '@GET', '@POST', '@PUT', '@DELETE', '@PATCH']):
            return code

        for verb in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']:
            code = re.sub(rf'(@{verb}\s*\n)+', f'@{verb}\n', code)
        code = re.sub(r'(@Path\([^\n]+\)\s*\n)(?:\s*@Path\([^\n]+\)\s*\n)+', r'\1', code)

        if 'ProxyExchange' in code and self._is_resource_controller(code):
            code = self._normalize_proxy_exchange_usage(code)

        code = self._expand_proxy_catch_all_methods(code)

        code = re.sub(
            r'((?:@[A-Za-z_][\w]*(?:\([^)]*\))?\s*\n)+)(public\s+class\s+\w+)',
            self._strip_class_level_http_verbs,
            code
        )

        code = re.sub(
            r'@QueryParam\s+(MultivaluedMap<\s*String\s*,\s*String\s*>\s+\w+)',
            r'\1',
            code
        )
        code = re.sub(
            r'@QueryParam\s+(MultiValueMap<\s*String\s*,\s*String\s*>\s+\w+)',
            r'\1',
            code
        )
        code = re.sub(
            r'@Consumes\s+([A-Z][A-Za-z0-9_<>, \.\?\[\]]+\s+[a-zA-Z_]\w*)',
            r'\1',
            code
        )
        code = re.sub(
            r'\bMultiValueMap\s*<\s*String\s*,\s*String\s*>\b',
            'MultivaluedMap<String, String>',
            code
        )
        code = code.replace('MultiValueMap<String, String>', 'MultivaluedMap<String, String>')
        if '@QueryParam' not in code:
            code = re.sub(r'import\s+jakarta\.ws\.rs\.QueryParam;\s*\n?', '', code)

        class_match = re.search(r'public\s+class\s+\w+[^\{]*\{', code)
        if class_match:
            before_class = code[:class_match.start()]
            after_class = code[class_match.end():]
            has_method_level_path = bool(re.search(r'^\s*@Path\(', after_class, re.MULTILINE))
            has_class_level_path = '@Path(' in before_class[-400:]
            if has_method_level_path and not has_class_level_path:
                class_decl = class_match.group(0)
                replacement = '@Path("/")\n' + class_decl
                if '@ApplicationScoped' not in before_class[-400:]:
                    replacement = '@ApplicationScoped\n' + replacement
                code = code[:class_match.start()] + replacement + code[class_match.end():]

        if '@Path(' in code and '@ApplicationScoped' not in code:
            class_match = re.search(r'public\s+class\s+\w+[^\{]*\{', code)
            if class_match:
                code = code[:class_match.start()] + '@ApplicationScoped\n' + code[class_match.start():]

        code = self._ensure_body_consumes_annotations(code)

        return code

    def _ensure_body_consumes_annotations(self, code: str) -> str:
        """Add JSON consumes to body-bearing JAX-RS methods when no explicit consumes is present."""
        method_pattern = re.compile(
            r'((?:\s*@\w+(?:\((?:[^()\n]|\([^()\n]*\))*\))?\s*\n)+)\s*(public\s+Response\s+\w+\s*\((?:[^()]|\([^)]*\))*\))',
            re.MULTILINE
        )

        def looks_like_body_param(params: str) -> bool:
            for param in [part.strip() for part in params.split(',') if part.strip()]:
                if any(marker in param for marker in ['@Context', '@HeaderParam', '@PathParam', '@QueryParam']):
                    continue
                if 'HttpServletRequest' in param or 'ProxyExchange' in param or 'MultivaluedMap<' in param:
                    continue
                if re.search(r'\b(String|int|long|boolean|double|float|Integer|Long|Boolean|Double|Float)\b', param):
                    continue
                return True
            return False

        rewritten = []
        cursor = 0
        for match in method_pattern.finditer(code):
            rewritten.append(code[cursor:match.start()])
            annotations = match.group(1)
            signature = match.group(2)
            params_match = re.search(r'\((.*)\)', signature, re.DOTALL)
            params = params_match.group(1) if params_match else ''
            has_mutating_verb = any(verb in annotations for verb in ['@POST', '@PUT', '@PATCH'])
            has_consumes = '@Consumes(' in annotations
            if has_mutating_verb and not has_consumes and looks_like_body_param(params):
                annotations = annotations + '    @Consumes(MediaType.APPLICATION_JSON)\n'
            rewritten.append(annotations + signature)
            cursor = match.end()

        rewritten.append(code[cursor:])
        return ''.join(rewritten)

    def _expand_proxy_catch_all_methods(self, code: str) -> str:
        """Expand methodless wildcard proxy routes into explicit JAX-RS verb methods."""
        cursor = 0
        rewritten = []
        method_pattern = re.compile(
            r'((?:\s*//[^\n]*\n|\s*@\w+(?:\((?:[^()\n]|\([^()\n]*\))*\))?\s*\n)+)\s*(public\s+Response\s+(\w+)\s*\((?:[^()]|\([^)]*\))*\)\s*(?:throws\s+[^{]+)?\s*\{)',
            re.MULTILINE
        )

        while True:
            match = method_pattern.search(code, cursor)
            if not match:
                rewritten.append(code[cursor:])
                break

            annotations = match.group(1)
            signature = match.group(2)
            method_name = match.group(3)
            body_start = match.end() - 1
            body_end = self._find_matching_brace(code, body_start)
            if body_end == -1:
                rewritten.append(code[cursor:])
                break

            method_block = code[match.start():body_end + 1]
            rewritten.append(code[cursor:match.start()])

            has_http_verb = any(f'@{verb}' in annotations for verb in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'])
            looks_like_proxy = (
                '@Path(' in annotations and
                (
                    re.search(r'\{path:\s*(?:\.\*|\(/\.\*\)\?)\}', annotations) is not None
                    or 'getProxy(' in method_block
                    or 'proxyArtifactPath(' in method_block
                    or 'getVersion(' in method_block
                )
            )

            if has_http_verb or not looks_like_proxy:
                rewritten.append(method_block)
            else:
                expanded_methods = []
                body_inside = code[body_start + 1:body_end]
                for verb in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD']:
                    renamed_signature = re.sub(
                        rf'\b{re.escape(method_name)}\b',
                        f'{method_name}{verb.title()}',
                        signature,
                        count=1
                    )
                    expanded_methods.append(f'    @{verb}\n{annotations}{renamed_signature}\n{body_inside}\n    }}')
                rewritten.append('\n\n'.join(expanded_methods))

            cursor = body_end + 1

        return ''.join(rewritten)

    def _ensure_bean_scope_annotations(self, code: str) -> str:
        """Add CDI scope to service/config/aspect style classes that still need a bean scope."""
        if '@ApplicationScoped' in code or 'public interface ' in code:
            return code

        class_match = re.search(r'public\s+class\s+(\w+)', code)
        if not class_match:
            return code

        class_name = class_match.group(1)
        if 'extends Application' in code:
            return code

        bean_markers = [
            '@Aspect',
            '@Produces',
            '@Inject',
            '@ConfigProperty',
            ' implements OudpAdminService',
            ' implements ',
        ]
        looks_like_bean = (
            any(marker in code for marker in bean_markers)
            or class_name.endswith(('Service', 'ServiceImpl', 'Config', 'Controller', 'Aspect', 'Intercept', 'Handler'))
        )
        if not looks_like_bean:
            return code

        code = code[:class_match.start()] + '@ApplicationScoped\n' + code[class_match.start():]
        return code

    def _inject_custom_response_error_handler(self, code: str) -> str:
        """Replace ad-hoc CustomResponseErrorHandler construction with CDI injection."""
        uses_handler = (
            'new CustomResponseErrorHandler()' in code
            or 'customResponseErrorHandler.' in code
        )
        if not uses_handler:
            return code

        code = code.replace('new CustomResponseErrorHandler()', 'customResponseErrorHandler')

        if re.search(r'private\s+CustomResponseErrorHandler\s+customResponseErrorHandler\s*;', code):
            return code

        field_decl = '\n    @Inject\n    private CustomResponseErrorHandler customResponseErrorHandler;\n'
        class_match = re.search(r'public\s+class\s+\w+[^\{]*\{', code)
        if class_match:
            code = code[:class_match.end()] + field_decl + code[class_match.end():]
        return code

    def _strip_class_level_http_verbs(self, match) -> str:
        """Remove HTTP verb annotations applied directly to resource classes."""
        annotation_block = match.group(1)
        class_decl = match.group(2)
        cleaned = []
        for line in annotation_block.splitlines():
            if re.fullmatch(r'\s*@(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*', line):
                continue
            cleaned.append(line)
        block = '\n'.join(cleaned).strip()
        if block:
            return block + '\n' + class_decl
        return class_decl

    def _normalize_proxy_exchange_usage(self, code: str) -> str:
        """Convert ProxyExchange method injection to a request-scoped field reliably."""
        package_match = re.search(r'package\s+([^;]+);', code)
        current_package = package_match.group(1) if package_match else 'com.example.demo'
        support_import = f'{self._shared_proxy_support_package(current_package)}.ProxyExchange'

        method_pattern = re.compile(
            r'((?:public|protected)\s+[\w<>\[\], ?]+\s+\w+\s*)\(([^)]*ProxyExchange(?:<[^>]+>)?\s+(\w+)[^)]*)\)',
            re.MULTILINE
        )
        matches = list(method_pattern.finditer(code))
        if not matches:
            return code

        for match in matches:
            full_params = match.group(2)
            arg_name = match.group(3)
            cleaned_params = re.sub(
                r',\s*ProxyExchange(?:<[^>]+>)?\s+\w+\s*,',
                ', ',
                full_params,
                flags=re.DOTALL
            )
            cleaned_params = re.sub(
                r'^\s*ProxyExchange(?:<[^>]+>)?\s+\w+\s*,\s*',
                '',
                cleaned_params,
                flags=re.DOTALL
            )
            cleaned_params = re.sub(
                r',\s*ProxyExchange(?:<[^>]+>)?\s+\w+\s*$',
                '',
                cleaned_params,
                flags=re.DOTALL
            )
            cleaned_params = re.sub(r'^\s*,\s*', '', cleaned_params)
            cleaned_params = re.sub(r'\s*,\s*$', '', cleaned_params)
            cleaned_params = re.sub(r',\s*,', ', ', cleaned_params)
            code = code.replace(f'({full_params})', f'({cleaned_params})', 1)
            if arg_name != 'proxy':
                code = re.sub(rf'\b{re.escape(arg_name)}\b', 'proxy', code)

        if 'private ProxyExchange<byte[]> proxy;' not in code and 'private ProxyExchange<?> proxy;' not in code:
            field_decl = '\n    @Inject\n    private ProxyExchange<byte[]> proxy;\n'
            class_match = re.search(r'public\s+class\s+\w+[^\{]*\{', code)
            if class_match:
                code = code[:class_match.end()] + field_decl + code[class_match.end():]

        if f'import {support_import};' not in code:
            code = re.sub(
                r'(package\s+[^;]+;\s*\n)',
                rf'\1\nimport {support_import};\n',
                code,
                count=1
            )

        return code

    def _is_resource_controller(self, code: str) -> bool:
        """Return True when the class looks like a JAX-RS/Spring MVC resource class."""
        package_match = re.search(r'package\s+([^;]+);', code)
        current_package = package_match.group(1) if package_match else ''
        class_match = re.search(r'public\s+class\s+(\w+)', code)
        class_name = class_match.group(1) if class_match else ''
        return (
            '.controller' in current_package
            or class_name.endswith('Controller')
            or '@Path(' in code
            or '@RestController' in code
            or '@RequestMapping' in code
        )

    def _shared_proxy_support_package(self, current_package: str) -> str:
        """Resolve a shared support package so controllers and services use one shim type."""
        for marker in ['.controller.', '.service.', '.config.']:
            if marker in current_package:
                return current_package.split(marker, 1)[0] + '.support'
        for suffix in ['.controller', '.service', '.config']:
            if current_package.endswith(suffix):
                return current_package[:-len(suffix)] + '.support'
        return f'{current_package}.support'

    def _transform_helidon_se_controller(self, code: str) -> str:
        """Convert Helidon SE/webserver-style controller output to Helidon MP JAX-RS resources."""
        se_markers = ['io.helidon.webserver', 'ServerRequest', 'Routing', 'request.response().send']
        if not any(marker in code for marker in se_markers):
            return code

        resolved_constants = self._resolve_string_constants(code)
        base_path = resolved_constants.get('VERSION')
        if base_path and base_path.startswith('/') and '@Path(' not in code:
            code = re.sub(
                r'(@ApplicationScoped\s*\n)(public\s+class\s+\w+)',
                rf'\1@Path("{base_path}")' + '\n' + r'\2',
                code,
                count=1
            )

        code = re.sub(r'import\s+io\.helidon\.common\.http\.Http;\s*\n?', '', code)
        code = re.sub(r'import\s+io\.helidon\.security\.Subject;\s*\n?', '', code)
        code = re.sub(r'import\s+io\.helidon\.webserver\.[^;]+;\s*\n?', '', code)
        code = re.sub(r'import\s+java\.util\.Objects;\s*\n?', '', code)

        code = self._replace_method(
            code,
            r'public\s+void\s+register\s*\(\s*Routing\s+\w+\s*\)\s*\{',
            ''
        )
        code = self._replace_method(
            code,
            r'private\s+void\s+\w*ControllerHandler\s*\(\s*ServerRequest\s+\w+\s*\)\s*\{',
            ''
        )

        method_pattern = re.compile(
            r'private\s+void\s+(handle\w+)\s*\(([^)]*)\)\s*\{',
            re.MULTILINE
        )

        cursor = 0
        rewritten = []
        while True:
            match = method_pattern.search(code, cursor)
            if not match:
                rewritten.append(code[cursor:])
                break

            body_start = match.end() - 1
            body_end = self._find_matching_brace(code, body_start)
            if body_end == -1:
                rewritten.append(code[cursor:])
                break

            rewritten.append(code[cursor:match.start()])
            method_name = match.group(1)
            raw_params = match.group(2)
            body = code[body_start + 1:body_end]

            http_verb = self._infer_http_verb(method_name)
            route_path = self._infer_route_path(method_name, resolved_constants)
            if base_path and route_path and route_path.startswith(base_path):
                route_path = route_path[len(base_path):] or '/'
            if not route_path:
                route_path = '/'

            signature_params = []
            path_params = []
            for path_param in re.findall(r'request\.pathParams\("([^"]+)"\)', body):
                if path_param not in path_params:
                    path_params.append(path_param)
            for path_param in path_params:
                signature_params.append(f'@PathParam("{path_param}") String {path_param}')
                body = re.sub(
                    rf'String\s+(\w+)\s*=\s*request\.pathParams\("{re.escape(path_param)}"\);',
                    rf'String \1 = {path_param};',
                    body
                )

            if 'subject.principal().get()' in body:
                signature_params.append(f'@HeaderParam(IDCS_USER_ID_HEADER) String idcsUserId')
                body = body.replace('subject.principal().get()', 'idcsUserId')

            if 'getAllHeaders(request)' in body:
                signature_params.append('@Context HttpHeaders headers')
                body = re.sub(
                    r'List<String>\s+(\w+)\s*=\s*getAllHeaders\(request\)\.getOrEmpty\(([^)]+)\);',
                    r'List<String> \1 = headers.getRequestHeader(\2);\n    if (\1 == null) {\n      \1 = java.util.Collections.emptyList();\n    }',
                    body
                )

            if 'oudpTenantConfig' in body and 'OudpTenantConfig oudpTenantConfig' not in raw_params and 'OudpTenantConfig oudpTenantConfig' not in body:
                signature_params.append('OudpTenantConfig oudpTenantConfig')

            body = re.sub(r'request\.response\(\)\.send\((.+?)\);', r'return \1;', body)
            body = body.replace('ServerRequest request, ', '')
            body = body.replace(', Subject subject', '')
            body = body.replace('Subject subject', '')
            body = re.sub(r'(?m)^\s*return;\s*$', '        return Response.noContent().build();', body)
            body = re.sub(r'\n\s*\n\s*\n+', '\n\n', body)

            annotations = [f'@{http_verb}', f'@Path("{route_path}")']
            if http_verb in {'POST', 'PUT', 'PATCH'} and 'OudpTenantConfig oudpTenantConfig' in signature_params:
                annotations.append('@Consumes(MediaType.APPLICATION_JSON)')

            method_block = (
                "    " + "\n    ".join(annotations) + "\n"
                + f"    public Response {method_name}({', '.join(signature_params)}) {{\n"
                + body
                + "\n    }"
            )
            rewritten.append(method_block)
            cursor = body_end + 1

        code = ''.join(rewritten)
        code = re.sub(r'private\s+static\s+final\s+String\s+\w+\s*=\s*"(GET|POST|PUT|DELETE|PATCH)";\s*\n', '', code)
        code = re.sub(r'\n{3,}', '\n\n', code)
        return code

    def _resolve_string_constants(self, code: str) -> Dict[str, str]:
        """Resolve simple Java string constants built from concatenated literals and other constants."""
        raw_constants = {}
        for name, expression in re.findall(r'private\s+static\s+final\s+String\s+(\w+)\s*=\s*(.+?);', code):
            raw_constants[name] = expression.strip()

        resolved = {}
        for _ in range(10):
            changed = False
            for name, expression in raw_constants.items():
                if name in resolved:
                    continue
                value = self._resolve_string_expression(expression, resolved)
                if value is not None:
                    resolved[name] = value
                    changed = True
            if not changed:
                break
        return resolved

    def _resolve_string_expression(self, expression: str, resolved_constants: Dict[str, str]) -> str | None:
        """Resolve a simple concatenated string expression."""
        parts = [part.strip() for part in expression.split('+')]
        resolved_parts = []
        for part in parts:
            if re.fullmatch(r'"[^"]*"', part):
                resolved_parts.append(part[1:-1])
            elif part in resolved_constants:
                resolved_parts.append(resolved_constants[part])
            else:
                return None
        return ''.join(resolved_parts)

    def _infer_http_verb(self, method_name: str) -> str:
        """Infer HTTP verb from a handler method name."""
        lowered = method_name.lower()
        if 'create' in lowered or 'post' in lowered:
            return 'POST'
        if 'delete' in lowered or 'remove' in lowered:
            return 'DELETE'
        if 'update' in lowered or 'put' in lowered:
            return 'PUT'
        if 'patch' in lowered:
            return 'PATCH'
        return 'GET'

    def _infer_route_path(self, method_name: str, resolved_constants: Dict[str, str]) -> str | None:
        """Infer a JAX-RS path for a generated SE handler from known route constants."""
        method_tokens = self._tokenize_identifier(method_name)
        best_match = None
        best_score = float('-inf')

        for constant_name, constant_value in resolved_constants.items():
            if not constant_value.startswith('/') or constant_name == 'VERSION':
                continue

            candidate_tokens = set(self._tokenize_identifier(constant_name) + self._tokenize_identifier(constant_value))
            overlap = len(set(method_tokens) & candidate_tokens)
            score = overlap * 10 - len(candidate_tokens)
            if score > best_score:
                best_match = constant_value
                best_score = score

        return best_match

    def _tokenize_identifier(self, value: str) -> List[str]:
        """Split identifier-like values into lowercase tokens."""
        normalized = re.sub(r'[^A-Za-z0-9]+', ' ', value)
        pieces = []
        for token in normalized.split():
            split_token = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', token)
            split_token = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', split_token)
            pieces.extend(part.lower() for part in split_token.split())
        return pieces

    def _transform_http_utilities(self, code: str) -> str:
        """Normalize Spring HTTP helper types and invalid Response usage to Jakarta forms."""
        if not any(marker in code for marker in ['HttpHeaders', 'MultiValueMap', 'LinkedMultiValueMap', 'Status.', 'HttpStatus.valueOf(', 'new Response(']):
            return code

        code = re.sub(r'import\s+org\.springframework\.http\.HttpHeaders;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.util\.MultiValueMap;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.util\.LinkedMultiValueMap;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.http\.HttpStatus;\s*\n?', '', code)

        code = code.replace('@Context HttpHeaders', '@Context __JAXRS_HTTP_HEADERS__')
        code = re.sub(
            r'(?<!@Context )\bHttpHeaders\b',
            'MultivaluedMap<String, String>',
            code
        )
        code = code.replace('@Context __JAXRS_HTTP_HEADERS__', '@Context HttpHeaders')

        code = re.sub(
            r'\bMultivaluedMap<String, String>\s+(\w+)\s*=\s*new\s+MultivaluedMap<String, String>\(\s*\)\s*;',
            r'MultivaluedMap<String, String> \1 = new MultivaluedHashMap<>();',
            code
        )
        code = re.sub(
            r'\bMultivaluedMap<String, String>\s+(\w+)\s*=\s*new\s+HttpHeaders\(\s*\)\s*;',
            r'MultivaluedMap<String, String> \1 = new MultivaluedHashMap<>();',
            code
        )
        code = re.sub(
            r'\bMultivaluedMap<String, String>\s+(\w+)\s*=\s*new\s+LinkedMultiValueMap(?:<[^>]*>)?\(\s*\)\s*;',
            r'MultivaluedMap<String, String> \1 = new MultivaluedHashMap<>();',
            code
        )
        code = re.sub(
            r'\bMultiValueMap\s*<\s*String\s*,\s*String\s*>\s+(\w+)\s*=\s*new\s+LinkedMultiValueMap(?:<[^>]*>)?\(\s*\)\s*;',
            r'MultivaluedMap<String, String> \1 = new MultivaluedHashMap<>();',
            code
        )
        code = re.sub(
            r'\bMultiValueMap\s*<\s*String\s*,\s*String\s*>\b',
            'MultivaluedMap<String, String>',
            code
        )
        code = re.sub(
            r'\bLinkedMultiValueMap(?:<[^>]*>)?\s*\(\s*\)',
            'MultivaluedHashMap<>()',
            code
        )

        header_vars = set(
            re.findall(r'\b(?:MultivaluedMap<String,\s*String>|MultiValueMap<\s*String\s*,\s*String\s*>)\s+(\w+)\b', code)
        )
        for header_var in header_vars:
            code = re.sub(rf'\b{re.escape(header_var)}\.set\(', f'{header_var}.putSingle(', code)
            code = re.sub(rf'\b{re.escape(header_var)}\.add\(', f'{header_var}.putSingle(', code)

        code = re.sub(
            r'HttpHeaders\.([A-Z0-9_]+)',
            lambda match: f'"{self._http_header_constant(match.group(1))}"',
            code
        )
        code = re.sub(
            r'MultivaluedMap<String,\s*String>\.([A-Z0-9_]+)',
            lambda match: f'"{self._http_header_constant(match.group(1))}"',
            code
        )
        code = re.sub(
            r'MediaType\.([A-Z0-9_]+)\.toString\(\)',
            r'MediaType.\1',
            code
        )
        code = re.sub(
            r'HttpStatus\.valueOf\(([^)]+)\)',
            r'Response.Status.fromStatusCode(\1)',
            code
        )
        code = re.sub(
            r'HttpStatus\.resolve\(([^)]+)\)',
            r'Response.Status.fromStatusCode(\1)',
            code
        )
        code = re.sub(
            r'HttpStatus\.([A-Z_]+)\.value\(\)',
            r'Response.Status.\1.getStatusCode()',
            code
        )
        code = re.sub(
            r'\bHttpStatus\b',
            'Response.Status',
            code
        )
        code = re.sub(
            r'Response\.Status\.([A-Z_]+)\.value\(\)',
            r'Response.Status.\1.getStatusCode()',
            code
        )
        code = re.sub(
            r'Response\.Status\.valueOf\(([^)]+)\)',
            r'Response.Status.fromStatusCode(\1)',
            code
        )

        code = self._normalize_response_statuses(code)
        code = self._rewrite_invalid_response_constructors(code)
        return code

    def _transform_bean_utils_copy(self, code: str) -> str:
        """Replace Spring BeanUtils.copyProperties with a local reflection helper."""
        if 'BeanUtils.copyProperties(' not in code:
            return code

        package_match = re.search(r'package\s+([^;]+);', code)
        current_package = package_match.group(1) if package_match else 'com.example.demo'
        support_package = self._shared_proxy_support_package(current_package)
        support_import = f'import {support_package}.PropertyCopySupport;\n'

        code = re.sub(r'import\s+org\.springframework\.beans\.BeanUtils;\s*\n?', '', code)
        code = code.replace('BeanUtils.copyProperties(', 'PropertyCopySupport.copyProperties(')

        if support_import not in code:
            package_decl = re.search(r'package\s+[^;]+;\s*\n', code)
            insert_pos = package_decl.end() if package_decl else 0
            code = code[:insert_pos] + '\n' + support_import + code[insert_pos:]

        self._generate_property_copy_support(support_package)
        return code

    def _transform_request_abstractions(self, code: str) -> str:
        """Normalize servlet/JAX-RS request handling helpers for Helidon MP."""
        request_markers = ['HttpServletRequest', 'UriComponentsBuilder', '.getOrEmpty(']
        if not any(marker in code for marker in request_markers):
            return code

        if '@Path' in code:
            code = re.sub(
                r'(?<!@Context\s)\bHttpServletRequest\s+(\w+)',
                r'@Context HttpServletRequest \1',
                code
            )
            code = re.sub(
                r'(?<!@Context\s)\bUriInfo\s+(\w+)',
                r'@Context UriInfo \1',
                code
            )
            code = re.sub(
                r'(?<!@Context\s)\bHttpHeaders\s+(\w+)',
                r'@Context HttpHeaders \1',
                code
            )

        code = re.sub(
            r'([A-Za-z_][\w]*(?:\([^)]*\))?)\.getOrEmpty\(([^)]+)\)',
            r'java.util.Optional.ofNullable(\1.get(\2)).orElse(java.util.Collections.emptyList())',
            code
        )

        code = re.sub(r'import\s+org\.springframework\.web\.util\.UriComponentsBuilder;\s*\n?', '', code)
        if 'UriComponentsBuilder' in code:
            code = code.replace('UriComponentsBuilder', 'UriBuilder')
            code = re.sub(
                r'(\w+)\s*=\s*UriBuilder\.newInstance\(\)\s*'
                r'\.scheme\(([^)]+)\)\s*'
                r'\.host\(([^)]+)\)\s*'
                r'\.path\(([^)]+)\)\s*'
                r'\.query\(([^)]+)\)\s*;',
                r'\1 = UriBuilder.fromUri(mcpsBaseUrl).path(\4).replaceQuery(\5);',
                code,
                flags=re.DOTALL
            )
            code = code.replace('.query(', '.replaceQuery(')

        code = self._replace_method(
            code,
            r'public\s+URI\s+composeTargetUri\s*\(\s*(?:@Context\s+)?HttpServletRequest\s+\w+\s*,\s*String\s+\w+\s*\)\s*\{',
            '''public URI composeTargetUri(HttpServletRequest request, String mcpsBaseUrl) {
        String queryParams = request.getQueryString();
        if (queryParams != null) {
            queryParams = java.net.URLDecoder.decode(request.getQueryString(), StandardCharsets.UTF_8);
        }
        log.info("QueryParams: {} ", queryParams);
        try {
            return UriBuilder.fromUri(mcpsBaseUrl)
                    .path(request.getRequestURI())
                    .replaceQuery(queryParams)
                    .build();
        } catch (IllegalArgumentException e) {
            log.error("Error building target URI {}", e.getMessage());
        }
        return null;
    }'''
        )
        return code

    def _transform_parameter_annotation_aspects(self, code: str) -> str:
        """Rewrite Spring parameter-annotation AOP into explicit CDI helper calls."""
        if 'public @interface ' in code:
            code = self._transform_interceptor_binding_annotation(code)

        if '@Around(' in code and 'ProceedingJoinPoint' in code:
            code = self._rewrite_parameter_annotation_aspect_helper(code)

        parameter_annotations = sorted({
            match.group(1)
            for match in re.finditer(r'@(\w+)\s*@Context\s+HttpServletRequest\s+([A-Za-z_]\w*)', code)
            if match.group(1) not in {'Context'}
        })
        if not parameter_annotations or 'public @interface ' in code:
            return code

        for annotation_name in parameter_annotations:
            code = self._rewrite_parameter_annotation_usage(code, annotation_name)

        return code

    def _transform_interceptor_binding_annotation(self, code: str) -> str:
        """Convert companion annotations for AspectJ parameter aspects into CDI interceptor bindings."""
        annotation_match = re.search(r'public\s+@interface\s+(\w+)', code)
        if not annotation_match:
            return code

        annotation_name = annotation_match.group(1)
        if not self._has_companion_aspect(annotation_name):
            return code

        if '@InterceptorBinding' not in code:
            package_match = re.search(r'package\s+[^;]+;\s*\n', code)
            insert_pos = package_match.end() if package_match else 0
            code = code[:insert_pos] + '\nimport jakarta.interceptor.InterceptorBinding;\n' + code[insert_pos:]

        if '@Inherited' not in code:
            code = re.sub(
                r'(import\s+java\.lang\.annotation\.RetentionPolicy;\s*\n)',
                r'\1import java.lang.annotation.Inherited;\n',
                code,
                count=1
            )

        if '@Inherited' not in code and '@Retention(' in code:
            code = code.replace('@Retention(', '@Inherited\n@Retention(', 1)
        annotation_decl_match = re.search(r'public\s+@interface\s+\w+', code)
        annotation_prefix = code[:annotation_decl_match.start()] if annotation_decl_match else code
        if '@InterceptorBinding' not in annotation_prefix and '@Retention(' in code:
            code = code.replace('@Retention(', '@InterceptorBinding\n@Retention(', 1)

        code = re.sub(
            r'@Target\(\{\s*ElementType\.PARAMETER\s*,\s*ElementType\.FIELD\s*\}\)',
            '@Target({ ElementType.METHOD, ElementType.TYPE })',
            code
        )
        code = re.sub(
            r'@Target\(\{\s*ElementType\.FIELD\s*,\s*ElementType\.PARAMETER\s*\}\)',
            '@Target({ ElementType.METHOD, ElementType.TYPE })',
            code
        )
        return code

    def _has_companion_aspect(self, annotation_name: str) -> bool:
        """Return True when the workspace contains a matching Aspect class for the annotation."""
        aspect_file = f'{annotation_name}Aspect.java'
        for root_attr in ['source_path', 'target_path']:
            root = getattr(self, root_attr, None)
            if not root:
                continue
            try:
                if any(candidate.name == aspect_file for candidate in Path(root).rglob(aspect_file)):
                    return True
            except Exception:
                continue
        return False

    def _rewrite_parameter_annotation_aspect_helper(self, code: str) -> str:
        """Convert AspectJ parameter advice into a CDI interceptor with parameter rewriting."""
        around_match = re.search(
            r'@Around\(\s*"execution\(public \* \*\(\.\., @(\w+) \(\*\), \.\.\)\)"\s*\)',
            code
        )
        if not around_match:
            return code

        annotation_name = around_match.group(1)
        helper_method_match = re.search(
            r'public\s+HttpServletRequest\s+(\w+)\s*\(\s*(?:final\s+)?HttpServletRequest\s+([A-Za-z_]\w*)\s*\)\s*(?:throws\s+[^{]+)?\{',
            code
        )
        helper_method_name = helper_method_match.group(1) if helper_method_match else None

        code = re.sub(r'import\s+org\.aspectj\.lang\.ProceedingJoinPoint;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.aspectj\.lang\.annotation\.Around;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.aspectj\.lang\.annotation\.Aspect;\s*\n?', '', code)
        code = re.sub(r'^\s*@Aspect\s*\n', '', code, flags=re.MULTILINE)

        package_match = re.search(r'package\s+[^;]+;\s*\n', code)
        insert_pos = package_match.end() if package_match else 0
        required_imports = [
            'import jakarta.annotation.Priority;\n',
            'import jakarta.interceptor.AroundInvoke;\n',
            'import jakarta.interceptor.Interceptor;\n',
            'import jakarta.interceptor.InvocationContext;\n',
        ]
        for import_line in required_imports:
            if import_line not in code:
                code = code[:insert_pos] + '\n' + import_line + code[insert_pos:]
                insert_pos += len('\n' + import_line)

        advice_signature = (
            r'@Around\(\s*"execution\(public \* \*\(\.\., @'
            + re.escape(annotation_name)
            + r' \(\*\), \.\.\)\)"\s*\)\s*'
            r'public\s+Object\s+\w+\s*\(\s*ProceedingJoinPoint\s+\w+\s*\)\s*throws\s+[^{]+\{'
        )
        replacement_method = f'''@AroundInvoke
    public Object updateQueryParameter(InvocationContext ctx) throws Exception {{
        Object[] args = ctx.getParameters();
        Object[] newArgs = new Object[args.length];

        for (int i = 0; i < args.length; i++) {{
            if (args[i] instanceof jakarta.servlet.ServletRequest) {{
                HttpServletRequest httpRequest = (HttpServletRequest) args[i];
                if (httpRequest.getMethod().equals("GET")) {{
                    log.debug("updating request");
                    newArgs[i] = {helper_method_name}(httpRequest);
                }} else {{
                    newArgs[i] = args[i];
                }}
            }} else {{
                newArgs[i] = args[i];
            }}
        }}
        ctx.setParameters(newArgs);
        return ctx.proceed();
    }}'''
        code = self._replace_method(code, advice_signature, replacement_method)

        class_match = re.search(r'public\s+class\s+\w+', code)
        if class_match:
            prefix = code[:class_match.start()]
            if '@Interceptor' not in prefix[-400:]:
                interceptor_prefix = f'@Interceptor\n@{annotation_name}\n@Priority(Interceptor.Priority.APPLICATION)\n'
                code = code[:class_match.start()] + interceptor_prefix + code[class_match.start():]

        return code

    def _rewrite_parameter_annotation_usage(self, code: str, annotation_name: str) -> str:
        """Move custom parameter annotations to method-level interceptor bindings."""
        class_match = re.search(r'public\s+class\s+(\w+)[^\{]*\{', code)
        if class_match and class_match.group(1) == f'{annotation_name}Aspect':
            return code

        method_pattern = re.compile(
            r'((?:\s*@\w+(?:\((?:[^()\n]|\([^()\n]*\))*\))?\s*\n)+)'
            r'(\s*(?:public|protected|private)\s+[A-Za-z_][\w<>,\[\]\.? ]*\s+\w+\s*\((?:[^()]|\([^)]*\))*\)\s*(?:throws\s+[^{]+)?\s*\{)',
            re.MULTILINE
        )

        cursor = 0
        rewritten = []
        while True:
            match = method_pattern.search(code, cursor)
            if not match:
                rewritten.append(code[cursor:])
                break

            signature = match.group(2)
            block_start = match.start(2)
            body_start = match.end(2) - 1
            body_end = self._find_matching_brace(code, body_start)
            if body_end == -1:
                rewritten.append(code[cursor:])
                break

            body = code[body_start + 1:body_end]
            rewritten.append(code[cursor:block_start])

            request_param_match = re.search(
                rf'@{re.escape(annotation_name)}\s*((?:@\w+(?:\([^)]*\))?\s*)*)HttpServletRequest\s+([A-Za-z_]\w*)',
                signature
            )
            if not request_param_match:
                rewritten.append(code[block_start:body_end + 1])
                cursor = body_end + 1
                continue

            new_signature = re.sub(rf'@{re.escape(annotation_name)}\s*', '', signature)
            annotation_block = match.group(1)
            if f'@{annotation_name}' not in annotation_block:
                annotation_block = annotation_block + f'    @{annotation_name}\n'
            rewritten.append(f'{annotation_block}{new_signature}{body}}}')
            cursor = body_end + 1

        return ''.join(rewritten)

    def _http_header_constant(self, constant_name: str) -> str:
        """Map Spring HttpHeaders constants to wire header names."""
        known_headers = {
            'ACCEPT': 'Accept',
            'AUTHORIZATION': 'Authorization',
            'CACHE_CONTROL': 'Cache-Control',
            'CONTENT_DISPOSITION': 'Content-Disposition',
            'CONTENT_ENCODING': 'Content-Encoding',
            'CONTENT_LANGUAGE': 'Content-Language',
            'CONTENT_LENGTH': 'Content-Length',
            'CONTENT_TYPE': 'Content-Type',
            'COOKIE': 'Cookie',
            'ETAG': 'ETag',
            'HOST': 'Host',
            'IF_MATCH': 'If-Match',
            'IF_MODIFIED_SINCE': 'If-Modified-Since',
            'IF_NONE_MATCH': 'If-None-Match',
            'LAST_MODIFIED': 'Last-Modified',
            'LOCATION': 'Location',
            'SET_COOKIE': 'Set-Cookie',
            'USER_AGENT': 'User-Agent',
        }
        if constant_name in known_headers:
            return known_headers[constant_name]
        return '-'.join(part.capitalize() for part in constant_name.split('_'))

    def _normalize_response_statuses(self, code: str) -> str:
        """Map bare Status constants to valid JAX-RS Response.Status values."""
        status_map = {
            'ACCEPTED': 'Response.Status.ACCEPTED',
            'BAD_REQUEST': 'Response.Status.BAD_REQUEST',
            'CONFLICT': 'Response.Status.CONFLICT',
            'CREATED': 'Response.Status.CREATED',
            'FORBIDDEN': 'Response.Status.FORBIDDEN',
            'INTERNAL_SERVER_ERROR': 'Response.Status.INTERNAL_SERVER_ERROR',
            'NOT_FOUND': 'Response.Status.NOT_FOUND',
            'NO_CONTENT': 'Response.Status.NO_CONTENT',
            'OK': 'Response.Status.OK',
            'SERVER_ERROR': 'Response.Status.INTERNAL_SERVER_ERROR',
            'UNAUTHORIZED': 'Response.Status.UNAUTHORIZED',
        }
        for original, replacement in status_map.items():
            code = re.sub(rf'(?<!Response\.)\bStatus\.{original}\b', replacement, code)
            if original == 'SERVER_ERROR':
                code = code.replace('Response.Status.SERVER_ERROR', replacement)
        return code

    def _rewrite_invalid_response_constructors(self, code: str) -> str:
        """Replace invalid new Response(...) constructor usage with builder calls."""
        status_first_pattern = re.compile(
            r'new\s+Response(?:<[^>]*>)?\s*\(\s*(.+?)\s*,\s*(.+?)\s*,\s*null\s*\)',
            re.DOTALL
        )

        def replace_status_first(match):
            first_arg = match.group(1).strip()
            second_arg = match.group(2).strip()
            if 'Response.Status.' in first_arg:
                if second_arg == 'null':
                    return f'Response.status({first_arg}).build()'
                return f'Response.status({first_arg}).entity({second_arg}).build()'
            return f'Response.ok({first_arg}).build()'

        status_last_pattern = re.compile(
            r'new\s+Response(?:<[^>]*>)?\s*\(\s*(.+?)\s*,\s*(.+?)\s*,\s*(Response\.Status(?:\.[A-Z_]+|\.fromStatusCode\([^)]+\)))\s*\)',
            re.DOTALL
        )

        def replace_status_last(match):
            entity_arg = match.group(1).strip()
            status_arg = match.group(3).strip()
            return f'Response.status({status_arg}).entity({entity_arg}).build()'

        code = status_first_pattern.sub(replace_status_first, code)
        code = status_last_pattern.sub(replace_status_last, code)
        return code

    def _transform_test_support(self, code: str) -> str:
        """Convert Spring test scaffolding and exception types to portable alternatives."""
        test_markers = [
            'SpringBootTest',
            'SpringExtension',
            'SpringRunner',
            'AutoConfigureMockMvc',
            'TestPropertySource',
            'BeforeTestClass',
            'ReflectionTestUtils',
            'DataIntegrityViolationException',
            'RestClientException',
        ]
        if not any(marker in code for marker in test_markers):
            return code

        code = re.sub(r'import\s+org\.springframework\.boot\.test\.context\.SpringBootTest;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.test\.context\.junit\.jupiter\.SpringExtension;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.test\.context\.junit4\.SpringRunner;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.boot\.test\.autoconfigure\.web\.servlet\.AutoConfigureMockMvc;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.test\.context\.TestPropertySource;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.test\.context\.event\.annotation\.BeforeTestClass;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.test\.util\.ReflectionTestUtils;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.dao\.DataIntegrityViolationException;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.web\.client\.RestClientException;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.junit\.runner\.RunWith;\s*\n?', '', code)

        code = re.sub(r'^\s*@SpringBootTest(?:\([^)]*\))?\s*\n', '', code, flags=re.MULTILINE)
        code = code.replace('@ExtendWith(SpringExtension.class)', '@ExtendWith(MockitoExtension.class)')
        code = re.sub(r'@RunWith\s*\(\s*SpringRunner\.class\s*\)\s*\n?', '', code)
        code = re.sub(r'^\s*@AutoConfigureMockMvc\s*\n', '', code, flags=re.MULTILINE)
        code = re.sub(r'^\s*@TestPropertySource\([^)]*\)\s*\n', '', code, flags=re.MULTILINE)
        code = code.replace('@BeforeTestClass', '@BeforeAll')
        code = code.replace('DataIntegrityViolationException', 'PersistenceException')
        code = code.replace('RestClientException', 'ProcessingException')
        code = code.replace('ReflectionTestUtils.setField(', '_setField(')
        code = code.replace('.getStatusCodeValue()', '.getStatus()')
        code = re.sub(
            r'(\w+)\.getStatusCode\(\)\.equals\((Response\.Status\.[A-Z_]+)\)',
            r'\1.getStatus() == \2.getStatusCode()',
            code
        )
        code = re.sub(
            r'when\(([^)]+)\.getStatusCode\(\)\)\.thenReturn\(Response\.Status\.fromStatusCode\(([^)]+)\)\)',
            r'when(\1.getStatus()).thenReturn(\2)',
            code
        )
        code = re.sub(
            r'when\(([^)]+)\.getStatusCode\(\)\)\.thenReturn\(HttpStatus\.valueOf\(([^)]+)\)\)',
            r'when(\1.getStatus()).thenReturn(\2)',
            code
        )
        code = re.sub(
            r'when\(([^)]+)\.getStatusCode\(\)\)\.thenReturn\((Response\.Status\.[A-Z_]+)\)',
            r'when(\1.getStatus()).thenReturn(\2.getStatusCode())',
            code
        )
        code = re.sub(
            r'(@ExtendWith\(MockitoExtension\.class\)\s*\n)+',
            '@ExtendWith(MockitoExtension.class)\n',
            code
        )

        if '_setField(' in code and 'private static void _setField(' not in code:
            helper = '''

    private static void _setField(Object target, String fieldName, Object value) {
        try {
            java.lang.reflect.Field field = target.getClass().getDeclaredField(fieldName);
            field.setAccessible(true);
            field.set(target, value);
        } catch (ReflectiveOperationException ex) {
            throw new RuntimeException(ex);
        }
    }
'''
            code = re.sub(r'\n}\s*$', helper + '\n}', code)

        return code

    def _transform_spring_configuration(self, code: str) -> str:
        """Transform Spring @Configuration classes to CDI"""
        package_match = re.search(r'package\s+([^;]+);', code)
        current_package = package_match.group(1) if package_match else 'com.example.demo'
        
        # 1. @Configuration -> @ApplicationScoped
        if '@Configuration' in code:
            code = code.replace('@Configuration', '@ApplicationScoped')
            code = re.sub(r'import\s+org\.springframework\.context\.annotation\.Configuration;\s*\n?', '', code)
            code = re.sub(r'import\s+org\.springframework\.cloud\.gateway\.mvc\.config\.ProxyProperties;\s*\n?', '', code)

        if '@ConfigurationProperties' in code:
            datasource_name = self.settings.datasource_name or 'myDS'
            code = re.sub(
                r'@ConfigurationProperties\(\s*"spring\.datasource\.hikari"\s*\)',
                f'@ConfigProperties(prefix = "javax.sql.DataSource.{datasource_name}")',
                code
            )
            code = re.sub(
                r'@ConfigurationProperties\(\s*prefix\s*=\s*"spring\.datasource\.hikari"\s*\)',
                f'@ConfigProperties(prefix = "javax.sql.DataSource.{datasource_name}")',
                code
            )
            code = re.sub(r'import\s+org\.springframework\.boot\.context\.properties\.ConfigurationProperties;\s*\n?', '', code)
            if '@ConfigProperties' in code and 'import org.eclipse.microprofile.config.inject.ConfigProperties;' not in code:
                code = re.sub(
                    r'package\s+[^;]+;\s*\n',
                    lambda m: m.group(0) + '\nimport org.eclipse.microprofile.config.inject.ConfigProperties;\n',
                    code
                )
            
        # 2a. @Bean(name="...") -> @Produces @Named("...")
        bean_name_pattern = r'@Bean\s*\(\s*(?:name\s*=\s*)?"([^"]+)"\s*\)'
        code = re.sub(bean_name_pattern, r'@Produces\n    @Named("\1")', code)
        
        # 2b. @Bean -> @Produces
        if '@Bean' in code:
            code = code.replace('@Bean', '@Produces')
            code = re.sub(r'import\s+org\.springframework\.context\.annotation\.Bean;\s*\n?', '', code)

        # 3. WebMvcConfigurer -> Remove
        if 'WebMvcConfigurer' in code:
            code = re.sub(r'\s+implements\s+WebMvcConfigurer\s*', '', code)
            code = re.sub(r'import\s+org\.springframework\.web\.servlet\.config\.annotation\.WebMvcConfigurer;\s*\n?', '', code)
            code = re.sub(r'@Override\s*\n\s*public\s+void\s+addArgumentResolvers\s*\([^)]*\)\s*\{[^}]*\}\s*', '', code, flags=re.DOTALL)

        # 4. RestTemplate -> JAX-RS Client
        if 'RestTemplate' in code:
             # Imports
            code = re.sub(r'import\s+org\.springframework\.web\.client\.RestTemplate;\s*\n?', '', code)
            if 'jakarta.ws.rs.client.Client' not in code:
                # Add imports after package
                code = re.sub(r'package\s+[^;]+;\s*\n', lambda m: m.group(0) + '\nimport jakarta.ws.rs.client.Client;\nimport jakarta.ws.rs.client.ClientBuilder;\n', code)
            
            # Transform Bean methods signature
            # Match: @Produces public RestTemplate name(...)
            rt_method_pattern = r'(@Produces\s+)(?:public\s+)?RestTemplate\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{'
            def replace_rest_template_sig(match):
                prefix = match.group(1)
                name = match.group(2)
                return f'{prefix}public Client {name}() {{'
            code = re.sub(rt_method_pattern, replace_rest_template_sig, code, flags=re.DOTALL)
            
            # Replace instantiation logic in body
            # 1. RestTemplate restTemplate = ...
            code = re.sub(r'RestTemplate\s+(\w+)\s*=\s*new\s+RestTemplate\([^;]*\);', r'Client \1 = ClientBuilder.newClient();', code)
            # 2. return new RestTemplate(...)
            code = re.sub(r'return\s+new\s+RestTemplate\([^)]*\);', 'return ClientBuilder.newClient();', code)
            
            # Comment out Spring Factories
            if 'SimpleClientHttpRequestFactory' in code:
                code = re.sub(r'(\w*SimpleClientHttpRequestFactory\s+\w+\s*=[^;]+;)', r'// \1', code)
                code = re.sub(r'import\s+org\.springframework\.http\.client\.SimpleClientHttpRequestFactory;\s*\n?', '', code)
            if 'ClientHttpRequestFactory' in code:
                 code = re.sub(r'(\w*ClientHttpRequestFactory\s+\w+\s*=[^;]+;)', r'// \1', code)
                 code = re.sub(r'import\s+org\.springframework\.http\.client\.ClientHttpRequestFactory;\s*\n?', '', code)
            if 'BufferingClientHttpRequestFactory' in code:
                code = re.sub(r'(\w*BufferingClientHttpRequestFactory\s+\w+\s*=[^;]+;)', r'// \1', code)
                code = re.sub(r'import\s+org\.springframework\.http\.client\.BufferingClientHttpRequestFactory;\s*\n?', '', code)

            # Cleanup RestTemplate internal usages (setters) - use .*?; for arguments
            code = re.sub(r'\s*\w+\.setErrorHandler\s*\(.*?\);\s*', '\n', code, flags=re.DOTALL)
            code = re.sub(r'(\w+\.setInterceptors\s*\(.*?\);)', r'// \1', code, flags=re.DOTALL)
            code = re.sub(r'(requestFactory\.setConnectTimeout\s*\(.*?\);)', r'// \1', code, flags=re.DOTALL)
            code = re.sub(r'(requestFactory\.setReadTimeout\s*\(.*?\);)', r'// \1', code, flags=re.DOTALL)
            code = re.sub(r'^\s*//\s*.*(?:SimpleClientHttpRequestFactory|BufferingClientHttpRequestFactory|ClientHttpRequestFactory).*\n?', '', code, flags=re.MULTILINE)
            has_custom_response_error_handler = 'CustomResponseErrorHandler' in code
            code = re.sub(r'import\s+[^;]*CustomResponseErrorHandler;\s*\n?', '', code)
            
            # Global Type Replacement: RestTemplate -> Client (for arguments, fields)
            # Be careful not to replace strings or comments, but here we assume code
            code = re.sub(r'\bRestTemplate\b', 'Client', code)
            if has_custom_response_error_handler:
                support_package = self._shared_proxy_support_package(current_package)
                self._generate_proxy_exchange_client_response_filter(support_package)
                support_import = f'import {support_package}.ProxyExchangeClientResponseFilter;\n'
                if support_import not in code:
                    package_decl = re.search(r'package\s+[^;]+;\s*\n', code)
                    insert_pos = package_decl.end() if package_decl else 0
                    code = code[:insert_pos] + '\n' + support_import + code[insert_pos:]
                if 'private ProxyExchangeClientResponseFilter proxyExchangeClientResponseFilter;' not in code:
                    class_match = re.search(r'public\s+class\s+\w+[^\{]*\{', code)
                    if class_match:
                        field_decl = '\n    @Inject\n    private ProxyExchangeClientResponseFilter proxyExchangeClientResponseFilter;\n'
                        code = code[:class_match.end()] + field_decl + code[class_match.end():]
                code = re.sub(
                    r'Client\s+(\w+)\s*=\s*ClientBuilder\.newClient\(\);',
                    r'Client \1 = ClientBuilder.newBuilder().register(proxyExchangeClientResponseFilter).build();',
                    code,
                    count=1
                )

        # 5. ThreadPoolTaskExecutor -> ExecutorService
        if 'ThreadPoolTaskExecutor' in code:
            # 1. Replace instantiation
            code = re.sub(r'new\s+ThreadPoolTaskExecutor\(\)', 'java.util.concurrent.Executors.newCachedThreadPool()', code)
            # 2. Comment out setters
            code = re.sub(r'(\w+\.setCorePoolSize\([^)]+\);)', r'// \1', code)
            code = re.sub(r'(\w+\.setMaxPoolSize\([^)]+\);)', r'// \1', code)
            code = re.sub(r'(\w+\.setQueueCapacity\([^)]+\);)', r'// \1', code)
            code = re.sub(r'(\w+\.setThreadNamePrefix\([^)]+\);)', r'// \1', code)
            code = re.sub(r'(\w+\.initialize\(\);)', r'// \1', code)
            # 3. Replace Type Name
            code = code.replace('ThreadPoolTaskExecutor', 'java.util.concurrent.ExecutorService')
            code = re.sub(r'import\s+org\.springframework\.scheduling\.concurrent\.ThreadPoolTaskExecutor;\s*\n?', '', code)

        # 6. @EnableAsync -> Document removal
        if '@EnableAsync' in code:
            code = code.replace('@EnableAsync', '// @EnableAsync removed (Use MicroProfile Fault Tolerance @Asynchronous)')
            code = re.sub(r'import\s+org\.springframework\.scheduling\.annotation\.EnableAsync;\s*\n?', '', code)
            
        # 7. Add Imports for CDI Produces/Named if needed
        if '@Produces' in code and 'import jakarta.enterprise.inject.Produces;' not in code:
             code = re.sub(r'package\s+[^;]+;\s*\n', lambda m: m.group(0) + '\nimport jakarta.enterprise.inject.Produces;\n', code)
        if '@Named' in code and 'import jakarta.inject.Named;' not in code:
             code = re.sub(r'package\s+[^;]+;\s*\n', lambda m: m.group(0) + 'import jakarta.inject.Named;\n', code)
             
        code = self._disambiguate_produces_annotations(code)

        # Replace Spring-style ApplicationScopedProperties with MicroProfile ConfigProperties
        if re.search(r'@ApplicationScopedProperties\("spring\.datasource\.hikari"\)', code):
            datasource_name = self.settings.datasource_name or 'default'
            code = re.sub(
                r'@ApplicationScopedProperties\("spring\.datasource\.hikari"\)\s*',
                f'@ConfigProperties(prefix = "javax.sql.DataSource.{datasource_name}")\n',
                code
            )
            if 'import org.eclipse.microprofile.config.inject.ConfigProperties;' not in code:
                code = re.sub(
                    r'package\s+[^;]+;\s*\n',
                    lambda m: m.group(0) + '\nimport org.eclipse.microprofile.config.inject.ConfigProperties;\n',
                    code
                )
        else:
            code = re.sub(r'@ApplicationScopedProperties\([^)]*\)\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.boot\.context\.properties\.ConfigurationProperties;\s*\n?', '', code)
        # Remove any leftover custom ApplicationScopedProperties import
        code = re.sub(r'import\s+.*ApplicationScopedProperties;\s*\n?', '', code)
        code = self._transform_filter_registration_beans(code)

        if '@Produces' in code and '@ApplicationScoped' not in code:
            class_match = re.search(r'(\s*public\s+class\s+\w+)', code)
            if class_match:
                code = code[:class_match.start(1)] + '@ApplicationScoped\n' + code[class_match.start(1):]
            
        return code

    def _transform_filter_registration_beans(self, code: str) -> str:
        """Convert Spring FilterRegistrationBean usage to plain CDI-produced filters."""
        if 'FilterRegistrationBean' not in code:
            return code

        package_match = re.search(r'package\s+([^;]+);', code)
        current_package = package_match.group(1) if package_match else 'com.example.demo'

        code = re.sub(r'import\s+org\.springframework\.boot\.web\.servlet\.FilterRegistrationBean;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.core\.Ordered;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.core\.annotation\.Order;\s*\n?', '', code)
        code = re.sub(r'^\s*@Order\([^)]*\)\s*\n', '', code, flags=re.MULTILINE)
        code = re.sub(r'^\s*//.*Filter ordering.*\n', '', code, flags=re.MULTILINE)
        if 'import jakarta.annotation.Priority;' not in code:
            package_match = re.search(r'package\s+[^;]+;\s*\n', code)
            insert_pos = package_match.end() if package_match else 0
            code = code[:insert_pos] + '\nimport jakarta.annotation.Priority;\n' + code[insert_pos:]

        field_pattern = re.compile(
            r'@(Autowired|Inject)\s+public\s+FilterRegistrationBean<([^>]+)>\s+(\w+);'
        )
        code = field_pattern.sub(r'@Inject\n    private \2 \3;', code)

        method_pattern = re.compile(
            r'((?:\s*@\w+(?:\([^)]*\))?\s*\n)*)'
            r'(\s*(?:public|protected|private)\s+)FilterRegistrationBean<([^>]+)>\s+(\w+)\s*\(([^)]*)\)\s*\{',
            re.MULTILINE
        )

        cursor = 0
        rewritten = []
        while True:
            match = method_pattern.search(code, cursor)
            if not match:
                rewritten.append(code[cursor:])
                break

            body_start = match.end() - 1
            body_end = self._find_matching_brace(code, body_start)
            if body_end == -1:
                rewritten.append(code[cursor:])
                break

            rewritten.append(code[cursor:match.start()])
            annotations = match.group(1)
            visibility = match.group(2)
            filter_type = match.group(3).strip()
            method_name = match.group(4)
            params = match.group(5)
            body = code[body_start + 1:body_end]

            filter_expr = self._extract_filter_expression(body)
            if not filter_expr:
                filter_expr = f'new {filter_type}()'

            special_filter_block, code = self._build_special_filter_registration_block(
                code=code,
                current_package=current_package,
                annotations=annotations,
                visibility=visibility,
                filter_type=filter_type,
                method_name=method_name,
                params=params,
                body=body,
                filter_expr=filter_expr,
            )
            if special_filter_block is not None:
                rewritten.append(special_filter_block)
                cursor = body_end + 1
                continue

            new_body_lines = []
            if '@Named("' not in annotations:
                annotations = annotations + f'    @Named("{method_name}")\n'
            order_match = re.search(r'\w+\.setOrder\(([^)]+)\);', body)
            if order_match and '@Priority(' not in annotations:
                annotations = annotations + f'    @Priority({order_match.group(1).strip()})\n'
            preserved_lines = self._extract_filter_setup_statements(body)
            for preserved_line in preserved_lines:
                new_body_lines.append(f'        {preserved_line}')
            metadata_comments = self._extract_filter_registration_comments(body)
            for comment in metadata_comments:
                new_body_lines.append(f'        // TODO Manual registration review: {comment}')
            new_body_lines.append(f'        return {filter_expr};')

            self._generate_mp_filter_registration(
                current_package=current_package,
                source_code=code,
                method_name=method_name,
                filter_type=filter_type,
                order_value=order_match.group(1).strip() if order_match else None,
                metadata_comments=metadata_comments,
            )

            method_block = (
                f"{annotations}{visibility}{filter_type} {method_name}({params}) {{\n"
                + "\n".join(new_body_lines)
                + "\n    }"
            )
            rewritten.append(method_block)
            cursor = body_end + 1

        code = ''.join(rewritten)
        code = re.sub(r'\bFilterRegistrationBean<[^>]+>\b', '', code)
        code = re.sub(r'\bFilterRegistrationBean\b', '', code)
        code = re.sub(r'import\s+org\.apache\.commons\.lang3\.ObjectUtils;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.apache\.commons\.lang3\.StringUtils;\s*\n?', '', code)
        code = re.sub(r'import\s+[^;]*ServletResponseFilter;\s*\n?', '', code)
        code = re.sub(r'import\s+lombok\.Setter;\s*\n?', '', code) if '@Setter' not in code else code
        code = re.sub(r'\n{3,}', '\n\n', code)
        return code

    def _build_special_filter_registration_block(
        self,
        code: str,
        current_package: str,
        annotations: str,
        visibility: str,
        filter_type: str,
        method_name: str,
        params: str,
        body: str,
        filter_expr: str,
    ) -> tuple[str | None, str]:
        """Handle specific servlet-style registrations that need Helidon MP-native equivalents."""
        if filter_type != 'ServletResponseFilter':
            return None, code

        constructor_match = re.match(r'new\s+ServletResponseFilter\((.+)\)$', filter_expr)
        if not constructor_match:
            return None, code

        config_symbol = constructor_match.group(1).strip()
        config_name, config_default = self._find_config_property_for_symbol(code, config_symbol)
        if not config_name:
            config_name = 'http.headers.suppression.list'
            config_default = ''

        order_match = re.search(r'\w+\.setOrder\(([^)]+)\);', body)
        order_value = order_match.group(1).strip() if order_match else None
        metadata_comments = self._extract_filter_registration_comments(body)
        producer_name = f'{method_name}Headers'

        self._generate_header_suppression_filter_registration(
            current_package=current_package,
            method_name=method_name,
            producer_name=producer_name,
            order_value=order_value,
            metadata_comments=metadata_comments,
        )

        method_annotations = annotations
        if '@Named("' not in method_annotations:
            method_annotations = method_annotations + f'    @Named("{producer_name}")\n'

        method_block = (
            f'{method_annotations}{visibility}List<String> {producer_name}('
            f'@ConfigProperty(name = "{config_name}", defaultValue = "{config_default}") String configuredHeaders) {{\n'
        )
        method_block += (
            '        if (configuredHeaders == null || configuredHeaders.isBlank()) {\n'
            '            return java.util.Collections.emptyList();\n'
            '        }\n'
            '        return java.util.Arrays.stream(configuredHeaders.split(","))\n'
                '                .map(String::trim)\n'
            '                .filter(value -> !value.isEmpty())\n'
            '                .toList();\n'
            '    }'
        )
        return method_block, code

    def _find_config_property_for_symbol(self, code: str, symbol: str) -> tuple[str | None, str]:
        """Find the config property name/default associated with a field symbol."""
        field_tail = rf'(?:private|protected|public)\s+[^\n;=]+?\b{re.escape(symbol)}\b\s*;'
        patterns = [
            re.compile(
                rf'@ConfigProperty\(\s*name\s*=\s*"([^"]+)"(?:\s*,\s*defaultValue\s*=\s*"([^"]*)")?\s*\)\s*{field_tail}',
                re.MULTILINE
            ),
            re.compile(
                r'@Value\(\s*"\#\{\'\$\{([^}:]+)(?::([^}]*))?\}\'\.split\(\'\,\'\)\}"\s*\)\s*' + field_tail,
                re.MULTILINE
            ),
            re.compile(
                r'@Value\(\s*"\$\{([^}:]+)(?::([^}]*))?\}"\s*\)\s*' + field_tail,
                re.MULTILINE
            ),
        ]
        for pattern in patterns:
            match = pattern.search(code)
            if match:
                return match.group(1), (match.group(2) or '').strip()
        return None, ''

    def _generate_header_suppression_filter_registration(
        self,
        current_package: str,
        method_name: str,
        producer_name: str,
        order_value: str | None,
        metadata_comments: List[str],
    ) -> None:
        """Generate a Helidon MP response filter that removes configured response headers."""
        if not hasattr(self, 'target_path') or not self.target_path:
            return

        module_root = self.target_path
        try:
            for pom in self.target_path.rglob('pom.xml'):
                module_root = pom.parent
                break
        except Exception:
            module_root = self.target_path

        support_package = self._shared_proxy_support_package(current_package)
        class_name = ''.join(part[:1].upper() + part[1:] for part in method_name.split('_')) + 'Registration'
        output_file = module_root / 'src/main/java' / support_package.replace('.', '/') / f'{class_name}.java'
        output_file.parent.mkdir(parents=True, exist_ok=True)

        priority_annotation = f'@Priority({order_value})\n' if order_value else ''
        metadata_block = '\n'.join(
            f' * TODO Manual review: {comment}'
            for comment in metadata_comments
        ) or ' * TODO Manual review: verify original servlet response filter semantics are preserved.'

        registration_code = f'''package {support_package};

import jakarta.annotation.Priority;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import jakarta.inject.Named;
import jakarta.ws.rs.container.ContainerRequestContext;
import jakarta.ws.rs.container.ContainerResponseContext;
import jakarta.ws.rs.container.ContainerResponseFilter;
import jakarta.ws.rs.ext.Provider;
import java.util.List;

/**
 * Helidon MP 4.x response filter generated from legacy servlet-style header suppression wiring.
 * Applies configured response-header removal to JAX-RS endpoints.
{metadata_block}
 */
@Provider
@ApplicationScoped
{priority_annotation}public class {class_name} implements ContainerResponseFilter {{

    @Inject
    @Named("{producer_name}")
    private List<String> suppressedHeaders;

    @Override
    public void filter(ContainerRequestContext requestContext, ContainerResponseContext responseContext) {{
        if (suppressedHeaders == null || suppressedHeaders.isEmpty()) {{
            return;
        }}
        for (String header : suppressedHeaders) {{
            if (header != null && !header.isBlank()) {{
                responseContext.getHeaders().remove(header);
            }}
        }}
    }}
}}
'''
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(registration_code)
            logger.info(f"Generated Helidon MP header suppression filter at {output_file}")
        except Exception as e:
            logger.error(f"Failed to generate Helidon MP header suppression filter: {e}")

    def _extract_filter_setup_statements(self, body: str) -> List[str]:
        """Preserve meaningful side effects from Spring filter registration methods."""
        preserved: List[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
        return preserved

    def _extract_filter_registration_comments(self, body: str) -> List[str]:
        """Describe Spring filter registration metadata that Helidon MP cannot port directly."""
        comments: List[str] = []

        order_match = re.search(r'\w+\.setOrder\(([^)]+)\);', body)
        if order_match:
            comments.append(f'Original filter order: {order_match.group(1).strip()}')

        url_patterns = re.findall(r'\w+\.addUrlPatterns\(([^)]+)\);', body)
        if url_patterns:
            comments.append(f'Original URL patterns: {", ".join(pattern.strip() for pattern in url_patterns)}')

        if 'setEnabled(false)' in body:
            comments.append('Original registration disabled this filter or a related registration')

        if 'ObjectUtils.isEmpty(' in body or 'StringUtils.isEmpty(' in body:
            comments.append('Original registration conditionally disabled this filter based on config state')

        return comments

    def _extract_filter_expression(self, body: str) -> str | None:
        """Extract the actual filter instance from a FilterRegistrationBean method body."""
        set_filter_match = re.search(r'\w+\.setFilter\((.+?)\);', body, re.DOTALL)
        if set_filter_match:
            return set_filter_match.group(1).strip()

        direct_return_match = re.search(r'return\s+new\s+([A-Za-z_][\w<>]*)\((.*?)\);', body, re.DOTALL)
        if direct_return_match:
            return f"new {direct_return_match.group(1)}({direct_return_match.group(2).strip()})"

        return None

    def _generate_mp_filter_registration(
        self,
        current_package: str,
        source_code: str,
        method_name: str,
        filter_type: str,
        order_value: str | None,
        metadata_comments: List[str],
    ) -> None:
        """Generate a Helidon MP/JAX-RS provider wrapper for a migrated Spring filter registration."""
        if not hasattr(self, 'target_path') or not self.target_path:
            return

        module_root = self.target_path
        try:
            for pom in self.target_path.rglob('pom.xml'):
                module_root = pom.parent
                break
        except Exception:
            module_root = self.target_path

        support_package = self._shared_proxy_support_package(current_package)
        class_name = ''.join(part[:1].upper() + part[1:] for part in method_name.split('_')) + 'Registration'
        output_file = module_root / 'src/main/java' / support_package.replace('.', '/') / f'{class_name}.java'
        output_file.parent.mkdir(parents=True, exist_ok=True)

        filter_kind = self._infer_mp_filter_kind(method_name, filter_type)
        interfaces = []
        methods = []
        if filter_kind in {'request', 'both'}:
            interfaces.append('ContainerRequestFilter')
            methods.append(
                '''    @Override
    public void filter(ContainerRequestContext requestContext) {
        // TODO Manual review: port servlet request-filter behavior into this JAX-RS request filter.
    }'''
            )
        if filter_kind in {'response', 'both'}:
            interfaces.append('ContainerResponseFilter')
            methods.append(
                '''    @Override
    public void filter(ContainerRequestContext requestContext, ContainerResponseContext responseContext) {
        // TODO Manual review: port servlet response-filter behavior into this JAX-RS response filter.
    }'''
            )

        priority_annotation = f'@Priority({order_value})\n' if order_value else ''
        metadata_block = '\n'.join(
            f' * TODO Manual review: {comment}'
            for comment in metadata_comments
        ) or ' * TODO Manual review: verify original servlet filter semantics are preserved.'
        filter_import = self._resolve_type_import(source_code, filter_type, current_package)

        registration_code = f'''package {support_package};

import {filter_import};
import jakarta.annotation.Priority;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import jakarta.inject.Named;
import jakarta.ws.rs.container.ContainerRequestContext;
import jakarta.ws.rs.container.ContainerRequestFilter;
import jakarta.ws.rs.container.ContainerResponseContext;
import jakarta.ws.rs.container.ContainerResponseFilter;
import jakarta.ws.rs.ext.Provider;

/**
 * Helidon MP 4.x registration generated from legacy servlet-style filter wiring.
 * Uses JAX-RS provider registration for MP-compatible request/response interception.
{metadata_block}
 */
@Provider
@ApplicationScoped
{priority_annotation}public class {class_name} implements {', '.join(interfaces)} {{

    @Inject
    @Named("{method_name}")
    private {filter_type} delegate;

{chr(10).join(methods)}
}}
'''
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(registration_code)
            logger.info(f"Generated Helidon MP filter registration at {output_file}")
        except Exception as e:
            logger.error(f"Failed to generate Helidon MP filter registration: {e}")

    def _infer_mp_filter_kind(self, method_name: str, filter_type: str) -> str:
        """Infer whether a migrated filter should become a request, response, or dual JAX-RS provider."""
        marker = f'{method_name} {filter_type}'.lower()
        if 'response' in marker:
            return 'response'
        if 'log' in marker:
            return 'both'
        return 'request'

    def _resolve_type_import(self, code: str, simple_name: str, current_package: str) -> str:
        """Resolve the imported type for generated helper code."""
        import_match = re.search(rf'import\s+([A-Za-z0-9_\.]+\.{re.escape(simple_name)})\s*;', code)
        if import_match:
            return import_match.group(1)
        return f'{current_package}.{simple_name}'

    def _materialize_lombok_features(self, code: str) -> str:
        """Replace Lombok conveniences with explicit Java where generated code depends on them."""
        code = self._materialize_slf4j_logger(code)
        code = self._materialize_lombok_accessors(code)
        code = re.sub(r'^\s*@ToString\s*\n', '', code, flags=re.MULTILINE)
        code = re.sub(r'import\s+lombok\.ToString;\s*\n?', '', code)
        return code

    def _materialize_slf4j_logger(self, code: str) -> str:
        if '@Slf4j' not in code or 'log.' not in code:
            return code
        if re.search(r'(private|protected|public)\s+static\s+final\s+(?:org\.slf4j\.)?Logger\s+log\s*=', code):
            code = re.sub(r'^\s*@Slf4j\s*\n', '', code, flags=re.MULTILINE)
            code = re.sub(r'import\s+lombok\.extern\.slf4j\.Slf4j;\s*\n?', '', code)
            return code

        class_match = re.search(r'public\s+class\s+(\w+)[^{]*\{', code)
        if not class_match:
            return code
        class_name = class_match.group(1)
        logger_field = (
            '\n    private static final org.slf4j.Logger log = '
            f'org.slf4j.LoggerFactory.getLogger({class_name}.class);\n'
        )
        code = code[:class_match.end()] + logger_field + code[class_match.end():]
        code = re.sub(r'^\s*@Slf4j\s*\n', '', code, flags=re.MULTILINE)
        code = re.sub(r'import\s+lombok\.extern\.slf4j\.Slf4j;\s*\n?', '', code)
        return code

    def _materialize_lombok_accessors(self, code: str) -> str:
        if '@Getter' not in code and '@Setter' not in code:
            return code

        class_prefix_match = re.search(
            r'((?:\s*@[\w.]+(?:\((?:[^()\n]|\([^()\n]*\))*\))?\s*\n)*)\s*public\s+class\s+\w+[^{]*\{',
            code
        )
        if not class_prefix_match:
            return code
        class_annotations = class_prefix_match.group(1) or ''
        class_has_getter = '@Getter' in class_annotations
        class_has_setter = '@Setter' in class_annotations
        if not class_has_getter and not class_has_setter:
            return code

        class_match = re.search(r'public\s+class\s+\w+[^{]*\{', code)
        if not class_match:
            return code

        field_pattern = re.compile(
            r'^\s*(?:private|protected|public)?\s*(?!static\b)(?!final\b)([A-Za-z_][\w<>,\[\]\.? ]*)\s+([A-Za-z_]\w*)\s*;\s*$',
            re.MULTILINE
        )
        accessors: List[str] = []
        for field_type, field_name in field_pattern.findall(code):
            field_type = field_type.strip()
            capitalized = field_name[:1].upper() + field_name[1:]
            getter_name = f'get{capitalized}'
            setter_name = f'set{capitalized}'
            if class_has_getter and not re.search(rf'\b{getter_name}\s*\(', code):
                accessors.append(
                    f'\n    public {field_type} {getter_name}() {{\n        return {field_name};\n    }}\n'
                )
            if class_has_setter and not re.search(rf'\b{setter_name}\s*\(', code):
                accessors.append(
                    f'\n    public void {setter_name}({field_type} {field_name}) {{\n        this.{field_name} = {field_name};\n    }}\n'
                )

        if accessors:
            last_brace = code.rfind('}')
            if last_brace != -1:
                code = code[:last_brace] + ''.join(accessors) + '\n' + code[last_brace:]

        code = re.sub(r'^\s*@Getter\s*\n', '', code, flags=re.MULTILINE)
        code = re.sub(r'^\s*@Setter\s*\n', '', code, flags=re.MULTILINE)
        code = re.sub(r'import\s+lombok\.Getter;\s*\n?', '', code)
        code = re.sub(r'import\s+lombok\.Setter;\s*\n?', '', code)
        return code

    def _transform_response_error_handler(self, code: str) -> str:
        """Convert Spring ResponseErrorHandler-style classes to JAX-RS Response helpers."""
        error_handler_markers = [
            'implements ResponseErrorHandler',
            'import org.springframework.web.client.ResponseErrorHandler',
            'ClientHttpResponse',
            'import org.springframework.http.client.ClientHttpResponse',
        ]
        if not any(marker in code for marker in error_handler_markers):
            return code

        code = re.sub(r'import\s+org\.springframework\.web\.client\.ResponseErrorHandler;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.http\.client\.ClientHttpResponse;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.http\.HttpStatus;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.http\.HttpMethod;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.http\.HttpHeaders;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.stereotype\.Component;\s*\n?', '', code)
        code = re.sub(r'implements\s+ResponseErrorHandler', '', code)
        code = re.sub(r'@Component', '@ApplicationScoped', code)
        code = re.sub(r'@Override\s*\n', '', code)
        code = code.replace('ClientHttpResponse', 'Response')
        code = code.replace('HttpMethod', 'String')
        code = code.replace('HttpHeaders', 'Object')
        code = code.replace('HttpStatus', 'Response.Status')
        code = code.replace('Response.Status.resolve(', 'Response.Status.fromStatusCode(')
        code = code.replace('.value()', '.getStatusCode()')
        code = code.replace('.series()', '.getFamily()')
        code = code.replace('getRawStatusCode()', 'getStatus()')
        code = code.replace('getStatusText()', 'getStatusInfo().getReasonPhrase()')
        code = code.replace('getStatusCode().toString()', 'String.valueOf(getStatus())')
        code = code.replace('clienthttpresponse.getStatusCode()', 'Response.Status.fromStatusCode(clienthttpresponse.getStatus())')
        code = code.replace('httpResponse.getStatusCode()', 'Response.Status.fromStatusCode(httpResponse.getStatus())')
        code = code.replace('response.getStatusCode()', 'Response.Status.fromStatusCode(response.getStatus())')
        code = code.replace('Response.Status.OK', 'Response.Status.OK.getStatusCode()')

        code = self._replace_method(
            code,
            r'public\s+String\s+getErrorMessage\s*\(\s*Response\s+\w+\s*\)\s*\{',
            '''public String getErrorMessage(Response httpResponse) {
        String responseBodyString = null;
        UDPErrorResponse udpErrorResponse = new UDPErrorResponse();
        try {
            responseBodyString = httpResponse.readEntity(String.class);
            if (responseBodyString != null && !responseBodyString.isBlank()) {
                Gson g = new Gson();
                udpErrorResponse = g.fromJson(responseBodyString, UDPErrorResponse.class);
            }
        } catch (com.google.gson.JsonSyntaxException ex){
            log.error("Error while fetching error message from response : {} ", responseBodyString);
            log.error(ex.getMessage());
            udpErrorResponse.setErrorMessage(responseBodyString);
        } catch (Exception ex) {
            log.error("Generic Error while fetching error message from response : {} ", responseBodyString);
            log.error(ex.getMessage());
            udpErrorResponse.setErrorMessage(responseBodyString);
        }
        return udpErrorResponse.getErrorMessage();
    }'''
        )

        code = self._replace_method(
            code,
            r'public\s+boolean\s+hasError\s*\(\s*Response\s+\w+\s*\)\s*(?:throws\s+IOException\s*)?\{',
            '''public boolean hasError(Response clienthttpresponse) throws IOException {
        log.error("Inside hasError of CustomResponseErrorHandler");

        if (clienthttpresponse == null || clienthttpresponse.getStatusInfo() == null) {
            log.error("clienthttpresponse and clienthttpresponse.getStatusInfo() is null");
            return false;
        }
        if (clienthttpresponse.getStatus() != Response.Status.OK.getStatusCode()) {
            log.error("Client response status: {} reason: {}", clienthttpresponse.getStatus(), clienthttpresponse.getStatusInfo().getReasonPhrase());
        }
        log.info("Client response status: {} reason: {}", clienthttpresponse.getStatus(), clienthttpresponse.getStatusInfo().getReasonPhrase());
        return clienthttpresponse.getStatusInfo().getFamily() == Response.Status.Family.CLIENT_ERROR
                || clienthttpresponse.getStatusInfo().getFamily() == Response.Status.Family.SERVER_ERROR;
    }'''
        )

        code = self._replace_method(
            code,
            r'public\s+void\s+handleError\s*\(\s*URI\s+\w+\s*,\s*String\s+\w+\s*,\s*Response\s+\w+\s*\)\s*throws\s+IOException\s*\{',
            '''public void handleError(URI url, String method, Response httpResponse) throws IOException {
        log.error("Inside handleError of CustomResponseErrorHandler");

        String errorMessage = getErrorMessage(httpResponse);
        log.error("ErrorMessage from response: {}", errorMessage);

        Response.Status statusCode = Response.Status.fromStatusCode(httpResponse.getStatus());
        String statusText = httpResponse.getStatusInfo().getReasonPhrase();
        String message = errorMessage != null ? errorMessage : String.valueOf(httpResponse.getStatus());
        log.error("Final error message: {}", message);

        if (statusCode != null) {
            switch (statusCode.getFamily()) {
                case CLIENT_ERROR:
                    throw handleClientErrorException(message, statusCode, statusText, null, url);
                case SERVER_ERROR:
                    throw handleServerErrorException(message, statusCode, statusText, null, url);
                default:
                    throw new DomainException(statusCode.getStatusCode(), DomainException.ERROR_TYPE, SERVER_ERROR, message,
                            defaultServerErrCode);
            }
        }
    }'''
        )

        code = self._replace_method(
            code,
            r'public\s+void\s+handleError\s*\(\s*Response\s+\w+\s*\)\s*(?:throws\s+IOException\s*)?\{',
            '''public void handleError(Response response) throws IOException {
        if (response != null && hasError(response)) {
            handleError(URI.create("about:blank"), "UNKNOWN", response);
        }
    }'''
        )

        code = self._replace_method(
            code,
            r'DomainException\s+handleClientErrorException\s*\([^)]*\)\s*\{',
            '''DomainException handleClientErrorException(String message, Response.Status statusCode, String statusText, Object headers, URI uri) {
        log.error("Inside handleClientErrorException of CustomResponseErrorHandler message:{ },statusCode:{ },statusText:{ }",message,statusCode,statusText);
        String errMsg = (message != null) ? message : statusText;
        String path = uri.getPath();
        String domainDetailProdCode = MCPS_ERR_CODE_PREFIX + "-" + statusCode.getStatusCode();

        DomainException domainException = null;
        if (statusCode != null && statusCode.getStatusCode() == 422) {
            domainException = new UnprocessableEntityException(errMsg, MCPS_ERR_CODE_PREFIX, null);// UDP
        } else {
            switch (statusCode) {
                case BAD_REQUEST:
                domainException = new RequestContextInvalidException(errMsg, MCPS_ERR_CODE_PREFIX, null); // UDP
                break;
                case UNAUTHORIZED:
                domainException = new UnauthorizedException(errMsg, CXU_ERR_CODE_PREFIX, null); // CXU
                domainDetailProdCode = CXU_ERR_CODE_PREFIX + "-" + statusCode.getStatusCode();
                break;
                case FORBIDDEN:
                domainException = new AccessDeniedException(errMsg, CXU_ERR_CODE_PREFIX, null); // CXU
                domainDetailProdCode = CXU_ERR_CODE_PREFIX + "-" + statusCode.getStatusCode();
                break;
                case NOT_FOUND:
                domainException = new ResourceNotFoundException(errMsg, MCPS_ERR_CODE_PREFIX, null);// UDP
                break;
                case CONFLICT:
                domainException = new ResourceConflictException(errMsg, MCPS_ERR_CODE_PREFIX, null);// UDP
                break;
                case TOO_MANY_REQUESTS:
                domainException = new OciRateLimitException(errMsg, MCPS_ERR_CODE_PREFIX, null); // UDP
                break;
                default:
                domainException = new DomainException(statusCode.getStatusCode(), DomainException.ERROR_TYPE, CLIENT_ERROR, errMsg,
                        defaultClientErrCode);
            }
        }

        DomainExceptionDetail details = new DomainExceptionDetail(domainException.getType(), path,
                domainException.getTitle(), path, domainDetailProdCode);
        domainException.addDetail(details);

        log.error("Inside handleClientErrorException, statusCode: {}, errorMessage: {}", statusCode, errMsg);

        return domainException;
    }'''
        )
        code = re.sub(
            r'DomainException\s+handleServerErrorException\s*\([^)]*\)',
            'DomainException handleServerErrorException(String message, Response.Status statusCode, String statusText, Object headers, URI uri)',
            code
        )
        code = re.sub(r'\n{3,}', '\n\n', code)
        return code

    def _transform_keystone_router_proxy_forwarding(self, code: str) -> str:
        """Replace Spring-only KeyStoneRouter.forward(proxy, ...) usage with Helidon-native proxy dispatch."""
        if 'keyStoneRouter.forward(proxy, request, keystoneParams)' not in code:
            return code

        replacement_method = '''public Response forward(ProxyExchange<?> proxy, HttpServletRequest request,
    Map<String, String> keystoneParams, String requestId) throws URISyntaxException {
        Response response = null;
        Instant start = null;
        Instant finish = null;
        try {
            log.debug("calling oudp service");
            start = Instant.now();
            String oudpServerUrl = keystoneParams != null ? keystoneParams.get(KEYSTONE_REGION_URL) : null;
            String token = keyStoneRouter.getToken(keystoneParams);
            URI targetUri = composeTargetUri(request, oudpServerUrl);
            if (targetUri == null) {
                throw customResponseErrorHandler.handleServerErrorException(
                        "Unable to compose Keystone target URI",
                        Response.Status.BAD_GATEWAY,
                        null,
                        null,
                        URI.create(request.getRequestURI()));
            }

            ProxyExchange<?> outboundProxy = getHeaders(proxy, request, targetUri.toString());
            outboundProxy.header("Authorization", "Bearer " + token);

            switch (request.getMethod()) {
                case "GET":
                response = outboundProxy.get();
                break;
                case "PUT":
                response = outboundProxy.put();
                break;
                case "POST":
                response = outboundProxy.post();
                break;
                case "DELETE":
                response = outboundProxy.delete();
                break;
                case "OPTIONS":
                response = outboundProxy.options();
                break;
                case "HEAD":
                response = outboundProxy.head();
                break;
                case "PATCH":
                response = outboundProxy.patch();
                break;
                default:
                response = Response.status(Response.Status.METHOD_NOT_ALLOWED).build();
            }
            finish = Instant.now();
        } catch (KeystoneRouterException e) {
            log.error("KeystoneRouterException {}", e.getMessage());
            String errMsg = e.getMessage()!=null?e.getMessage():e.getErrorMsg();
            Response.Status errorCode = Response.Status.fromStatusCode(e.getCode())!=null ? Response.Status.fromStatusCode(e.getCode()): Response.Status.INTERNAL_SERVER_ERROR;
            throw customResponseErrorHandler.handleServerErrorException(errMsg,errorCode,null,null,new URI(request.getRequestURI()));
        }finally {
            if(finish == null){
                log.info("OUDP Call errored out!");
                finish = Instant.now();
            }
            log.info("Time taken to complete the OUDP call in millsec {}",Duration.between(start, finish).toMillis());
        }
        return response;
    }'''

        return self._replace_method(
            code,
            r'public\s+Response\s+forward\s*\(\s*ProxyExchange<\?>\s+\w+\s*,\s*HttpServletRequest\s+\w+\s*,\s*Map<String,\s*String>\s+\w+\s*,\s*String\s+\w+\s*\)\s*throws\s+URISyntaxException\s*\{',
            replacement_method
        )

    def _normalize_generic_exception_usage(self, code: str) -> str:
        """Remove broad checked Exception contracts where deterministic Helidon-safe alternatives exist."""
        code = code.replace(
            'throw new Exception("Header X-IDCS_USER_NAME is required"); //TODO Throw Generic Unity Exception',
            'throw new BadRequestException("Header X-IDCS_USER_NAME is required"); // TODO Manual review: replace with a domain-specific CXU exception if needed'
        )
        code = re.sub(r'throw\s+new\s+Exception\s*\(', 'throw new IllegalStateException(', code)

        signature_pattern = re.compile(
            r'((?:public|protected|private)\s+[A-Za-z_][\w<>,\[\]\.? ]*\s+\w+\s*\((?:[^()]|\([^)]*\))*\))\s*throws\s+Exception(\s*[;{])',
            re.MULTILINE
        )

        def replace_signature(match):
            signature = match.group(1)
            if 'InvocationContext' in signature:
                return match.group(0)
            return f'{signature}{match.group(2)}'

        code = signature_pattern.sub(replace_signature, code)

        if 'BadRequestException' in code and 'import jakarta.ws.rs.BadRequestException;' not in code:
            package_match = re.search(r'package\s+[^;]+;\s*\n', code)
            insert_pos = package_match.end() if package_match else 0
            code = code[:insert_pos] + '\nimport jakarta.ws.rs.BadRequestException;\n' + code[insert_pos:]

        return code

    def _normalize_uri_exception_signatures(self, code: str) -> str:
        """Remove checked URI exceptions from migrated proxy flows when URI.create is sufficient."""
        code = code.replace('new URI(request.getRequestURI())', 'URI.create(request.getRequestURI())')
        code = re.sub(
            r'(\b(?:getProxyVersion|getProxyPath|forward)\s*\((?:[^()]|\([^)]*\))*\))\s*throws\s+URISyntaxException(\s*\{)',
            r'\1\2',
            code,
            flags=re.MULTILINE
        )
        return code

    def _cleanup_obsolete_uri_exception_blocks(self, code: str) -> str:
        """Remove dead try/catch scaffolding left behind after URI.create conversion."""
        code = re.sub(
            r'URI\s+requestUri\s*=\s*null;\s*try\s*\{\s*requestUri\s*=\s*URI\.create\(request\.getRequestURI\(\)\);\s*(log\.debug\([^;]+;\s*)\}\s*catch\s*\(URISyntaxException\s+\w+\)\s*\{\s*[^}]+\}\s*',
            r'URI requestUri = URI.create(request.getRequestURI());\n        \1',
            code,
            flags=re.DOTALL
        )
        code = re.sub(
            r'try\s*\{\s*return\s+(getProxyPath\([^;]+;\s*)\}\s*catch\s*\(URISyntaxException\s+\w+\)\s*\{\s*[^}]+\}\s*',
            r'return \1',
            code,
            flags=re.DOTALL
        )
        return code

    def _stabilize_admin_service_proxy_methods(self, code: str) -> str:
        """Replace brittle regex-cleaned AdminService proxy methods with stable deterministic bodies."""
        if 'class AdminService' not in code or 'public Response getProxy(' not in code:
            return code

        replacement_method = '''public Response getProxy(HttpServletRequest request, String mcpsBaseUrl, String xRequestId,ProxyExchange<?> proxy) {
        log.debug("Inside getProxy method of AdminService request : {}, mcpsBaseUrl: {}, xRequestId {}, proxy {}",request,mcpsBaseUrl,xRequestId,proxy );
        URI uri = composeTargetUri(request,mcpsBaseUrl);
        String queryString ="";
        if(uri!=null) {
            queryString=uri.toString();
        }
        String infoMessage = String.format(FORWARD_LOG, request.getMethod(), request.getRequestURI());
        infoMessage =  String.format("%s %s %s", xRequestId, request.getMethod(), queryString);
        log.debug("infoMessage,xRequestId = {} :: {}", infoMessage,queryString);
        String appName = request.getHeader(APPNAME_HEADER);
        String idcsUserId = request.getHeader(IDCS_USER_ID_HEADER);
        MCPSKeyStoneConfig mcpsKeyStoneConfig = mcpsSwitchService.findByTenantId(appName);
        log.debug("Ready to go tentantType Equals condition :: {}",request.getHeader(IDCS_USER_NAME_HEADER));

        TenantType tenantType = mcpsKeyStoneConfig == null ? TenantType.CLASSIC : TenantType.KEYSTONE;
        URI requestUri = URI.create(request.getRequestURI());
        log.debug("requestUri {} ::", requestUri);
        Map<String,String> keystoneParams = null;
        if( tenantType.equals(TenantType.KEYSTONE)){
            log.debug("Outside tentantType Equals condition {} :: {}",tenantType,request.getHeader(IDCS_USER_NAME_HEADER));
            if (StringUtils.isBlank(request.getHeader(IDCS_USER_NAME_HEADER))) {
                log.error("Inside tentantType Equals condition {} :: {}",tenantType,request.getHeader(IDCS_USER_NAME_HEADER));
                throw customResponseErrorHandler.handleClientErrorException("Header X-IDCS_USER_NAME is required",Response.Status.BAD_REQUEST,null,null,requestUri);
            }
            try{
                log.info("$$$$$$$$$$$$$$$$$$$$$$$$$$");
                log.info("idcsUserId :- {}", idcsUserId);
                log.info("idcsUserName :- "+request.getHeader(IDCS_USER_NAME_HEADER));
                log.info("$$$$$$$$$$$$$$$$$$$$$$$$$$");
                keystoneParams = populateKeystoneParams(mcpsKeyStoneConfig);
                keystoneParams.put(USER_ID,idcsUserId);
                keystoneParams.put(USER_NAME, request.getHeader(IDCS_USER_NAME_HEADER));
                keystoneParams.put(GRANT_TYPE, IDCS_TOKEN_GRANT_TYPE_JWT_BEARER);
            }
            catch(Exception e){
                log.error("populateKeystoneParams {},Exception {} ::", e.getMessage(), e);
                throw customResponseErrorHandler.handleServerErrorException("PopulateKeystoneParams exception",Response.Status.INTERNAL_SERVER_ERROR,null,null,requestUri);
            }
        }
        log.info("Tenant Type : {}  URI : {} HTTPMethod: {}", tenantType, uri == null ? "empty" : uri, request.getMethod());
        log.debug("end of getProxy method of AdminService idcsUserId: {}",idcsUserId);
        return getProxyPath(request, tenantType, proxy, queryString, keystoneParams, xRequestId);
    }'''

        signature_pattern = re.compile(
            r'public\s+Response\s+getProxy\s*\(\s*HttpServletRequest\s+\w+\s*,\s*String\s+\w+\s*,\s*String\s+\w+\s*,\s*ProxyExchange<\?>\s+\w+\s*\)\s*\{',
            re.MULTILINE
        )
        match = signature_pattern.search(code)
        if not match:
            return code

        brace_start = match.end() - 1
        brace_end = self._find_matching_brace(code, brace_start)
        if brace_end == -1:
            return code

        next_javadoc = code.find('\n    /**', brace_end + 1)
        if next_javadoc == -1:
            next_javadoc = code.find('\n/**', brace_end + 1)
        replace_end = next_javadoc if next_javadoc != -1 else brace_end + 1

        return code[:match.start()] + replacement_method + '\n\n' + code[replace_end:]

    def _disambiguate_produces_annotations(self, code: str) -> str:
        """Separate CDI @Produces from JAX-RS @Produces(MediaType...) to avoid import conflicts."""
        has_cdi_produces = bool(re.search(r'(?m)^\s*@Produces\s*$', code))
        has_jaxrs_produces = '@Produces(' in code or '@jakarta.ws.rs.Produces(' in code

        if has_cdi_produces and has_jaxrs_produces:
            code = code.replace('@Produces(', '@jakarta.ws.rs.Produces(')
            code = re.sub(r'import\s+jakarta\.ws\.rs\.Produces;\s*\n?', '', code)
            if 'import jakarta.enterprise.inject.Produces;' not in code:
                code = re.sub(
                    r'package\s+[^;]+;\s*\n',
                    lambda m: m.group(0) + '\nimport jakarta.enterprise.inject.Produces;\n',
                    code,
                    count=1
                )
            return code

        if has_cdi_produces and not has_jaxrs_produces:
            code = re.sub(r'import\s+jakarta\.ws\.rs\.Produces;\s*\n?', '', code)
            if 'import jakarta.enterprise.inject.Produces;' not in code:
                code = re.sub(
                    r'package\s+[^;]+;\s*\n',
                    lambda m: m.group(0) + '\nimport jakarta.enterprise.inject.Produces;\n',
                    code,
                    count=1
                )
            return code

        if has_jaxrs_produces and not has_cdi_produces:
            code = re.sub(r'import\s+jakarta\.enterprise\.inject\.Produces;\s*\n?', '', code)

        return code

    def _replace_method(self, code: str, signature_pattern: str, replacement: str) -> str:
        """Replace a method block identified by its signature regex."""
        match = re.search(signature_pattern, code, re.MULTILINE)
        if not match:
            return code

        brace_start = match.end() - 1
        brace_end = self._find_matching_brace(code, brace_start)
        if brace_end == -1:
            return code

        return code[:match.start()] + replacement + code[brace_end + 1:]

    def _find_matching_brace(self, code: str, open_brace_index: int) -> int:
        """Find the matching closing brace for a method or block."""
        depth = 0
        for index in range(open_brace_index, len(code)):
            char = code[index]
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    return index
        return -1

        
    def _transform_types(self, code: str) -> tuple[str, int]:
        """Transform Spring types to Jakarta/Helidon types"""
        count = 0
        
        # 1. ResponseEntity -> Response
        if 'ResponseEntity' in code:
            # Replace class name
            code = code.replace('ResponseEntity', 'Response')
            
            # Remove generics <...> from Response<...>
            # Handle nested generics iteratively with limit to prevent infinite loops
            # Pattern: Response<...> -> Response
            for _ in range(5): # Max 5 levels of nesting
                # Match Response< [content with no < or >] >
                # This peels off one layer of generics from the inside
                # Actually, simple greedy match for top level is hard with regex unless balanced.
                # Better approach: Just look for Response<...> and remove <...> if possible.
                # But Response<List<String>> -> Response<List<String>> match?
                
                # Let's use a simpler heuristic: Remove <...> after Response if it doesn't contain < or > inside one level?
                # Or just handle common cases.
                
                # Attempt to remove all generics attached to Response
                # Replaces Response<AnyNonBracket> with Response
                new_code = re.sub(r'Response<[^<>]+>', 'Response', code)
                if new_code == code:
                    break
                code = new_code
            
            # Handle .ok() builder
            code = code.replace('Response.ok(', 'Response.ok().entity(')
            code = code.replace('Response.status(', 'Response.status(')
            
            # Handle .body() -> .entity() (Spring uses .body(), JAX-RS uses .entity())
            code = code.replace('.body(', '.entity(')
            
            count += 1
            
        # 2. HttpStatus -> Response.Status
        if 'HttpStatus' in code:
            code = code.replace('HttpStatus.CREATED', 'Response.Status.CREATED')
            code = code.replace('HttpStatus.OK', 'Response.Status.OK')
            code = code.replace('HttpStatus.NOT_FOUND', 'Response.Status.NOT_FOUND')
            code = code.replace('HttpStatus.BAD_REQUEST', 'Response.Status.BAD_REQUEST')
            code = code.replace('HttpStatus.INTERNAL_SERVER_ERROR', 'Response.Status.INTERNAL_SERVER_ERROR')
            count += 1

        # 3. new Response<>(Response.Status.X) -> Response.status(Response.Status.X).build()
        code = re.sub(
            r'new\s+Response\s*<[^>]*>\s*\(\s*Response\.Status\.([A-Z_]+)\s*\)',
            r'Response.status(Response.Status.\1).build()',
            code
        )
        code = re.sub(
            r'new\s+Response\s*\(\s*Response\.Status\.([A-Z_]+)\s*\)',
            r'Response.status(Response.Status.\1).build()',
            code
        )
            
        return code, count
    
    def _transform_annotations(self, code: str) -> tuple[str, int]:
        """Transform Spring annotations to Helidon MP annotations using Vector DB ONLY"""
        transformation_count = 0
        
        # Use vector DB ONLY - no hardcoded fallbacks
        spring_annotations = re.findall(r'@\w+(?:\([^)]*\))?', code)
        processed_annotations = set()
        
        for annotation in spring_annotations:
            if annotation in processed_annotations:
                continue
                
            # Extract annotation name (without parameters)
            ann_match = re.match(r'@(\w+)', annotation)
            if not ann_match:
                continue
            ann_name = ann_match.group(1)
            
            # Skip if already Jakarta/Helidon annotation
            if ann_name in ['Path', 'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'Inject', 'ApplicationScoped', 'ConfigProperty', 'PathParam', 'QueryParam', 'Consumes', 'Produces']:
                continue
            
            # Try vector DB search - use metadata filter for exact match
            found_in_db = False
            try:
                # First: Try exact match using metadata filter
                exact_pattern = f'@{ann_name}'
                embedding = self.embedding_model.encode_single(exact_pattern)
                
                # Search with filter for exact spring_pattern match
                results = self.knowledge_base.search(
                    collection_name='annotations',
                    query_embedding=embedding,
                    top_k=10,
                    filters={'spring_pattern': exact_pattern}  # Exact match filter
                )
                
                if results and len(results) > 0:
                    for result in results:
                        metadata = result.get('metadata', {})
                        if metadata.get('migration_type') == 'annotation':
                            spring_pattern = metadata.get('spring_pattern', '')
                            # Should be exact match due to filter, but double-check
                            if f'@{ann_name}' == spring_pattern:
                                helidon_pattern = metadata.get('helidon_pattern', '')
                                # Replace annotation
                                if helidon_pattern == '':
                                    code = re.sub(rf'@{re.escape(ann_name)}(?:\([^)]*\))?\s*\n?', '', code)
                                else:
                                    # Replace with Helidon annotation (keep parameters if any)
                                    param_match = re.search(rf'@{re.escape(ann_name)}(\([^)]*\))?', code)
                                    if param_match and param_match.group(1):
                                        code = code.replace(param_match.group(0), f'{helidon_pattern}{param_match.group(1)}')
                                    else:
                                        code = code.replace(f'@{ann_name}', helidon_pattern)
                                transformation_count += 1
                                found_in_db = True
                                processed_annotations.add(annotation)
                                break
            except Exception as e:
                logger.debug(f"Vector DB search failed for annotation @{ann_name}: {str(e)}")
            
            if not found_in_db:
                code, rewritten = self._deterministic_annotation_rewrite(code, ann_name)
                if rewritten:
                    transformation_count += 1
                    processed_annotations.add(annotation)
                else:
                    if self._should_warn_for_missing_annotation_mapping(ann_name):
                        logger.warning(f"No mapping found in vector DB for annotation: @{ann_name}, skipping transformation")
        
        # Handle parameterized mappings (e.g. @GetMapping("/path") -> @GET @Path("/path"))
        parameterized_mappings = [
            # Fix spacing for existing @GET @Path combo
            (r'@GET\s+@Path\((.*?)\)', r'@GET\n    @Path(\1)'),
            (r'@POST\s+@Path\((.*?)\)', r'@POST\n    @Path(\1)'),
            (r'@PUT\s+@Path\((.*?)\)', r'@PUT\n    @Path(\1)'),
            (r'@DELETE\s+@Path\((.*?)\)', r'@DELETE\n    @Path(\1)'),
            (r'@PATCH\s+@Path\((.*?)\)', r'@PATCH\n    @Path(\1)'),
            
            # Convert @GET("value") -> @GET @Path("value")
            (r'@GET\s*\(\s*"([^"]+)"\s*\)', r'@GET\n    @Path("\1")'),
            (r'@POST\s*\(\s*"([^"]+)"\s*\)', r'@POST\n    @Path("\1")'),
            (r'@PUT\s*\(\s*"([^"]+)"\s*\)', r'@PUT\n    @Path("\1")'),
            (r'@DELETE\s*\(\s*"([^"]+)"\s*\)', r'@DELETE\n    @Path("\1")'),
            (r'@PATCH\s*\(\s*"([^"]+)"\s*\)', r'@PATCH\n    @Path("\1")'),
        ]
        
        for pattern, replacement in parameterized_mappings:
            if re.search(pattern, code):
                code = re.sub(pattern, replacement, code)
                code = self._normalize_wildcard_path_literals(code)
                
                transformation_count += 1
        
        # Special handling: Add @ApplicationScoped to classes with @Path (REST controllers)
        if '@Path' in code and 'class' in code:
            # Find class declaration with @Path
            class_match = re.search(r'(@Path[^\n]*)\n(public\s+class\s+\w+)', code)
            if class_match:
                before_class = code[:class_match.start()]
                # Only add if it's a REST controller (has @Path) and doesn't already have @ApplicationScoped
                if '@ApplicationScoped' not in before_class[-200:]:  # Check last 200 chars before class
                    code = code.replace(class_match.group(0), '@ApplicationScoped\n' + class_match.group(0))
                    # Also add import if not present
                    if 'import jakarta.enterprise.context.ApplicationScoped' not in code:
                        # Find last import statement and add after it
                        import_match = re.search(r'(import\s+[^;]+;\s*\n)(?=\n)', code)
                        if import_match:
                            code = code.replace(import_match.group(0), import_match.group(0) + 'import jakarta.enterprise.context.ApplicationScoped;\n')
                        else:
                            # Add after package declaration
                            package_match = re.search(r'(package\s+[^;]+;\s*\n)', code)
                            if package_match:
                                code = code.replace(package_match.group(0), package_match.group(0) + '\nimport jakarta.enterprise.context.ApplicationScoped;\n')
                    transformation_count += 1
        
        # Remove duplicate @Path annotations - keep the one with value
        # Pattern: @Path\n@ApplicationScoped\n@Path("/value") -> @Path("/value")\n@ApplicationScoped
        code = re.sub(r'@Path\s*\n\s*@ApplicationScoped\s*\n\s*@Path\(([^)]+)\)', r'@Path(\1)\n@ApplicationScoped', code)
        code = re.sub(r'@Path\s*\n\s*@Path\(([^)]+)\)', r'@Path(\1)', code)
        code = re.sub(r'@Path\(([^)]+)\)\s*\n\s*@Path\s*\n', r'@Path(\1)\n', code)
        code = re.sub(r'@Path\s*\n\s*@Path\s*\n', r'@Path\n', code)
        
        # Clean up: Remove @ApplicationScoped from fields (should be @Inject)
        code = re.sub(r'@ApplicationScoped\s+private\s+(\w+)', r'@Inject\n    private \1', code)
        
        # Clean up: Remove duplicate or incorrect annotations
        code = re.sub(r'@Path\s+\+\s+@ApplicationScoped', '@Path', code)
        code = re.sub(r'@ApplicationScoped\s*\+\s*@Path', '@Path', code)
        
        # Fix: @ApplicationScoped should not be on method parameters
        code = re.sub(r'@ApplicationScoped\s+(\w+\s+\w+)', r'\1', code)  # Remove from parameters
        
        # Add @ApplicationScoped to service classes if missing
        if 'class' in code and '@Service' not in code and '@ApplicationScoped' not in code:
            # Check if it's a service (has methods like findAll, save, etc.)
            if re.search(r'(findAll|save|findById|delete)', code):
                class_match = re.search(r'(public\s+class\s+\w+)', code)
                if class_match:
                    code = code.replace(class_match.group(0), '@ApplicationScoped\n' + class_match.group(0))
                    transformation_count += 1
        
        return code, transformation_count
    
    def _transform_imports(self, code: str) -> tuple[str, int]:
        """Transform Spring imports to Jakarta/Helidon imports using Vector DB ONLY"""
        transformation_count = 0
        
        # Use vector DB ONLY - no hardcoded fallbacks
        # Find all Spring imports
        spring_import_pattern = r'import\s+(org\.springframework\.[^;]+);'
        spring_imports = re.findall(spring_import_pattern, code)
        
        for spring_import in spring_imports:
            # Try vector DB - use metadata filter for exact match
            found_in_db = False
            try:
                # Search with exact import string and metadata filter
                embedding = self.embedding_model.encode_single(spring_import)
                
                # Search with filter for exact spring_pattern match
                results = self.knowledge_base.search(
                    collection_name='imports',
                    query_embedding=embedding,
                    top_k=10,
                    filters={'spring_pattern': spring_import}  # Exact match filter
                )
                
                if results and len(results) > 0:
                    for result in results:
                        metadata = result.get('metadata', {})
                        if metadata.get('migration_type') == 'import':
                            spring_pattern = metadata.get('spring_pattern', '')
                            # Should be exact match due to filter, but double-check
                            if spring_import == spring_pattern:
                                helidon_pattern = metadata.get('helidon_pattern', '')
                                if helidon_pattern == '':
                                    code = re.sub(rf'import\s+{re.escape(spring_import)};\s*\n?', '', code)
                                else:
                                    code = re.sub(
                                        rf'import\s+{re.escape(spring_import)};',
                                        f'import {helidon_pattern};',
                                        code
                                    )
                                transformation_count += 1
                                found_in_db = True
                                break
            except Exception as e:
                logger.debug(f"Vector DB search failed for import {spring_import}: {str(e)}")
            
            if not found_in_db:
                deterministic_import = self._deterministic_import_rewrite(spring_import)
                if deterministic_import:
                    code = re.sub(
                        rf'import\s+{re.escape(spring_import)};',
                        f'import {deterministic_import};',
                        code
                    )
                    transformation_count += 1
                else:
                    if self._should_warn_for_missing_import_mapping(spring_import):
                        logger.warning(f"No mapping found in vector DB for import: {spring_import}, skipping transformation")
        
        # Remove any remaining Spring imports that weren't transformed (cleanup)
        remaining_spring = re.findall(spring_import_pattern, code)
        for imp in remaining_spring:
            if self._should_warn_for_missing_import_mapping(imp):
                logger.warning(f"Removing untransformed Spring import: {imp}")
            else:
                logger.debug(f"Removing cleaned-up Spring import: {imp}")
            code = re.sub(rf'import\s+{re.escape(imp)};\s*\n?', '', code)
            transformation_count += 1
        
        # Remove empty import lines
        code = re.sub(r'import\s+;\s*\n', '', code)
        
        return code, transformation_count

    def _should_warn_for_missing_annotation_mapping(self, ann_name: str) -> bool:
        """Suppress noise for annotations that are non-actionable or handled elsewhere."""
        quiet_annotations = {
            'Around',
            'Aspect',
            'AuthzCheck',
            'author',
            'Bean',
            'ConfigurationProperties',
            'ComponentScan',
            'DeleteMapping',
            'EnableJpaRepositories',
            'EntityScan',
            'FilterSystemMetadataLogs',
            'GetMapping',
            'Getter',
            'interface',
            'Order',
            'Override',
            'param',
            'PatchMapping',
            'PostConstruct',
            'PostMapping',
            'PutMapping',
            'RequestBody',
            'RequestMapping',
            'RequestScoped',
            'RequestHeader',
            'RequestParam',
            'ResponseStatus',
            'Retention',
            'return',
            'Setter',
            'Slf4j',
            'SpringBootApplication',
            'Target',
            'throws',
            'ToString',
            'version',
            'PathVariable',
        }
        if ann_name in quiet_annotations:
            return False
        if ann_name.startswith('jakarta'):
            return False
        return True

    def _should_warn_for_missing_import_mapping(self, spring_import: str) -> bool:
        """Suppress import warnings for Spring APIs cleaned up by later deterministic passes."""
        quiet_imports = {
            'org.springframework.beans.BeanUtils',
            'org.springframework.boot.SpringApplication',
            'org.springframework.boot.autoconfigure.SpringBootApplication',
            'org.springframework.boot.autoconfigure.domain.EntityScan',
            'org.springframework.boot.web.servlet.FilterRegistrationBean',
            'org.springframework.cloud.gateway.mvc.config.ProxyProperties',
            'org.springframework.context.annotation.Bean',
            'org.springframework.context.annotation.ComponentScan',
            'org.springframework.dao.DataIntegrityViolationException',
            'org.springframework.data.jpa.repository.config.EnableJpaRepositories',
            'org.springframework.http.HttpHeaders',
            'org.springframework.http.HttpMethod',
            'org.springframework.http.HttpStatus',
            'org.springframework.http.MediaType',
            'org.springframework.http.ResponseEntity',
            'org.springframework.http.client.BufferingClientHttpRequestFactory',
            'org.springframework.http.client.ClientHttpResponse',
            'org.springframework.http.client.SimpleClientHttpRequestFactory',
            'org.springframework.util.MultiValueMap',
            'org.springframework.web.bind.annotation.DeleteMapping',
            'org.springframework.web.bind.annotation.GetMapping',
            'org.springframework.web.bind.annotation.PatchMapping',
            'org.springframework.web.bind.annotation.PathVariable',
            'org.springframework.web.bind.annotation.PostMapping',
            'org.springframework.web.bind.annotation.PutMapping',
            'org.springframework.web.bind.annotation.RequestBody',
            'org.springframework.web.bind.annotation.RequestMethod',
            'org.springframework.web.bind.annotation.RestController',
            'org.springframework.web.client.ResponseErrorHandler',
            'org.springframework.web.client.RestTemplate',
            'org.springframework.web.util.UriComponentsBuilder',
            'org.springframework.core.Ordered',
            'org.springframework.core.annotation.Order',
        }
        return spring_import not in quiet_imports
        
        # Remove empty imports
        code = re.sub(r'import\s*;\s*\n', '', code)
        code = re.sub(r'import\s+;\s*\n', '', code)
        
        # Transform Spring Boot main class to Helidon MP main class
        code = self._transform_main_class(code)
        
        # Transform Spring Data JPA repositories to CDI beans with EntityManager
        code = self._transform_repository(code)
        
        return code, transformation_count
    
    def _transform_main_class(self, code: str) -> str:
        """Transform Spring Boot main class to Helidon MP main class"""
        # Check if this is a main class (has main method)
        if 'public static void main' not in code:
            return code
        had_entity_scan = '@EntityScan' in code
        had_enable_jpa_repositories = '@EnableJpaRepositories' in code
        entity_scan_package = self._extract_annotation_string_arg(code, 'EntityScan')
        repository_scan_package = self._extract_annotation_string_arg(code, 'EnableJpaRepositories')
        
        # Remove @SpringBootApplication if still present
        code = re.sub(r'@SpringBootApplication\s*\n', '', code)
        code = re.sub(r'@SpringBootApplication', '', code)
        code = re.sub(r'@ComponentScan\([^)]*\)\s*\n', '', code)
        code = re.sub(r'@EntityScan\([^)]*\)\s*\n', '', code)
        code = re.sub(r'@EnableJpaRepositories\([^)]*\)\s*\n', '', code)
        code = re.sub(r'@ComponentScan\s*\n', '', code)
        code = re.sub(r'@EntityScan\s*\n', '', code)
        code = re.sub(r'@EnableJpaRepositories\s*\n', '', code)
        
        # Remove Spring Boot imports
        code = re.sub(r'import\s+org\.springframework\.boot\.[^;]+;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.context\.annotation\.ComponentScan;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.boot\.autoconfigure\.domain\.EntityScan;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.data\.jpa\.repository\.config\.EnableJpaRepositories;\s*\n?', '', code)
        
        # 1. Add JAX-RS Application imports if missing
        if 'jakarta.ws.rs.core.Application' not in code:
            # Check for package declaration
            package_match = re.search(r'package\s+[^;]+;\s*\n', code)
            imports_to_add = 'import jakarta.ws.rs.ApplicationPath;\nimport jakarta.ws.rs.core.Application;\n'
            
            if package_match:
                # Insert after package declaration
                insert_pos = package_match.end()
                code = code[:insert_pos] + imports_to_add + code[insert_pos:]
            else:
                # Insert at top
                code = imports_to_add + code
            
        # 2. Make class extend Application and add @ApplicationPath
        # Only if it doesn't already extend something
        class_match = re.search(r'public\s+class\s+(\w+)', code)
        if class_match and 'extends' not in class_match.group(0):
            class_name = class_match.group(1)
            code = code.replace(
                f'public class {class_name}',
                f'@ApplicationPath("/")\npublic class {class_name} extends Application'
            )

        if '@ApplicationPath' in code and '@ApplicationScoped' not in code:
            main_class_needs_cdi = any(marker in code for marker in ['@Inject', '@ConfigProperty', '@PostConstruct'])
            if main_class_needs_cdi:
                code = code.replace('@ApplicationPath("/")', '@ApplicationScoped\n@ApplicationPath("/")', 1)

        if had_entity_scan or had_enable_jpa_repositories:
            class_match = re.search(r'(public\s+class\s+\w+\s+extends\s+Application)', code)
            if class_match and 'TODO Manual review: verify JPA entity scanning' not in code:
                todo_lines = []
                if had_entity_scan:
                    todo_lines.append('// TODO Manual review: verify annotated JPA entities are discovered by the configured Helidon/JPA provider.')
                    if entity_scan_package:
                        todo_lines.append(f'// Original entity scan package: {entity_scan_package}')
                if had_enable_jpa_repositories:
                    todo_lines.append('// TODO Manual review: replace repository auto-discovery with CDI/JPA repository beans where needed.')
                    if repository_scan_package:
                        todo_lines.append(f'// Original repository scan package: {repository_scan_package}')
                todo_lines.append('// Helidon MP keeps jakarta.persistence annotations on entities, but legacy bootstrapping annotations do not apply.')
                code = code[:class_match.start()] + '\n'.join(todo_lines) + '\n' + code[class_match.start():]
            
        # 3. Replace SpringApplication.run() with Helidon MP main
        if 'SpringApplication.run' in code:
            # Find the main method fully
            # Matches: public static void main(String[] args) { ... }
            main_pattern = r'public static void main\s*\([^)]+\)\s*\{[^}]*\}'
            main_match = re.search(main_pattern, code, re.DOTALL)
            
            helidon_main = '''public static void main(String[] args) {
        io.helidon.microprofile.cdi.Main.main(args);
    }'''
            
            if main_match:
                code = code.replace(main_match.group(0), helidon_main)
            else:
                # Fallback simple replacement within method body if regex fails to match whole block
                code = code.replace('SpringApplication.run(DemoApplication.class, args);', 
                                  'io.helidon.microprofile.cdi.Main.main(args);')
                code = code.replace('SpringApplication.run(', 'io.helidon.microprofile.cdi.Main.main(')
        
        # Clean up any remaining Spring imports
        code = re.sub(r'import\s+org\.springframework\.[^;]+;\s*\n?', '', code)
        
        # Remove empty import lines
        code = re.sub(r'import\s+;\s*\n', '', code)
        code = re.sub(r'import\s+;\s*\n', '', code)
        
        return code

    def _extract_annotation_string_arg(self, code: str, annotation_name: str) -> str | None:
        """Extract a simple quoted package from a Spring annotation like @EntityScan("com.example")."""
        match = re.search(rf'@{re.escape(annotation_name)}\(\s*"([^"]+)"\s*\)', code)
        if match:
            return match.group(1).strip()
        return None

    def _ensure_imports(self, code: str) -> str:
        """Ensure required Jakarta/Helidon imports are present based on usage"""
        
        # Mapping of usage token -> Import statement
        required_imports = {
            '@Path': 'jakarta.ws.rs.Path',
            '@GET': 'jakarta.ws.rs.GET',
            '@POST': 'jakarta.ws.rs.POST',
            '@PUT': 'jakarta.ws.rs.PUT',
            '@DELETE': 'jakarta.ws.rs.DELETE',
            '@PATCH': 'jakarta.ws.rs.PATCH',
            '@HEAD': 'jakarta.ws.rs.HEAD',
            '@OPTIONS': 'jakarta.ws.rs.OPTIONS',
            '@PathParam': 'jakarta.ws.rs.PathParam',
            '@HeaderParam': 'jakarta.ws.rs.HeaderParam',
            '@QueryParam': 'jakarta.ws.rs.QueryParam',
            '@Context': 'jakarta.ws.rs.core.Context',
            '@Consumes': 'jakarta.ws.rs.Consumes',
            '@Produces(': 'jakarta.ws.rs.Produces',
            '@Inject': 'jakarta.inject.Inject',
            '@Named': 'jakarta.inject.Named',
            '@ApplicationScoped': 'jakarta.enterprise.context.ApplicationScoped',
            '@RequestScoped': 'jakarta.enterprise.context.RequestScoped',
            '@ConfigProperty': 'org.eclipse.microprofile.config.inject.ConfigProperty',
            '@ConfigProperties': 'org.eclipse.microprofile.config.inject.ConfigProperties',
            '@BeforeAll': 'org.junit.jupiter.api.BeforeAll',
            '@ExtendWith': 'org.junit.jupiter.api.extension.ExtendWith',
            '@Entity': 'jakarta.persistence.Entity',
            '@Table': 'jakarta.persistence.Table',
            '@Id': 'jakarta.persistence.Id',
            '@GeneratedValue': 'jakarta.persistence.GeneratedValue',
            '@Column': 'jakarta.persistence.Column',
            'Response': 'jakarta.ws.rs.core.Response',
            'MediaType': 'jakarta.ws.rs.core.MediaType',
            'HttpHeaders': 'jakarta.ws.rs.core.HttpHeaders',
            'UriBuilder': 'jakarta.ws.rs.core.UriBuilder',
            'UriInfo': 'jakarta.ws.rs.core.UriInfo',
            'MultivaluedMap': 'jakarta.ws.rs.core.MultivaluedMap',
            'MultivaluedHashMap': 'jakarta.ws.rs.core.MultivaluedHashMap',
            'MockitoExtension': 'org.mockito.junit.jupiter.MockitoExtension',
            'PersistenceException': 'jakarta.persistence.PersistenceException',
            'ProcessingException': 'jakarta.ws.rs.ProcessingException',
            'EntityManager': 'jakarta.persistence.EntityManager',
            'PersistenceContext': 'jakarta.persistence.PersistenceContext',
        }
        
        # Find where to insert imports (after existing imports or after package)
        package_match = re.search(r'package\s+[^;]+;\s*\n', code)
        last_import = list(re.finditer(r'import\s+[^;]+;\s*\n', code))
        
        insert_pos = 0
        if last_import:
            insert_pos = last_import[-1].end()
        elif package_match:
            insert_pos = package_match.end()
            
        imports_to_add = set()
        
        for token, import_pkg in required_imports.items():
            # Check if token is used
            # Handle start of string, whitespace, or other non-word chars before
            # Handle end of string, whitespace, or other non-word chars after
            # Simple check: (?:^|\s)token(?:\s|$) -- too simple
            # Better: re.search but be careful with \b and @
            
            # If token starts with @ (annotation)
            if token.startswith('@'):
                # Look for token followed by non-word char or end of string
                # We don't care about what's before @ usually (Start of line or space)
                pattern = re.escape(token) + r'(?!\w)'
            else:
                # Normal class name
                pattern = r'\b' + re.escape(token) + r'\b'
                
            if re.search(pattern, code):
                # Check if already imported (strict check)
                if f'import {import_pkg};' not in code:
                    imports_to_add.add(f'import {import_pkg};\n')
                    
        if imports_to_add:
            sorted_imports = sorted(list(imports_to_add))
            code = code[:insert_pos] + ''.join(sorted_imports) + code[insert_pos:]

        code = self._disambiguate_produces_annotations(code)
            
        return code

    def _remove_unused_imports(self, code: str) -> str:
        """Drop simple unused imports left behind after Spring rewrites."""
        import_pattern = re.compile(r'^(import\s+(static\s+)?([^;]+);)\s*$', re.MULTILINE)
        matches = list(import_pattern.finditer(code))
        if not matches:
            return code

        body = import_pattern.sub('', code)
        kept_imports = []
        for match in matches:
            full_line = match.group(1)
            is_static = match.group(2) is not None
            import_name = match.group(3)

            if is_static or import_name.endswith('.*'):
                kept_imports.append(full_line)
                continue

            simple_name = import_name.split('.')[-1]
            if re.search(rf'\b{re.escape(simple_name)}\b', body):
                kept_imports.append(full_line)

        deduped_imports = []
        seen_imports = set()
        for import_line in kept_imports:
            if import_line in seen_imports:
                continue
            seen_imports.add(import_line)
            deduped_imports.append(import_line)

        code = import_pattern.sub('', code)

        package_match = re.search(r'package\s+[^;]+;\s*\n', code)
        insert_pos = package_match.end() if package_match else 0
        import_block = ''
        if deduped_imports:
            import_block = '\n' + '\n'.join(deduped_imports) + '\n'

        code = code[:insert_pos] + import_block + code[insert_pos:]
        code = re.sub(r'\n{3,}', '\n\n', code)
        return code

    def _reindent_java_code(self, code: str) -> str:
        """Apply a lightweight indentation pass so generated Java is reviewable."""
        lines = code.splitlines()
        reformatted: List[str] = []
        indent_level = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                reformatted.append('')
                continue

            open_count = line.count('{')
            close_count = line.count('}')

            current_indent = indent_level
            if stripped.startswith('}'):
                current_indent = max(indent_level - 1, 0)

            if stripped.startswith(('package ', 'import ')):
                current_indent = 0
            elif stripped.startswith('@') and indent_level > 0:
                current_indent = indent_level
            elif stripped.startswith('*') and indent_level > 0:
                current_indent = indent_level

            reformatted.append(('    ' * max(current_indent, 0)) + stripped)
            indent_level += open_count - close_count
            if indent_level < 0:
                indent_level = 0

        return '\n'.join(reformatted) + ('\n' if code.endswith('\n') else '')
    
    def _transform_repository(self, code: str) -> str:
        """Transform Spring Data JPA repository interface to CDI bean with EntityManager"""
        # Check if this is a Spring Data JPA repository (extends JpaRepository)
        if 'JpaRepository' in code and 'interface' in code:
            # Extract package name
            package_match = re.search(r'package\s+([^;]+);', code)
            package_name = package_match.group(1) if package_match else 'com.example.demo'
            
            # Extract class name
            class_match = re.search(r'(?:public\s+)?interface\s+(\w+)', code)
            class_name = class_match.group(1) if class_match else 'Repository'
            
            # Extract entity type from JpaRepository<EntityType, IDType>
            entity_match = re.search(r'JpaRepository<(\w+),\s*(\w+)>', code)
            if entity_match:
                entity_type = entity_match.group(1)
                id_type = entity_match.group(2)
                
                # Convert interface to class with EntityManager
                helidon_repo = f'''package {package_name};

import jakarta.enterprise.context.ApplicationScoped;
import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import java.util.List;
import java.util.Optional;

/**
 * Equivalent CDI/JPA repository generated from legacy repository auto-discovery.
 * Repository discovery is handled explicitly through CDI beans and EntityManager usage.
 */
@ApplicationScoped
public class {class_name} {{
    
    // Backing store managed through CDI/JPA.
    @PersistenceContext
    private EntityManager entityManager;
    
    public List<{entity_type}> findAll() {{
        return entityManager.createQuery("SELECT e FROM {entity_type} e", {entity_type}.class).getResultList();
    }}
    
    public Optional<{entity_type}> findById({id_type} id) {{
        return Optional.ofNullable(entityManager.find({entity_type}.class, id));
    }}
    
    public {entity_type} save({entity_type} entity) {{
        if (entityManager.find({entity_type}.class, getId(entity)) == null) {{
            entityManager.persist(entity);
        }} else {{
            entity = entityManager.merge(entity);
        }}
        return entity;
    }}
    
    public void deleteById({id_type} id) {{
        {entity_type} entity = entityManager.find({entity_type}.class, id);
        if (entity != null) {{
            entityManager.remove(entity);
        }}
    }}
    
    private {id_type} getId({entity_type} entity) {{
        // Assuming entity has getId() method
        try {{
            return ({id_type}) entity.getClass().getMethod("getId").invoke(entity);
        }} catch (Exception e) {{
            throw new RuntimeException("Entity must have getId() method", e);
        }}
    }}
}}'''
                
                # Replace the entire interface - match everything from package to end
                # More robust pattern matching
                lines = code.split('\n')
                start_idx = 0
                end_idx = len(lines)
                
                # Find package line
                for i, line in enumerate(lines):
                    if line.strip().startswith('package'):
                        start_idx = i
                        break
                
                # Find interface declaration
                interface_start = None
                brace_count = 0
                for i in range(start_idx, len(lines)):
                    if 'interface' in lines[i] and 'JpaRepository' in lines[i]:
                        interface_start = i
                        brace_count = lines[i].count('{') - lines[i].count('}')
                        if brace_count == 0:  # Interface ends on same line
                            end_idx = i + 1
                            break
                        continue
                    if interface_start is not None:
                        brace_count += lines[i].count('{') - lines[i].count('}')
                        if brace_count == 0:
                            end_idx = i + 1
                            break
                
                if interface_start is not None:
                    # Replace the interface section
                    before = '\n'.join(lines[:start_idx]) if start_idx > 0 else ''
                    after = '\n'.join(lines[end_idx:]) if end_idx < len(lines) else ''
                    code = (before + '\n' + helidon_repo + '\n' + after).strip()
        
        return code

    def _transform_cloud_gateway(self, code: str) -> str:
        """
        Transform Spring Cloud Gateway MVC patterns (e.g. ProxyExchange)
        Generates equivalent helper classes in Helidon/JAX-RS
        """
        gateway_markers = ['ProxyExchange', 'ProxyExchangeArgumentResolver', 'RestTemplateBuilder', 'ProxyProperties']
        if not any(marker in code for marker in gateway_markers):
            return code

        package_match = re.search(r'package\s+([^;]+);', code)
        current_package = package_match.group(1) if package_match else 'com.example.demo'
        support_package = self._shared_proxy_support_package(current_package)
            
        # 1. Handle Imports
        if 'org.springframework.cloud.gateway.mvc.ProxyExchange' in code:
            # Replace import
            code = code.replace(
                'import org.springframework.cloud.gateway.mvc.ProxyExchange;', 
                f'import {support_package}.ProxyExchange;'
            )
            
            # Generate the Shim Class file
            self._generate_proxy_exchange_shim(support_package)

        is_proxy_exchange_intercept_config = (
            'ProxyExchangeArgumentResolver' in code
            or re.search(r'\bclass\s+ProxyExchangeIntercept\b', code) is not None
            or re.search(r'\bProxyExchangeArgumentResolver\s+\w+\s*\(', code) is not None
        )
        if is_proxy_exchange_intercept_config:
            self._generate_proxy_exchange_shim(support_package)
            return self._build_proxy_exchange_producer(current_package, support_package)
            
        # Remove implements GatewayMvcConfigurer and WebMvcConfigurer
        code = re.sub(r'\s+implements\s+(?:GatewayMvcConfigurer|WebMvcConfigurer)(?:,\s*\w+)*(\s*{)', r'\1', code)
        # Handle case where it's in a list of interfaces
        code = re.sub(r',\s*(?:GatewayMvcConfigurer|WebMvcConfigurer)\b', '', code)
        code = re.sub(r'(?:GatewayMvcConfigurer|WebMvcConfigurer),\s*', '', code)
        
        code = re.sub(r'import\s+org\.springframework\.cloud\.gateway\.mvc\.config\.GatewayMvcConfigurer;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.web\.servlet\.config\.annotation\.WebMvcConfigurer;\s*\n?', '', code)
            
        # 2. Refactor resource-method injection to field injection, but preserve
        # service-layer ProxyExchange parameters because controllers pass the proxy through.
        if self._is_resource_controller(code):
            code = self._normalize_proxy_exchange_usage(code)

        return code

    def _build_proxy_exchange_producer(self, package_name: str, support_package: str) -> str:
        """Build a Helidon-friendly producer for ProxyExchange shim instances."""
        self._generate_proxy_exchange_client_response_filter(support_package)
        return f'''package {package_name};

import {support_package}.ProxyExchange;
import {support_package}.ProxyExchangeClientResponseFilter;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.enterprise.context.RequestScoped;
import jakarta.enterprise.inject.Produces;
import jakarta.inject.Inject;
import jakarta.inject.Named;
import jakarta.ws.rs.client.Client;
import jakarta.ws.rs.client.ClientBuilder;
import lombok.extern.slf4j.Slf4j;

@Slf4j
@ApplicationScoped
public class ProxyExchangeIntercept {{

    @Inject
    private ProxyExchangeClientResponseFilter proxyExchangeClientResponseFilter;

    /**
     * Helidon MP equivalent of the legacy proxy argument resolver setup.
     * The generated ProxyExchange shim performs request-scoped forwarding and delegates
     * response error handling to CustomResponseErrorHandler when that bean exists.
     * TODO Manual review: map original header forwarding and sensitive-header rules explicitly if needed.
     */
    @Produces
    @ApplicationScoped
    @Named("proxyExchangeClient")
    public Client proxyExchangeClient() {{
        return ClientBuilder.newBuilder()
                .register(proxyExchangeClientResponseFilter)
                .build();
    }}

    @Produces
    @RequestScoped
    public ProxyExchange<byte[]> proxyExchange(@Named("proxyExchangeClient") Client client) {{
        return new ProxyExchange<>(client);
    }}
}}
'''

    def _find_custom_response_error_handler_fqcn(self) -> str | None:
        """Locate a migrated CustomResponseErrorHandler so ProxyExchange can reuse it."""
        if not hasattr(self, 'target_path') or not self.target_path:
            return None

        try:
            for candidate in self.target_path.rglob('CustomResponseErrorHandler.java'):
                try:
                    content = candidate.read_text(encoding='utf-8')
                except Exception:
                    continue
                package_match = re.search(r'package\s+([^;]+);', content)
                if package_match:
                    return f'{package_match.group(1)}.CustomResponseErrorHandler'
        except Exception:
            return None

        return None

    def _generate_proxy_exchange_shim(self, package_name: str):
        """Generate a Helper class for ProxyExchange to mimic Spring functionality"""
        if not hasattr(self, 'target_path') or not self.target_path:
            return

        # Determine module root by locating nearest pom.xml
        module_root = self.target_path
        try:
            for pom in self.target_path.rglob('pom.xml'):
                module_root = pom.parent
                break
        except Exception:
            module_root = self.target_path

        # Determine path
        package_path = package_name.replace('.', '/')
        output_file = module_root / 'src/main/java' / package_path / 'ProxyExchange.java'
        
        # Create directory
        output_file.parent.mkdir(parents=True, exist_ok=True)
        error_handler_fqcn = self._find_custom_response_error_handler_fqcn()
        extra_imports = ''
        error_handler_member = ''
        error_handler_helper = '''

    private Response applyErrorHandler(Response response) {
        return response;
    }
'''
        if error_handler_fqcn:
            extra_imports = (
                'import jakarta.inject.Inject;\n'
                f'import {error_handler_fqcn};\n'
            )
            error_handler_member = '\n    @Inject\n    private CustomResponseErrorHandler customResponseErrorHandler;\n'
            error_handler_helper = '''

    private Response applyErrorHandler(Response response) {
        if (response == null) {
            return null;
        }
        try {
            if (customResponseErrorHandler != null && customResponseErrorHandler.hasError(response)) {
                customResponseErrorHandler.handleError(response);
            }
            return response;
        } catch (java.io.IOException ex) {
            throw new jakarta.ws.rs.ProcessingException("ProxyExchange error handling failed", ex);
        }
    }
'''

        shim_code = f'''package {package_name};

import jakarta.enterprise.context.RequestScoped;
{extra_imports}import jakarta.ws.rs.client.Client;
import jakarta.ws.rs.client.ClientBuilder;
import jakarta.ws.rs.client.Entity;
import jakarta.ws.rs.client.Invocation;
import jakarta.ws.rs.core.Context;
import jakarta.ws.rs.core.HttpHeaders;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.MultivaluedHashMap;
import jakarta.ws.rs.core.MultivaluedMap;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.core.UriInfo;
import java.net.URI;
import java.util.List;
import java.util.Map;

/**
 * Compatibility shim for legacy proxy forwarding behavior.
 * Generated by Spring2Don-RAG Migration Agent.
 */
@RequestScoped
public class ProxyExchange<T> {{
    
    private final Client client;
    private URI targetUri;
    private final MultivaluedMap<String, Object> outboundHeaders = new MultivaluedHashMap<>();
    private Entity<?> requestEntity;
{error_handler_member}    
    @Context
    private UriInfo uriInfo;

    @Context
    private HttpHeaders inboundHeaders;
    
    public ProxyExchange() {{
        this(ClientBuilder.newClient());
    }}

    public ProxyExchange(Client client) {{
        this.client = client != null ? client : ClientBuilder.newClient();
    }}
    
    public ProxyExchange<T> uri(URI uri) {{
        this.targetUri = uri;
        return this;
    }}
    
    public ProxyExchange<T> uri(String uri) {{
        this.targetUri = URI.create(uri);
        return this;
    }}

    public ProxyExchange<T> headers(Object headers) {{
        if (headers instanceof HttpHeaders httpHeaders) {{
            mergeHeaders(httpHeaders.getRequestHeaders());
        }} else if (headers instanceof MultivaluedMap<?, ?> multiValueMap) {{
            for (Map.Entry<?, ?> entry : multiValueMap.entrySet()) {{
                if (entry.getKey() == null || entry.getValue() == null) {{
                    continue;
                }}
                if (!(entry.getValue() instanceof List<?> values)) {{
                    continue;
                }}
                for (Object value : values) {{
                    if (value != null) {{
                        outboundHeaders.add(String.valueOf(entry.getKey()), value);
                    }}
                }}
            }}
        }}
        return this;
    }}

    public ProxyExchange<T> header(String name, Object value) {{
        outboundHeaders.putSingle(name, value);
        return this;
    }}

    public ProxyExchange<T> body(byte[] body) {{
        this.requestEntity = Entity.entity(body, MediaType.APPLICATION_OCTET_STREAM_TYPE);
        return this;
    }}

    public ProxyExchange<T> entity(Object entity) {{
        if (entity instanceof byte[] bytes) {{
            return body(bytes);
        }}
        this.requestEntity = Entity.entity(entity, resolveMediaType());
        return this;
    }}
    
    public String path(String prefix) {{
        String path = uriInfo.getRequestUri().getPath();
        if (path.startsWith(prefix)) {{
            return path.substring(prefix.length());
        }}
        return path;
    }}

    private void mergeHeaders(MultivaluedMap<String, String> headers) {{
        if (headers == null) {{
            return;
        }}
        for (Map.Entry<String, List<String>> entry : headers.entrySet()) {{
            if (entry.getValue() == null) {{
                continue;
            }}
            for (String value : entry.getValue()) {{
                if (value != null) {{
                    outboundHeaders.add(entry.getKey(), value);
                }}
            }}
        }}
    }}

    private MediaType resolveMediaType() {{
        Object contentType = outboundHeaders.getFirst(HttpHeaders.CONTENT_TYPE);
        if (contentType instanceof MediaType mediaType) {{
            return mediaType;
        }}
        if (contentType != null) {{
            try {{
                return MediaType.valueOf(String.valueOf(contentType));
            }} catch (IllegalArgumentException ignored) {{
            }}
        }}
        if (inboundHeaders != null && inboundHeaders.getMediaType() != null) {{
            return inboundHeaders.getMediaType();
        }}
        return MediaType.APPLICATION_JSON_TYPE;
    }}

    private Invocation.Builder requestBuilder() {{
        Invocation.Builder builder = client.target(targetUri).request();
        for (Map.Entry<String, List<Object>> entry : outboundHeaders.entrySet()) {{
            if (entry.getValue() == null) {{
                continue;
            }}
            for (Object value : entry.getValue()) {{
                builder.header(entry.getKey(), value);
            }}
        }}
        return builder;
    }}

    private Entity<?> entityOrEmpty() {{
        return requestEntity != null ? requestEntity : Entity.entity("", resolveMediaType());
    }}
{error_handler_helper}
    public Response get() {{
        return applyErrorHandler(requestBuilder().get());
    }}
    
    public Response post() {{
        return applyErrorHandler(requestBuilder().post(entityOrEmpty()));
    }}

    public Response put() {{
        return applyErrorHandler(requestBuilder().put(entityOrEmpty()));
    }}

    public Response delete() {{
        return applyErrorHandler(requestBuilder().delete());
    }}

    public Response options() {{
        return applyErrorHandler(requestBuilder().options());
    }}

    public Response head() {{
        return applyErrorHandler(requestBuilder().head());
    }}

    public Response patch() {{
        return applyErrorHandler(requestBuilder().method("PATCH", entityOrEmpty()));
    }}
}}
'''
        # Write file
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(shim_code)
            logger.info(f"Generated ProxyExchange shim at {output_file}")
        except Exception as e:
            logger.error(f"Failed to generate shim: {e}")

    def _generate_proxy_exchange_client_response_filter(self, package_name: str) -> None:
        """Generate a client response filter that preserves legacy proxy error-handling intent."""
        if not hasattr(self, 'target_path') or not self.target_path:
            return

        error_handler_fqcn = self._find_custom_response_error_handler_fqcn()
        if not error_handler_fqcn:
            return

        module_root = self.target_path
        try:
            for pom in self.target_path.rglob('pom.xml'):
                module_root = pom.parent
                break
        except Exception:
            module_root = self.target_path

        output_file = module_root / 'src/main/java' / package_name.replace('.', '/') / 'ProxyExchangeClientResponseFilter.java'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        if output_file.exists():
            return

        filter_code = f'''package {package_name};

import {error_handler_fqcn};
import jakarta.annotation.Priority;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import jakarta.ws.rs.Priorities;
import jakarta.ws.rs.client.ClientRequestContext;
import jakarta.ws.rs.client.ClientResponseFilter;
import jakarta.ws.rs.client.ClientResponseContext;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.ext.Provider;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

/**
 * Client response filter that preserves legacy proxy error handling and
 * buffers the response body so downstream code can still read it.
 */
@Provider
@ApplicationScoped
@Priority(Priorities.USER)
public class ProxyExchangeClientResponseFilter implements ClientResponseFilter {{

    @Inject
    private CustomResponseErrorHandler customResponseErrorHandler;

    @Override
    public void filter(ClientRequestContext requestContext, ClientResponseContext responseContext) throws IOException {{
        if (responseContext == null || customResponseErrorHandler == null) {{
            return;
        }}

        Response.Status.Family family = responseContext.getStatusInfo().getFamily();
        if (family != Response.Status.Family.CLIENT_ERROR && family != Response.Status.Family.SERVER_ERROR) {{
            return;
        }}

        byte[] body = responseContext.getEntityStream() != null
                ? responseContext.getEntityStream().readAllBytes()
                : new byte[0];
        responseContext.setEntityStream(new ByteArrayInputStream(body));

        Response response = Response.status(responseContext.getStatus())
                .entity(new String(body, StandardCharsets.UTF_8))
                .build();
        customResponseErrorHandler.handleError(requestContext.getUri(), requestContext.getMethod(), response);
    }}
}}
'''
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(filter_code)
            logger.info(f"Generated proxy client response filter at {output_file}")
        except Exception as e:
            logger.error(f"Failed to generate proxy client response filter: {e}")

    def _generate_property_copy_support(self, package_name: str) -> None:
        """Generate a reusable BeanUtils.copyProperties replacement in the shared support package."""
        if not hasattr(self, 'target_path') or not self.target_path:
            return

        module_root = self.target_path
        try:
            for pom in self.target_path.rglob('pom.xml'):
                module_root = pom.parent
                break
        except Exception:
            module_root = self.target_path

        package_path = package_name.replace('.', '/')
        output_file = module_root / 'src/main/java' / package_path / 'PropertyCopySupport.java'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        if output_file.exists():
            return

        support_code = f'''package {package_name};

/**
 * Shared reflection-based property copy helper.
 * Generated so migrated resources can keep their original intent without embedding
 * ad-hoc helper methods directly inside controllers or services.
 */
public final class PropertyCopySupport {{

    private PropertyCopySupport() {{
    }}

    public static void copyProperties(Object source, Object target) {{
        if (source == null || target == null) {{
            return;
        }}
        try {{
            java.beans.PropertyDescriptor[] sourceProperties =
                    java.beans.Introspector.getBeanInfo(source.getClass()).getPropertyDescriptors();
            java.beans.PropertyDescriptor[] targetProperties =
                    java.beans.Introspector.getBeanInfo(target.getClass()).getPropertyDescriptors();
            java.util.Map<String, java.beans.PropertyDescriptor> targetByName = new java.util.HashMap<>();
            for (java.beans.PropertyDescriptor targetProperty : targetProperties) {{
                targetByName.put(targetProperty.getName(), targetProperty);
            }}
            for (java.beans.PropertyDescriptor sourceProperty : sourceProperties) {{
                if ("class".equals(sourceProperty.getName()) || sourceProperty.getReadMethod() == null) {{
                    continue;
                }}
                java.beans.PropertyDescriptor targetProperty = targetByName.get(sourceProperty.getName());
                if (targetProperty == null || targetProperty.getWriteMethod() == null) {{
                    continue;
                }}
                Object value = sourceProperty.getReadMethod().invoke(source);
                targetProperty.getWriteMethod().invoke(target, value);
            }}
        }} catch (ReflectiveOperationException | java.beans.IntrospectionException ex) {{
            throw new RuntimeException(ex);
        }}
    }}
}}
'''
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(support_code)
            logger.info(f"Generated PropertyCopySupport helper at {output_file}")
        except Exception as e:
            logger.error(f"Failed to generate PropertyCopySupport helper: {e}")
