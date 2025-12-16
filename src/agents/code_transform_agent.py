"""
Code Transform Agent
Transforms Java source code from Spring Boot to Helidon MP
"""

from pathlib import Path
from typing import Dict, List
import re
import javalang
import sys
import time
import json
import uuid
from datetime import datetime
from src.config.settings import Settings
from src.rag.knowledge_base import KnowledgeBase
from src.rag.embeddings import EmbeddingModel
from src.rag.llm_provider import LLMProviderFactory
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class CodeTransformAgent:
    """Transforms Java code from Spring Boot to Helidon MP"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.knowledge_base = KnowledgeBase(settings)
        self.embedding_model = EmbeddingModel(settings)
        self.llm_provider = LLMProviderFactory.create(settings)
        
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
        
        print(f"   Found {total_files} Java file(s) to migrate")
        sys.stdout.flush()
        
        for idx, java_file in enumerate(java_files, 1):
            file_start_time = time.time()
            file_name = java_file.name
            file_path = str(java_file.relative_to(self.target_path) if hasattr(self, 'target_path') else java_file)
            
            try:
                print(f"   [{idx}/{total_files}] Migrating: {file_name}...", end=' ', flush=True)
                sys.stdout.flush()
                
                result = self._migrate_file(java_file)
                file_time = time.time() - file_start_time
                
                if result['success']:
                    migrated_files.append(str(java_file))
                    transformations = result.get('transformations', 0)
                    transformations_applied += transformations
                    print(f"[OK] ({file_time:.1f}s, {transformations} transformations)")
                else:
                    error = result.get('error', 'Unknown error')
                    print(f"[FAIL] ({file_time:.1f}s)")
                    print(f"      Error: {error}")
                    logger.error(f"Error migrating {java_file}: {error}")
                    
            except Exception as e:
                file_time = time.time() - file_start_time
                print(f"[EXCEPTION] ({file_time:.1f}s)")
                print(f"      Exception: {type(e).__name__}: {str(e)}")
                logger.error(f"Exception migrating {java_file}: {str(e)}", exc_info=True)
        
        return {
            'success': True,
            'files_migrated': len(migrated_files),
            'transformations_applied': transformations_applied
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
            # 1. Retrieve Context (RAG)
            # Search for relevant patterns based on the code content
            try:
                embedding = self.embedding_model.encode_single(source_code[:1000]) # Embed first 1000 chars context
            except Exception as e:
                logger.warning(f"Embedding generation failed, using fallback: {str(e)}")
                # Fallback to regex transformation if embedding fails
                return self._fallback_regex_transform(source_code)
            
            # Search in code patterns and annotations
            try:
                code_results = self.knowledge_base.search('code_patterns', query_embedding=embedding, top_k=3)
                anno_results = self.knowledge_base.search('annotations', query_embedding=embedding, top_k=5)
            except Exception as e:
                logger.warning(f"Knowledge base search failed, using fallback: {str(e)}")
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
                # Use regex transform which now uses vector DB for all mappings
                migrated_code, _ = self._fallback_regex_transform(source_code)
                migrated_code = self._post_process_jakarta(migrated_code)
                return migrated_code, 1
            
            # MEDIUM PATH: Use patterns as context for LLM (similarity 0.7-0.9)
            context_examples = []
            for res in all_results:
                if res['similarity'] > 0.7: # Only relevant matches
                    text = res['text']
                    context_examples.append(f"--- Example Pattern ---\n{text}\n")
            
            context_str = "\n".join(context_examples) if context_examples else "No similar patterns found."
            
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
                migrated_code = self.llm_provider.generate(prompt)
            except Exception as e:
                logger.warning(f"LLM generation failed: {str(e)}, using fallback")
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
                if migrated_code and len(migrated_code.strip()) > 50:
                    # Post-process: Fix javax->jakarta
                    migrated_code = self._post_process_jakarta(migrated_code)
                    
                    # ENVIRONMENT LEARNING: Save new pattern if LLM generated it (no high similarity match)
                    if best_similarity < 0.9:
                        self._save_new_pattern(source_code, migrated_code)
                    
                    return migrated_code, 1
                else:
                    logger.warning("LLM returned empty or invalid code, using fallback")
                    return self._fallback_regex_transform(source_code)
            else:
                logger.warning("LLM returned None, using fallback")
                return self._fallback_regex_transform(source_code)
            
        except Exception as e:
            logger.error(f"LLM migration failed: {e}", exc_info=True)
            # Fallback to regex transformation if LLM fails
            logger.info("Falling back to regex transformation...")
            return self._fallback_regex_transform(source_code)
    
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
        
        # 2. General Transformations
        t_code, c1 = self._transform_annotations(transformed_code)
        t_code, c2 = self._transform_imports(t_code)
        t_code, c3 = self._transform_types(t_code) # New: Type transformation
        
        # Apply main class and repository transformations
        t_code = self._transform_main_class(t_code)
        t_code = self._transform_repository(t_code)
        t_code = self._transform_spring_configuration(t_code)
        
        # Ensure imports are present (FINAL SAFETY CHECK)
        t_code = self._ensure_imports(t_code)
        
        return t_code, c1 + c2 + c3

    def _transform_spring_configuration(self, code: str) -> str:
        """Transform Spring @Configuration classes to CDI"""
        
        # 1. @Configuration -> @ApplicationScoped
        if '@Configuration' in code:
            code = code.replace('@Configuration', '@ApplicationScoped')
            code = re.sub(r'import\s+org\.springframework\.context\.annotation\.Configuration;\s*\n?', '', code)
            
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
            code = re.sub(r'(\w+\.setErrorHandler\s*\(.*?\);)', r'// \1', code, flags=re.DOTALL)
            code = re.sub(r'(\w+\.setInterceptors\s*\(.*?\);)', r'// \1', code, flags=re.DOTALL)
            code = re.sub(r'(requestFactory\.setConnectTimeout\s*\(.*?\);)', r'// \1', code, flags=re.DOTALL)
            code = re.sub(r'(requestFactory\.setReadTimeout\s*\(.*?\);)', r'// \1', code, flags=re.DOTALL)
            
            # Global Type Replacement: RestTemplate -> Client (for arguments, fields)
            # Be careful not to replace strings or comments, but here we assume code
            code = re.sub(r'\bRestTemplate\b', 'Client', code)

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
             
        # Cleanup wrong Produces
        if 'import jakarta.enterprise.inject.Produces;' in code and 'import jakarta.ws.rs.Produces;' in code:
            code = code.replace('import jakarta.ws.rs.Produces;\n', '')
            
        return code

        
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
            
            # If not found in vector DB, log warning but don't transform (rely on vector DB only)
            if not found_in_db:
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
                # Fix Path Wildcards: "**" -> "{path: .*}" inside @Path
                # Simple heuristic: Replace "**" with "{path: .*?}" only inside @Path
                # This is risky doing globally, but typically "**" in Java strings in controllers is for paths.
                code = code.replace('"**"', '"{path: .*?}"') # Exact match
                code = code.replace('/**', '/{path: .*?}') # Path segment
                
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
        
        # Fix @RequestMapping -> @Path
        code = re.sub(r'@RequestMapping\s*\(([^)]+)\)', r'@Path(\1)', code)
        code = re.sub(r'@RequestMapping\s*\n', '@Path\n', code)
        
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
            
            # If not found in vector DB, log warning but don't transform (rely on vector DB only)
            if not found_in_db:
                logger.warning(f"No mapping found in vector DB for import: {spring_import}, skipping transformation")
        
        # Remove any remaining Spring imports that weren't transformed (cleanup)
        remaining_spring = re.findall(spring_import_pattern, code)
        for imp in remaining_spring:
            logger.warning(f"Removing untransformed Spring import: {imp}")
            code = re.sub(rf'import\s+{re.escape(imp)};\s*\n?', '', code)
            transformation_count += 1
        
        # Remove empty import lines
        code = re.sub(r'import\s+;\s*\n', '', code)
        
        return code, transformation_count
        
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
        
        # Remove @SpringBootApplication if still present
        code = re.sub(r'@SpringBootApplication\s*\n', '', code)
        code = re.sub(r'@SpringBootApplication', '', code)
        
        # Remove Spring Boot imports
        code = re.sub(r'import\s+org\.springframework\.boot\.[^;]+;\s*\n?', '', code)
        
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
        if 'public class DemoApplication' in code and 'extends' not in code:
            code = code.replace('public class DemoApplication', '@ApplicationPath("/")\npublic class DemoApplication extends Application')
            
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
        
        # Remove @ApplicationScoped from main class (not needed as it is JAX-RS Application)
        if '@ApplicationPath' in code:
            code = re.sub(r'@ApplicationScoped\s*\n', '', code)
            
        return code

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
            '@PathParam': 'jakarta.ws.rs.PathParam',
            '@QueryParam': 'jakarta.ws.rs.QueryParam',
            '@Consumes': 'jakarta.ws.rs.Consumes',
            '@Produces': 'jakarta.ws.rs.Produces',
            '@Inject': 'jakarta.inject.Inject',
            '@ApplicationScoped': 'jakarta.enterprise.context.ApplicationScoped',
            '@RequestScoped': 'jakarta.enterprise.context.RequestScoped',
            '@Entity': 'jakarta.persistence.Entity',
            '@Table': 'jakarta.persistence.Table',
            '@Id': 'jakarta.persistence.Id',
            '@GeneratedValue': 'jakarta.persistence.GeneratedValue',
            '@Column': 'jakarta.persistence.Column',
            'Response': 'jakarta.ws.rs.core.Response',
            'MediaType': 'jakarta.ws.rs.core.MediaType',
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
            
        return code
    
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

@ApplicationScoped
public class {class_name} {{
    
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
        if 'ProxyExchange' not in code:
            return code
            
        # 1. Handle Imports
        if 'org.springframework.cloud.gateway.mvc.ProxyExchange' in code:
            # Detect package to determine support package location
            package_match = re.search(r'package\s+([^;]+);', code)
            current_package = package_match.group(1) if package_match else 'com.example.demo'
            support_package = f"{current_package}.support"
            
            # Replace import
            code = code.replace(
                'import org.springframework.cloud.gateway.mvc.ProxyExchange;', 
                f'import {support_package}.ProxyExchange;'
            )
            
            # Generate the Shim Class file
            self._generate_proxy_exchange_shim(support_package)
            
        # Remove implements GatewayMvcConfigurer and WebMvcConfigurer
        code = re.sub(r'\s+implements\s+(?:GatewayMvcConfigurer|WebMvcConfigurer)(?:,\s*\w+)*(\s*{)', r'\1', code)
        # Handle case where it's in a list of interfaces
        code = re.sub(r',\s*(?:GatewayMvcConfigurer|WebMvcConfigurer)\b', '', code)
        code = re.sub(r'(?:GatewayMvcConfigurer|WebMvcConfigurer),\s*', '', code)
        
        code = re.sub(r'import\s+org\.springframework\.cloud\.gateway\.mvc\.config\.GatewayMvcConfigurer;\s*\n?', '', code)
        code = re.sub(r'import\s+org\.springframework\.web\.servlet\.config\.annotation\.WebMvcConfigurer;\s*\n?', '', code)
            
        # 2. Refactor method injection to field injection
        # Spring injects ProxyExchange into methods. JAX-RS prefers field injection for beans.
        # Pattern: public Response proxy(ProxyExchange<byte[]> proxy)
        
        # Find methods with ProxyExchange argument
        # Updated regex to handle return types with arrays (e.g. byte[])
        method_pattern = r'public\s+[\w<>[\]]+\s+\w+\s*\([^)]*ProxyExchange(?:<[^>]+>)?\s+(\w+)[^)]*\)'
        matches = list(re.finditer(method_pattern, code))
        
        if matches:
            # Remove argument from methods FIRST
            # Do this carefully to handle multiple arguments
            # Simplification: Remove "ProxyExchange<...> name" or "ProxyExchange name"
            # We add \b to ensure we don't match partial words, but main protection is delay of field insertion
            code = re.sub(r',\s*ProxyExchange(?:<[^>]+>)?\s+\w+\b', '', code) # Middle/End arg
            code = re.sub(r'ProxyExchange(?:<[^>]+>)?\s+\w+\b\s*,?', '', code) # First arg
            
            # Add @Inject field if not present (AFTER removal to avoid self-deletion)
            field_decl = '\n    @Inject\n    private ProxyExchange proxy;\n'
            # Check if field exists (it shouldn't if we just started, but logic safety)
            # Use strict check including private
            if 'private ProxyExchange proxy;' not in code:
                # Insert after class declaration
                class_match = re.search(r'public\s+class\s+\w+[^\{]*\{', code)
                if class_match:
                    insert_pos = class_match.end()
                    code = code[:insert_pos] + field_decl + code[insert_pos:]
            
            # Ensure "ProxyExchange" usage in method uses the field name "proxy"
            # If the argument name was variable (e.g. "p"), we need to replace usages
            for m in matches:
                arg_name = m.group(1)
                if arg_name != 'proxy':
                    # This is tricky because scope is local. 
                    # For now, assume arg name is 'proxy' or user fixes compilation.
                    pass 

        return code

    def _generate_proxy_exchange_shim(self, package_name: str):
        """Generate a Helper class for ProxyExchange to mimic Spring functionality"""
        if not hasattr(self, 'target_path') or not self.target_path:
            return

        # Determine path
        package_path = package_name.replace('.', '/')
        output_file = self.target_path / 'src/main/java' / package_path / 'ProxyExchange.java'
        
        # Create directory
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        shim_code = f'''package {package_name};

import jakarta.enterprise.context.RequestScoped;
import jakarta.inject.Inject;
import jakarta.ws.rs.client.Client;
import jakarta.ws.rs.client.ClientBuilder;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.core.Context;
import jakarta.ws.rs.core.UriInfo;
import java.net.URI;

/**
 * Compatibility Shim for Spring Cloud Gateway ProxyExchange
 * Generated by Spring2Don-RAG Migration Agent
 */
@RequestScoped
public class ProxyExchange<T> {{
    
    private Client client;
    private URI targetUri;
    
    @Context
    private UriInfo uriInfo;
    
    public ProxyExchange() {{
        this.client = ClientBuilder.newClient();
    }}
    
    public ProxyExchange<T> uri(URI uri) {{
        this.targetUri = uri;
        return this;
    }}
    
    public ProxyExchange<T> uri(String uri) {{
        this.targetUri = URI.create(uri);
        return this;
    }}
    
    public String path(String prefix) {{
        String path = uriInfo.getRequestUri().getPath();
        // Remove prefix if present
        if (path.startsWith(prefix)) {{
            return path.substring(prefix.length());
        }}
        return path;
    }}
    
    public Response get() {{
        return client.target(targetUri).request().get();
    }}
    
    public Response post() {{
        return client.target(targetUri).request().post(null);
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

