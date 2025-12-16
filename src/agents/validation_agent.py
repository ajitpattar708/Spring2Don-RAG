"""
Validation Agent
Validates migrated code and configuration
"""

from pathlib import Path
from typing import Dict
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
            'annotations': self._validate_annotations(target_path)
        }
        
        all_passed = all(result['success'] for result in validation_results.values())
        
        return {
            'success': all_passed,
            'results': validation_results
        }
    
    def _validate_compilation(self, target_path: Path) -> Dict:
        """Validate that code compiles"""
        logger.debug("Validating compilation...")
        
        if (target_path / 'pom.xml').exists():
            logger.info("Detected Maven project. Running 'mvn compile'...")
            try:
                result = self._run_maven_command(target_path, 'compile')
                if result.returncode == 0:
                    return {'success': True, 'message': 'Compilation successful'}
                else:
                    return {'success': False, 'message': f'Compilation failed: {result.stderr}'}
            except Exception as e:
                return {'success': False, 'message': f'Compilation check failed: {str(e)}'}
        
        return {'success': True, 'message': 'Skipped (not a Maven project)'}
    
    def _validate_build(self, target_path: Path) -> Dict:
        """Validate that project builds (files exist)"""
        logger.debug("Validating build structure...")
        
        pom_exists = (target_path / "pom.xml").exists()
        return {
            'success': pom_exists, 
            'message': 'pom.xml found' if pom_exists else 'pom.xml missing'
        }
    
    def _validate_imports(self, target_path: Path) -> Dict:
        """Validate import statements"""
        logger.debug("Validating imports...")
        
        issues = []
        java_files = list(target_path.rglob("*.java"))
        
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
            'issues': issues
        }
    
    def _validate_annotations(self, target_path: Path) -> Dict:
        """Validate annotations"""
        logger.debug("Validating annotations...")
        
        issues = []
        java_files = list(target_path.rglob("*.java"))
        
        forbidden_annotations = [
            '@RestController', '@Autowired', '@Service', '@Component', '@Repository',
            '@GetMapping', '@PostMapping', '@PutMapping', '@DeleteMapping', 
            '@Value', '@Configuration'
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
            'issues': issues
        }
    
    def _run_maven_command(self, target_path: Path, command: str) -> subprocess.CompletedProcess:
        """Run Maven command"""
        try:
            result = subprocess.run(
                ['mvn', command],
                cwd=target_path,
                capture_output=True,
                text=True,
                timeout=300
            )
            return result
        except subprocess.TimeoutExpired:
            logger.error(f"Maven command timed out: {command}")
            raise
        except FileNotFoundError:
            logger.error("Maven not found in PATH")
            raise

