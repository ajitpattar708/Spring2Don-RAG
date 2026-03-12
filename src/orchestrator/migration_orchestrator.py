"""
Migration Orchestrator
Coordinates all agents and manages the migration workflow
"""

from pathlib import Path
from typing import Optional
from dataclasses import dataclass
import shutil
import sys
import time
import os
import json
from src.config.settings import Settings
from src.utils.logger import color_text, setup_logger
from src.utils.version_compatibility import VersionCompatibility
from src.agents.dependency_agent import DependencyAgent
from src.agents.code_transform_agent import CodeTransformAgent
from src.agents.config_agent import ConfigAgent
from src.agents.validation_agent import ValidationAgent

logger = setup_logger(__name__)


@dataclass
class MigrationResult:
    """Result of migration operation"""
    success: bool
    files_migrated: int = 0
    transformations_applied: int = 0
    error_message: Optional[str] = None
    warnings: list = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class MigrationOrchestrator:
    """Orchestrates the migration process"""
    
    def __init__(
        self,
        source_path: str,
        target_path: str,
        spring_version: str,
        helidon_version: str,
        settings: Settings
    ):
        self.source_path = Path(source_path)
        self.target_path = Path(target_path)
        self.spring_version = spring_version
        self.helidon_version = helidon_version
        self.settings = settings
        self.settings.validate()
        
        # Set versions in settings for agents to use
        settings.spring_version = spring_version
        settings.helidon_version = helidon_version
        
        # Validate version compatibility
        is_compatible, error_msg = VersionCompatibility.validate_compatibility(
            spring_version, helidon_version
        )
        if not is_compatible:
            logger.warning(f"Version compatibility warning: {error_msg}")
        
        # Log version information
        version_info = VersionCompatibility.get_version_info(helidon_version)
        logger.info(f"Helidon {helidon_version} requires:")
        logger.info(f"  - JDK: {version_info['required_jdk']}+")
        logger.info(f"  - Maven: {version_info['required_maven']}+")
        logger.info(f"  - Jakarta EE: {version_info['jakarta_ee_version']}")
        logger.info(f"  - MicroProfile: {version_info['microprofile_version']}")
        
        # Initialize agents
        self.dependency_agent = DependencyAgent(settings)
        self.code_transform_agent = CodeTransformAgent(settings)
        self.config_agent = ConfigAgent(settings)
        self.validation_agent = ValidationAgent(settings)
        
    def migrate(self) -> MigrationResult:
        """Execute the migration process"""
        start_time = time.time()
        try:
            print("\n" + color_text("="*70, "title"))
            print(color_text("SPRING BOOT TO HELIDON MP MIGRATION", "title"))
            print(color_text("="*70, "title"))
            logger.info("Starting migration orchestration...")
            
            # Validate source path
            if not self.source_path.exists():
                error_msg = f"ERROR: Source path does not exist: {self.source_path}"
                print(color_text(error_msg, "error"))
                return MigrationResult(
                    success=False,
                    error_message=error_msg
                )
            
            # Validate knowledge base is initialized
            try:
                knowledge_base = self.dependency_agent.knowledge_base
                kb_available = getattr(knowledge_base, 'available', True)
                stats = knowledge_base.get_collection_stats('annotations')
                if kb_available and stats['count'] == 0:
                    warning_msg = "Knowledge base appears empty. Run 'python migration_agent_main.py init' first."
                    if self.settings.require_kb and not self.settings.offline_mode:
                        raise RuntimeError(warning_msg)
                    print(f"WARNING: {warning_msg}")
                    logger.warning(warning_msg)
                elif not kb_available:
                    warning_msg = "Knowledge base is unavailable; continuing with deterministic migration mode."
                    print(color_text(f"WARNING: {warning_msg}", "warn"))
                    logger.warning(warning_msg)
            except Exception as e:
                warning_msg = f"Could not verify knowledge base: {str(e)}"
                if self.settings.require_kb and not self.settings.offline_mode:
                    raise RuntimeError(warning_msg)
                print(color_text(f"WARNING: {warning_msg}", "warn"))
                logger.warning(warning_msg)
            
            # ALWAYS clean target directory before migration (even if it doesn't exist, ensure it's clean)
            print("\n" + color_text("[Phase 0] Cleaning target directory...", "phase"))
            sys.stdout.flush()
            clean_start = time.time()
            if self.target_path.exists():
                self._clean_target_directory()
            else:
                logger.info(f"Target directory does not exist, will create new: {self.target_path}")
            clean_time = time.time() - clean_start
            
            # Verify directory is gone/clean
            if self.target_path.exists():
                logger.warning(f"WARNING: Target directory still exists after cleanup: {self.target_path}")
                print(color_text("   [WARNING] Directory still exists, attempting final cleanup...", "warn"))
                sys.stdout.flush()
                self._clean_target_directory()
            
            print(color_text(f"   [OK] Cleaned in {clean_time:.2f}s", "ok"))
            
            # Copy project structure to target (copytree will create the directory)
            print("\n" + color_text("[Phase 0] Copying project structure...", "phase"))
            sys.stdout.flush()
            copy_start = time.time()
            self._copy_project_structure()
            copy_time = time.time() - copy_start
            print(color_text(f"   [OK] Completed in {copy_time:.2f}s", "ok"))
            
            # Phase 1: Analyze project structure
            print("\n" + color_text("[Phase 1] Analyzing project structure...", "phase"))
            sys.stdout.flush()
            analyze_start = time.time()
            project_structure = self._analyze_project_structure(self.target_path)
            analyze_time = time.time() - analyze_start
            print(color_text(f"   [OK] Completed in {analyze_time:.2f}s", "ok"))
            
            # Phase 2: Migrate dependencies
            print("\n" + color_text("[Phase 2] Migrating dependencies...", "phase"))
            sys.stdout.flush()
            dep_start = time.time()
            dependency_result = self.dependency_agent.migrate(project_structure)
            dep_time = time.time() - dep_start
            if not dependency_result.get('success'):
                error_msg = f"   WARNING: Dependency migration had issues: {dependency_result.get('error')}"
                print(color_text(error_msg, "warn"))
                logger.warning(error_msg)
            else:
                deps_migrated = dependency_result.get('dependencies_migrated', 0)
                print(color_text(f"   [OK] Migrated {deps_migrated} dependencies in {dep_time:.2f}s", "ok"))
            
            # Phase 3: Migrate configuration files
            print("\n" + color_text("[Phase 3] Migrating configuration files...", "phase"))
            sys.stdout.flush()
            config_start = time.time()
            config_result = self.config_agent.migrate(
                project_structure,
                source_path=self.target_path,
                target_path=self.target_path
            )
            config_time = time.time() - config_start
            if not config_result.get('success'):
                error_msg = f"   WARNING: Config migration had issues: {config_result.get('error')}"
                print(color_text(error_msg, "warn"))
                logger.warning(error_msg)
            else:
                configs_migrated = config_result.get('files_migrated', 0)
                print(color_text(f"   [OK] Migrated {configs_migrated} config files in {config_time:.2f}s", "ok"))
            
            # Phase 4: Migrate source code
            print("\n" + color_text("[Phase 4] Migrating source code...", "phase"))
            sys.stdout.flush()
            code_start = time.time()
            code_result = self.code_transform_agent.migrate(
                project_structure,
                source_path=self.target_path,
                target_path=self.target_path
            )
            code_time = time.time() - code_start
            if not code_result.get('success'):
                error_msg = f"   WARNING: Code migration had issues: {code_result.get('error')}"
                print(color_text(error_msg, "warn"))
                logger.warning(error_msg)
            else:
                files_migrated = code_result.get('files_migrated', 0)
                transformations = code_result.get('transformations_applied', 0)
                print(color_text(f"   [OK] Migrated {files_migrated} Java files with {transformations} transformations in {code_time:.2f}s", "ok"))
            
            # Phase 5: Validate migration
            print("\n" + color_text("[Phase 5] Validating migration...", "phase"))
            sys.stdout.flush()
            validation_start = time.time()
            validation_result = self.validation_agent.validate(self.target_path)
            validation_time = time.time() - validation_start
            if not validation_result.get('success'):
                warning_msg = "   WARNING: Validation found issues; migration will be marked failed"
                print(color_text(warning_msg, "warn"))
                logger.warning(warning_msg)
            else:
                print(color_text(f"   [OK] Validation completed in {validation_time:.2f}s", "ok"))
            
            files_migrated = code_result.get('files_migrated', 0)
            transformations_applied = code_result.get('transformations_applied', 0)
            total_time = time.time() - start_time

            # Generate migration report
            report = self._build_migration_report(
                files_migrated=files_migrated,
                transformations_applied=transformations_applied,
                total_time=total_time,
                dependency_result=dependency_result,
                config_result=config_result,
                code_result=code_result,
                validation_result=validation_result
            )
            self._write_migration_report(report)

            if not validation_result.get('success'):
                error_message = self._build_validation_error_message(validation_result)
                print("\n" + color_text("="*70, "error"))
                print(color_text("MIGRATION FAILED VALIDATION", "error"))
                print(color_text("="*70, "error"))
                print(color_text("Summary:", "info"))
                print(color_text(f"   • Files migrated: {files_migrated}", "info"))
                print(color_text(f"   • Transformations applied: {transformations_applied}", "info"))
                print(color_text(f"   • Total time: {total_time:.2f}s ({total_time/60:.1f} minutes)", "info"))
                print(color_text(f"   • Output directory: {self.target_path}", "info"))
                print(color_text(f"   • Validation error: {error_message}", "error"))
                print(color_text("="*70 + "\n", "error"))
                logger.error(error_message)
                return MigrationResult(
                    success=False,
                    files_migrated=files_migrated,
                    transformations_applied=transformations_applied,
                    error_message=error_message,
                    warnings=[error_message]
                )
            
            print("\n" + color_text("="*70, "ok"))
            print(color_text("MIGRATION COMPLETED SUCCESSFULLY!", "ok"))
            print(color_text("="*70, "ok"))
            print(color_text("Summary:", "info"))
            print(color_text(f"   • Files migrated: {files_migrated}", "info"))
            print(color_text(f"   • Transformations applied: {transformations_applied}", "info"))
            print(color_text(f"   • Total time: {total_time:.2f}s ({total_time/60:.1f} minutes)", "info"))
            print(color_text(f"   • Output directory: {self.target_path}", "info"))
            print(color_text("="*70 + "\n", "ok"))
            
            logger.info("Migration completed successfully!")
            return MigrationResult(
                success=True,
                files_migrated=files_migrated,
                transformations_applied=transformations_applied
            )
            
        except Exception as e:
            total_time = time.time() - start_time
            error_msg = f"MIGRATION FAILED after {total_time:.2f}s: {str(e)}"
            print("\n" + color_text(error_msg, "error"))
            print(color_text(f"   Error type: {type(e).__name__}", "error"))
            logger.error(f"Migration failed: {str(e)}", exc_info=True)
            return MigrationResult(
                success=False,
                error_message=str(e)
            )

    def _build_validation_error_message(self, validation_result: dict) -> str:
        """Summarize validation failure for the migration result."""
        results = validation_result.get('results') or {}
        compilation_result = results.get('compilation') or {}
        if not compilation_result.get('success'):
            compilation_message = compilation_result.get('message')
            if compilation_message:
                return compilation_message

        manual_review = validation_result.get('manual_review') or {}
        issues = manual_review.get('blocking_issues') or []
        issue_count = len(issues)

        if issue_count and issues:
            return f"Validation failed with {issue_count} issue(s). First issue: {issues[0]}"

        failed_checks = [
            name for name, result in results.items()
            if not result.get('success')
        ]
        if failed_checks:
            return f"Validation failed in checks: {', '.join(failed_checks)}"

        return "Validation failed with unknown issues."

    def _build_migration_report(
        self,
        files_migrated: int,
        transformations_applied: int,
        total_time: float,
        dependency_result: dict,
        config_result: dict,
        code_result: dict,
        validation_result: dict
    ) -> dict:
        """Build a GA-ready migration report"""
        ga_readiness = self._build_ga_readiness(validation_result)
        return {
            'summary': {
                'source_path': str(self.source_path),
                'target_path': str(self.target_path),
                'spring_version': self.spring_version,
                'helidon_version': self.helidon_version,
                'files_migrated': files_migrated,
                'transformations_applied': transformations_applied,
                'total_time_seconds': round(total_time, 2)
            },
            'dependency_migration': dependency_result,
            'config_migration': config_result,
            'code_migration': {
                'files_migrated': code_result.get('files_migrated'),
                'transformations_applied': code_result.get('transformations_applied'),
                'fallback_stats': code_result.get('fallback_stats', {})
            },
            'validation': validation_result,
            'ga_readiness': ga_readiness,
        }

    def _build_ga_readiness(self, validation_result: dict) -> dict:
        """Summarize whether the migrated service is actually ready for GA rollout."""
        results = validation_result.get('results') or {}
        manual_review = validation_result.get('manual_review') or {}
        manual_issues = manual_review.get('issues') or []
        blocking_manual_issues = manual_review.get('blocking_issues')
        if blocking_manual_issues is None:
            blocking_manual_issues = manual_issues
        advisory_manual_issues = manual_review.get('advisories') or []
        compilation = results.get('compilation') or {}

        compile_blocked = bool(compilation.get('blocked'))
        compile_success = bool(compilation.get('success'))
        compile_status = 'verified' if compile_success else 'blocked' if compile_blocked else 'failed'
        preserved_enterprise_patterns = [
            'AuthzCheck/AuthzCheckAspect preserved as-is',
            'OCI SDK usage preserved as-is',
            'OCI Vault access preserved as-is',
            'In-house request/response filters preserved as-is',
        ]

        enterprise_blockers = [
            issue for issue in blocking_manual_issues
            if any(marker in issue for marker in [
                'Custom aspect bean requires CDI/Jakarta compatibility review',
                'Commented-out security annotation requires manual review',
                'Generic throws Exception requires domain-specific exception mapping review',
                'Generic throw new Exception(...) requires domain-specific exception mapping review',
                'Leftover Spring import',
                'Leftover Spring annotation',
                'Leftover Spring-specific API',
            ])
        ]

        if validation_result.get('success') and not enterprise_blockers and compile_success:
            status = 'ready'
            ready_for_ga = True
        elif compile_blocked and not enterprise_blockers:
            status = 'verification_blocked'
            ready_for_ga = False
        else:
            status = 'blocked'
            ready_for_ga = False

        next_actions = []
        if compile_blocked:
            next_actions.append('Run Maven compile in an environment with writable Maven cache and repository access.')
        if enterprise_blockers:
            next_actions.append('Resolve enterprise migration blockers such as custom security/aspect integration and generic exception contracts.')
        if advisory_manual_issues or not enterprise_blockers:
            next_actions.append('Manually review preserved enterprise integrations before GA sign-off.')
        if not validation_result.get('success') and not enterprise_blockers and not compile_blocked:
            next_actions.append('Review validation failures and rerun migration verification.')

        return {
            'ready_for_ga': ready_for_ga,
            'status': status,
            'compile_status': compile_status,
            'enterprise_blockers_count': len(enterprise_blockers),
            'enterprise_blockers': enterprise_blockers,
            'preserved_enterprise_patterns': preserved_enterprise_patterns,
            'manual_review_issues_count': manual_review.get('issues_count', len(manual_issues)),
            'manual_review_advisories': advisory_manual_issues,
            'next_actions': next_actions,
        }

    def _write_migration_report(self, report: dict) -> None:
        """Write migration report to configured path"""
        try:
            report_path = Path(self.settings.migration_report_path)
            if not report_path.is_absolute():
                report_path = self.target_path / report_path
            report_path.parent.mkdir(parents=True, exist_ok=True)
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)
            logger.info(f"Migration report written to {report_path}")
        except Exception as e:
            logger.warning(f"Failed to write migration report: {str(e)}")
    
    def _clean_target_directory(self):
        """Clean the target directory before migration"""
        import time
        import os
        try:
            if self.target_path.exists():
                logger.info(f"Cleaning target directory: {self.target_path}")
                
                # On Windows, sometimes we need to retry due to file locks
                max_retries = 5
                for attempt in range(max_retries):
                    try:
                        # Remove read-only files first (Windows issue)
                        if os.name == 'nt':  # Windows
                            for root, dirs, files in os.walk(self.target_path):
                                for file in files:
                                    file_path = os.path.join(root, file)
                                    try:
                                        os.chmod(file_path, 0o777)  # Make writable
                                    except:
                                        pass
                        
                        # Remove the entire directory tree
                        shutil.rmtree(self.target_path, ignore_errors=False)
                        
                        # Wait a bit for Windows to release handles
                        time.sleep(0.2)
                        
                        # Verify it's actually gone
                        if not self.target_path.exists():
                            logger.info("Target directory cleaned successfully")
                            return
                        else:
                            # Still exists, try again
                            logger.warning(f"Directory still exists after removal attempt {attempt + 1}")
                            time.sleep(0.5)
                            
                    except (PermissionError, OSError, FileNotFoundError) as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"Retry {attempt + 1}/{max_retries} cleaning directory: {str(e)}")
                            time.sleep(0.5)
                        else:
                            logger.error(f"Failed to clean directory after {max_retries} attempts: {str(e)}")
                            raise
                
                # Final check - if still exists, force remove
                if self.target_path.exists():
                    logger.warning("Directory still exists after all retries, attempting force removal...")
                    try:
                        # Try to remove individual files first
                        for root, dirs, files in os.walk(self.target_path, topdown=False):
                            for file in files:
                                try:
                                    os.remove(os.path.join(root, file))
                                except:
                                    pass
                            for dir in dirs:
                                try:
                                    os.rmdir(os.path.join(root, dir))
                                except:
                                    pass
                        # Finally remove the root
                        os.rmdir(self.target_path)
                    except Exception as e:
                        logger.error(f"Force removal failed: {str(e)}")
                        raise
                        
        except Exception as e:
            logger.error(f"Failed to clean target directory: {str(e)}")
            raise
    
    def _copy_project_structure(self):
        """Copy project files to target directory"""
        try:
            # Ensure target directory doesn't exist (should be cleaned already, but double-check)
            if self.target_path.exists():
                logger.warning(f"Target directory still exists, attempting cleanup again...")
                self._clean_target_directory()
            
            # Copy all files except build artifacts
            ignore_patterns = shutil.ignore_patterns(
                'target', 'build', '.gradle', '.idea', '.vscode',
                '__pycache__', '*.pyc', '.git'
            )
            
            shutil.copytree(
                self.source_path,
                self.target_path,
                ignore=ignore_patterns,
                dirs_exist_ok=False  # Directory should not exist after cleanup
            )
            logger.info("Project structure copied successfully")
        except Exception as e:
            logger.error(f"Failed to copy project structure: {str(e)}")
            raise
    
    def _analyze_project_structure(self, base_path: Path) -> dict:
        """Analyze the project structure"""
        structure = {
            'build_tool': None,  # 'maven' or 'gradle'
            'java_files': [],
            'config_files': [],
            'pom_file': None,
            'build_gradle': None
        }
        
        # Detect build tool (direct root or nested modules)
        pom_file = base_path / 'pom.xml'
        build_gradle = base_path / 'build.gradle'
        
        if pom_file.exists():
            structure['build_tool'] = 'maven'
            structure['pom_file'] = pom_file
        elif build_gradle.exists():
            structure['build_tool'] = 'gradle'
            structure['build_gradle'] = build_gradle
        else:
            # Try to find nested module roots (any subfolder with pom.xml/build.gradle)
            nested_poms = list(base_path.rglob('pom.xml'))
            nested_gradles = list(base_path.rglob('build.gradle'))
            if nested_poms:
                structure['build_tool'] = 'maven'
                structure['pom_file'] = nested_poms[0]
            elif nested_gradles:
                structure['build_tool'] = 'gradle'
                structure['build_gradle'] = nested_gradles[0]
        
        # Find Java source files (direct root or nested modules)
        java_src_dir = base_path / 'src' / 'main' / 'java'
        if java_src_dir.exists():
            structure['java_files'] = list(java_src_dir.rglob('*.java'))
        else:
            structure['java_files'] = list(base_path.rglob('src/main/java/**/*.java'))
        
        # Find configuration files (search recursively to handle nested projects)
        for config_file in base_path.rglob('application.*'):
            structure['config_files'].append(config_file)
        
        logger.info(f"Detected build tool: {structure['build_tool']}")
        logger.info(f"Found {len(structure['java_files'])} Java files")
        logger.info(f"Found {len(structure['config_files'])} configuration files")
        
        return structure
