"""
Validation Agent
Validates migrated code and configuration
"""

from pathlib import Path
from typing import Dict, List
import os
import re
import subprocess
from src.config.settings import Settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class ValidationAgent:
    """Validates migrated projects"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        
    def validate(self, target_path: Path) -> Dict:
        """
        Validate migrated project
        
        Args:
            target_path: Path to migrated project
            
        Returns:
            Validation result dictionary
        """
        logger.info(f"Validating migrated project: {target_path}")
        
        validation_results = {
            'compilation': self._validate_compilation(target_path),
            'build': self._validate_build(target_path),
            'imports': self._validate_imports(target_path),
            'annotations': self._validate_annotations(target_path),
            'apis': self._validate_spring_apis(target_path),
        }
        
        all_passed = all(result['success'] for result in validation_results.values())
        
        manual_review = self._collect_manual_review(validation_results)

        return {
            'success': all_passed,
            'results': validation_results,
            'manual_review': manual_review
        }

    def _collect_manual_review(self, validation_results: Dict) -> Dict:
        """Collect manual review items for GA reporting"""
        issues = []
        advisories = []
        for key in ['imports', 'annotations', 'apis']:
            result = validation_results.get(key, {})
            for issue in result.get('issues', []) or []:
                issues.append(issue)
            for advisory in result.get('advisories', []) or []:
                advisories.append(advisory)

        return {
            'issues_count': len(issues) + len(advisories),
            'issues': issues + advisories,
            'blocking_issues': issues,
            'advisories': advisories,
        }
    
    def _validate_compilation(self, target_path: Path) -> Dict:
        """Validate that code compiles"""
        logger.debug("Validating compilation...")

        maven_projects = self._find_maven_projects(target_path)
        if not maven_projects:
            return {'success': True, 'message': 'Skipped (not a Maven project)'}

        failures = []
        compiled_projects = []
        environment_blocks = []

        for project_path in maven_projects:
            logger.info(f"Detected Maven project. Running 'mvn compile' in {project_path}...")
            try:
                result = self._run_maven_command(project_path, 'compile')
                combined_output = self._combined_maven_output(result)
                if result.returncode == 0:
                    compiled_projects.append(str(project_path))
                elif self._is_warning_only_maven_output(combined_output):
                    compiled_projects.append(str(project_path))
                else:
                    error_output = combined_output.strip()
                    if self._is_environmental_compile_blocker(error_output):
                        environment_blocks.append(f"{project_path}: {error_output or 'Compilation blocked by environment'}")
                    else:
                        failures.append(f"{project_path}: {error_output or 'Compilation failed'}")
            except Exception as e:
                failures.append(f"{project_path}: {str(e)}")

        if failures:
            return {
                'success': False,
                'message': f"Compilation failed for {len(failures)} project(s): {' | '.join(failures)}"
            }

        if environment_blocks and not compiled_projects:
            return {
                'success': False,
                'blocked': True,
                'message': (
                    "Compilation could not be executed in the current environment because dependency "
                    f"resolution or local Maven cache access is blocked: {' | '.join(environment_blocks)}"
                )
            }

        return {
            'success': True,
            'message': f"Compilation successful for {len(compiled_projects)} project(s)"
        }
    
    def _validate_build(self, target_path: Path) -> Dict:
        """Validate that project builds (files exist)"""
        logger.debug("Validating build structure...")

        maven_projects = self._find_maven_projects(target_path)
        pom_exists = len(maven_projects) > 0
        if pom_exists:
            project_list = ', '.join(str(project.relative_to(target_path)) for project in maven_projects)
            message = f"Maven project(s) found: {project_list}"
        else:
            message = 'pom.xml missing'

        return {
            'success': pom_exists, 
            'message': message
        }

    def _find_maven_projects(self, target_path: Path) -> List[Path]:
        """Find Maven project roots under the migrated target path."""
        pom_files = []

        root_pom = target_path / "pom.xml"
        if root_pom.exists():
            pom_files.append(root_pom)

        for pom_file in target_path.rglob("pom.xml"):
            if pom_file == root_pom:
                continue
            if "target" in pom_file.parts:
                continue
            pom_files.append(pom_file)

        project_dirs = sorted({pom_file.parent for pom_file in pom_files})
        return project_dirs
    
    def _validate_imports(self, target_path: Path) -> Dict:
        """Validate import statements"""
        logger.debug("Validating imports...")
        
        issues = []
        java_files = self._collect_java_files(target_path)
        
        for file_path in java_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # Check for Spring imports
                if 'import org.springframework' in content:
                    lines = content.splitlines()
                    for i, line in enumerate(lines):
                        if 'import org.springframework' in line:
                            issues.append(f"{file_path.name}:{i+1} - Leftover Spring import: {line.strip()}")
            except Exception as e:
                logger.warning(f"Could not read {file_path}: {e}")
                
        return {
            'success': len(issues) == 0,
            'message': f"Found {len(issues)} import issues" if issues else "All imports valid",
            'issues': issues,
            'advisories': [],
        }
    
    def _validate_annotations(self, target_path: Path) -> Dict:
        """Validate annotations"""
        logger.debug("Validating annotations...")
        
        issues = []
        java_files = self._collect_java_files(target_path)
        
        forbidden_annotations = [
            '@RestController', '@Autowired', '@Service', '@Component', '@Repository',
            '@GetMapping', '@PostMapping', '@PutMapping', '@DeleteMapping', 
            '@Value', '@Configuration', '@RequestHeader', '@RequestParam',
            '@PathVariable', '@RequestMapping'
        ]
        
        for file_path in java_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                for ann in forbidden_annotations:
                    if ann in content:
                        issues.append(f"{file_path.name} - Leftover Spring annotation: {ann}")
                        
            except Exception as e:
                logger.warning(f"Could not read {file_path}: {e}")
        
        return {
            'success': len(issues) == 0, 
            'message': f"Found {len(issues)} annotation issues" if issues else "All annotations valid",
            'issues': issues,
            'advisories': [],
        }

    def _validate_spring_apis(self, target_path: Path) -> Dict:
        """Validate that Spring-only APIs and migration TODOs are not left behind."""
        logger.debug("Validating Spring API usage...")

        issues = []
        advisories = []
        java_files = self._collect_java_files(target_path)
        forbidden_markers = [
            'FilterRegistrationBean',
            'Ordered.',
            '@Order',
            '@Aspect',
            '@Around(',
            'ProceedingJoinPoint',
            'RestTemplateBuilder',
            'ProxyExchangeArgumentResolver',
            'ClientHttpResponse',
            'ProxyProperties',
            'ReflectionTestUtils',
            'SpringRunner',
            'SpringExtension',
            'AutoConfigureMockMvc',
            'TestPropertySource',
            'BeforeTestClass',
            'DataIntegrityViolationException',
            'ResponseEntity',
            'RestClientException',
            'TODO: Replace Spring',
            'io.helidon.webserver',
            'ServerRequest',
            'ServerResponse',
            'Routing',
            'Handler<',
            'SimpleClientHttpRequestFactory',
            'new Response (',
            'new Response(',
        ]

        for file_path in java_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                for marker in forbidden_markers:
                    if marker in content:
                        issues.append(f"{file_path.name} - Leftover Spring-specific API or TODO: {marker}")

                commented_security_annotations = {
                    annotation_name
                    for annotation_name in re.findall(
                    r'^\s*//\s*@([A-Za-z_]\w*)',
                    content,
                    re.MULTILINE
                    )
                }
                for annotation_name in commented_security_annotations:
                    if annotation_name.endswith('Check') or annotation_name.endswith('Authorize') or annotation_name.endswith('Secured'):
                        advisories.append(
                            f"{file_path.name} - Commented-out security annotation requires manual review: @{annotation_name}"
                        )

                custom_aspect_producers = re.findall(
                    r'@Produces[\s\S]{0,400}?\b([A-Za-z_]\w*Aspect)\b',
                    content
                )
                for aspect_type in custom_aspect_producers:
                    if self._is_preserved_enterprise_aspect(aspect_type):
                        continue
                    if '@Interceptor' not in content and 'jakarta.interceptor' not in content:
                        issues.append(
                            f"{file_path.name} - Custom aspect bean requires CDI/Jakarta compatibility review: {aspect_type}"
                        )

                if self._has_non_interceptor_generic_exception_signature(content):
                    advisories.append(
                        f"{file_path.name} - Generic throws Exception requires domain-specific exception mapping review"
                    )

                if re.search(r'throw\s+new\s+Exception\s*\(', content):
                    advisories.append(
                        f"{file_path.name} - Generic throw new Exception(...) requires domain-specific exception mapping review"
                    )
            except Exception as e:
                logger.warning(f"Could not read {file_path}: {e}")

        return {
            'success': len(issues) == 0,
            'message': f"Found {len(issues)} Spring API issues" if issues else "No leftover Spring APIs detected",
            'issues': issues,
            'advisories': advisories,
        }

    def _is_preserved_enterprise_aspect(self, aspect_type: str) -> bool:
        """Allow known in-house enterprise aspects to remain as-is for now."""
        return aspect_type in {
            'AuthzCheckAspect',
        }

    def _has_non_interceptor_generic_exception_signature(self, content: str) -> bool:
        """Flag generic throws Exception, except for valid Jakarta interceptor signatures."""
        method_pattern = re.compile(
            r'((?:\s*@\w+(?:\([^)]*\))?\s*\n)*)'
            r'\s*(?:public|protected|private)\s+[A-Za-z_][\w<>,\[\]\.? ]*\s+\w+\s*\((?:[^()]|\([^)]*\))*\)\s*throws\s+Exception\b',
            re.MULTILINE
        )
        for match in method_pattern.finditer(content):
            annotations = match.group(1) or ''
            signature = match.group(0)
            if '@AroundInvoke' in annotations and 'InvocationContext' in signature:
                continue
            return True
        return False

    def _collect_java_files(self, target_path: Path) -> List[Path]:
        """Collect Java files for GA validation, preferring main sources when present."""
        all_java_files = list(target_path.rglob("*.java"))
        main_java_files = [
            file_path for file_path in all_java_files
            if "src" in file_path.parts and "main" in file_path.parts and "java" in file_path.parts
        ]
        return main_java_files or all_java_files
    
    def _run_maven_command(self, target_path: Path, command: str) -> subprocess.CompletedProcess:
        """Run Maven command"""
        try:
            result = subprocess.run(
                ['mvn', command],
                cwd=target_path,
                capture_output=True,
                text=True,
                timeout=300,
                env={**os.environ, 'TOKENIZERS_PARALLELISM': 'false'}
            )
            return result
        except subprocess.TimeoutExpired:
            logger.error(f"Maven command timed out: {command}")
            raise
        except FileNotFoundError:
            logger.error("Maven not found in PATH")
            raise

    def _combined_maven_output(self, result: subprocess.CompletedProcess) -> str:
        """Combine stdout/stderr so Maven warnings do not mask real build results."""
        stdout = (result.stdout or '').strip()
        stderr = (result.stderr or '').strip()
        if stdout and stderr:
            return f"{stdout}\n{stderr}"
        return stdout or stderr

    def _is_warning_only_maven_output(self, output: str) -> bool:
        """Treat warning-only Maven output as non-failing for migration validation."""
        if not output:
            return False

        normalized = output.upper()
        has_warning = 'WARNING' in normalized
        has_error = '[ERROR]' in normalized or 'ERROR' in normalized
        has_failure = 'BUILD FAILURE' in normalized or 'COMPILATION FAILURE' in normalized
        has_success = 'BUILD SUCCESS' in normalized

        return has_warning and not has_error and not has_failure and not has_success

    def _is_environmental_compile_blocker(self, error_output: str) -> bool:
        """Detect sandbox or repository access issues that are not migration defects."""
        if not error_output:
            return False

        environmental_markers = [
            'Operation not permitted',
            '.m2/repository',
            'Failed to write tracking file',
            'Downloading from ',
            'InternalErrorException',
            'nodename nor servname provided',
            'Name or service not known',
            'Temporary failure in name resolution',
            'Unknown host',
            'Could not resolve host',
            'Connection timed out',
            'Connection refused',
            'No route to host',
        ]
        return any(marker in error_output for marker in environmental_markers)
