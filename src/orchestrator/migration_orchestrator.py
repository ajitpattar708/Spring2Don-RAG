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
from src.config.settings import Settings
from src.utils.logger import setup_logger
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
            print("\n" + "="*70)
            print("SPRING BOOT TO HELIDON MP MIGRATION")
            print("="*70)
            logger.info("Starting migration orchestration...")
            
            # Validate source path
            if not self.source_path.exists():
                error_msg = f"ERROR: Source path does not exist: {self.source_path}"
                print(error_msg)
                return MigrationResult(
                    success=False,
                    error_message=error_msg
                )
            
            # Validate knowledge base is initialized
            try:
                stats = self.dependency_agent.knowledge_base.get_collection_stats('annotations')
                if stats['count'] == 0:
                    warning_msg = "WARNING: Knowledge base appears empty. Run 'python migration_agent_main.py init' first."
                    print(warning_msg)
                    logger.warning(warning_msg)
            except Exception as e:
                warning_msg = f"WARNING: Could not verify knowledge base: {str(e)}"
                print(warning_msg)
                logger.warning(warning_msg)
            
            # ALWAYS clean target directory before migration (even if it doesn't exist, ensure it's clean)
            print("\n[Phase 0] Cleaning target directory...")
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
                print(f"   [WARNING] Directory still exists, attempting final cleanup...")
                sys.stdout.flush()
                self._clean_target_directory()
            
            print(f"   [OK] Cleaned in {clean_time:.2f}s")
            
            # Copy project structure to target (copytree will create the directory)
            print("\n[Phase 0] Copying project structure...")
            sys.stdout.flush()
            copy_start = time.time()
            self._copy_project_structure()
            copy_time = time.time() - copy_start
            print(f"   [OK] Completed in {copy_time:.2f}s")
            
            # Phase 1: Analyze project structure
            print("\n[Phase 1] Analyzing project structure...")
            sys.stdout.flush()
            analyze_start = time.time()
            project_structure = self._analyze_project_structure(self.target_path)
            analyze_time = time.time() - analyze_start
            print(f"   [OK] Completed in {analyze_time:.2f}s")
            
            # Phase 2: Migrate dependencies
            print("\n[Phase 2] Migrating dependencies...")
            sys.stdout.flush()
            dep_start = time.time()
            dependency_result = self.dependency_agent.migrate(project_structure)
            dep_time = time.time() - dep_start
            if not dependency_result.get('success'):
                error_msg = f"   WARNING: Dependency migration had issues: {dependency_result.get('error')}"
                print(error_msg)
                logger.warning(error_msg)
            else:
                deps_migrated = dependency_result.get('dependencies_migrated', 0)
                print(f"   [OK] Migrated {deps_migrated} dependencies in {dep_time:.2f}s")
            
            # Phase 3: Migrate configuration files
            print("\n[Phase 3] Migrating configuration files...")
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
                print(error_msg)
                logger.warning(error_msg)
            else:
                configs_migrated = config_result.get('files_migrated', 0)
                print(f"   [OK] Migrated {configs_migrated} config files in {config_time:.2f}s")
            
            # Phase 4: Migrate source code
            print("\n[Phase 4] Migrating source code...")
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
                print(error_msg)
                logger.warning(error_msg)
            else:
                files_migrated = code_result.get('files_migrated', 0)
                transformations = code_result.get('transformations_applied', 0)
                print(f"   [OK] Migrated {files_migrated} Java files with {transformations} transformations in {code_time:.2f}s")
            
            # Phase 5: Validate migration
            print("\n[Phase 5] Validating migration...")
            sys.stdout.flush()
            validation_start = time.time()
            validation_result = self.validation_agent.validate(self.target_path)
            validation_time = time.time() - validation_start
            if not validation_result.get('success'):
                warning_msg = "   WARNING: Validation found issues, but migration completed"
                print(warning_msg)
                logger.warning(warning_msg)
            else:
                print(f"   [OK] Validation completed in {validation_time:.2f}s")
            
            files_migrated = code_result.get('files_migrated', 0)
            transformations_applied = code_result.get('transformations_applied', 0)
            total_time = time.time() - start_time
            
            print("\n" + "="*70)
            print("MIGRATION COMPLETED SUCCESSFULLY!")
            print("="*70)
            print(f"Summary:")
            print(f"   • Files migrated: {files_migrated}")
            print(f"   • Transformations applied: {transformations_applied}")
            print(f"   • Total time: {total_time:.2f}s ({total_time/60:.1f} minutes)")
            print(f"   • Output directory: {self.target_path}")
            print("="*70 + "\n")
            
            logger.info("Migration completed successfully!")
            return MigrationResult(
                success=True,
                files_migrated=files_migrated,
                transformations_applied=transformations_applied
            )
            
        except Exception as e:
            total_time = time.time() - start_time
            error_msg = f"MIGRATION FAILED after {total_time:.2f}s: {str(e)}"
            print(f"\n{error_msg}")
            print(f"   Error type: {type(e).__name__}")
            logger.error(f"Migration failed: {str(e)}", exc_info=True)
            return MigrationResult(
                success=False,
                error_message=str(e)
            )
    
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
        
        # Detect build tool
        pom_file = base_path / 'pom.xml'
        build_gradle = base_path / 'build.gradle'
        
        if pom_file.exists():
            structure['build_tool'] = 'maven'
            structure['pom_file'] = pom_file
        elif build_gradle.exists():
            structure['build_tool'] = 'gradle'
            structure['build_gradle'] = build_gradle
        
        # Find Java source files
        java_src_dir = base_path / 'src' / 'main' / 'java'
        if java_src_dir.exists():
            structure['java_files'] = list(java_src_dir.rglob('*.java'))
        
        # Find configuration files
        config_dir = base_path / 'src' / 'main' / 'resources'
        if config_dir.exists():
            for config_file in config_dir.rglob('application.*'):
                structure['config_files'].append(config_file)
        
        logger.info(f"Detected build tool: {structure['build_tool']}")
        logger.info(f"Found {len(structure['java_files'])} Java files")
        logger.info(f"Found {len(structure['config_files'])} configuration files")
        
        return structure

