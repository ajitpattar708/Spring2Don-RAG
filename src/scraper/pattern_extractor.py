"""
Pattern Extractor
Extracts migration patterns from scraped data
"""

import re
from typing import List, Dict, Optional
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class PatternExtractor:
    """Extracts migration patterns from various sources"""
    
    def __init__(self):
        self.spring_annotations = [
            '@RestController', '@Controller', '@Service', '@Component',
            '@Repository', '@Autowired', '@Value', '@Bean', '@Configuration',
            '@GetMapping', '@PostMapping', '@PutMapping', '@DeleteMapping',
            '@PatchMapping', '@RequestMapping', '@PathVariable', '@RequestParam',
            '@RequestBody', '@ResponseBody'
        ]
        
        self.helidon_annotations = [
            '@Path', '@GET', '@POST', '@PUT', '@DELETE', '@PATCH',
            '@ApplicationScoped', '@RequestScoped', '@SessionScoped',
            '@Inject', '@ConfigProperty', '@Produces', '@Consumes',
            '@PathParam', '@QueryParam', '@HeaderParam'
        ]

    def clean_code(self, code: str) -> str:
        """
        Clean code for production quality:
        1. Remove comments (single line // and multi-line /* */)
        2. Remove non-ASCII characters (often appearing in foreign language comments/strings)
        3. Normalize whitespace
        """
        # Remove single line comments
        code = re.sub(r'//.*', '', code)
        
        # Remove multi-line comments
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
        
        # Remove non-ASCII characters (keep code clean)
        # This keeps standard Java characters but removes Chinese/other scripts
        code = re.sub(r'[^\x00-\x7F]+', '', code)
        
        # Normalize whitespace (limit newlines)
        code = re.sub(r'\n\s*\n', '\n', code)
        
        return code.strip()

    def extract_spring_patterns(self, code: str) -> List[Dict]:
        """Extract Spring Boot patterns from code"""
        # Clean quality first
        code = self.clean_code(code)
        
        patterns = []
        
        # Find classes with Spring annotations
        class_pattern = r'(@\w+.*?)\n.*?class\s+(\w+)\s*[^{]*\{([^}]*)\}'
        matches = re.finditer(class_pattern, code, re.MULTILINE | re.DOTALL)
        
        for match in matches:
            annotations = match.group(1)
            class_name = match.group(2)
            class_body = match.group(3)
            
            # Check if it's a Spring pattern
            if any(ann in annotations for ann in self.spring_annotations):
                patterns.append({
                    'type': 'class',
                    'class_name': class_name,
                    'annotations': annotations,
                    'code': match.group(0),
                    'framework': 'spring'
                })
        
        # Find method-level patterns
        method_pattern = r'(@\w+.*?)\n\s*(public|private|protected).*?(\w+)\s*\([^)]*\)'
        matches = re.finditer(method_pattern, code, re.MULTILINE)
        
        for match in matches:
            annotation = match.group(1)
            method_name = match.group(3)
            
            if any(ann in annotation for ann in self.spring_annotations):
                patterns.append({
                    'type': 'method',
                    'method_name': method_name,
                    'annotation': annotation,
                    'code': match.group(0),
                    'framework': 'spring'
                })
        
        return patterns
    
    def extract_helidon_patterns(self, code: str) -> List[Dict]:
        """Extract Helidon MP patterns from code"""
        patterns = []
        
        # Similar to Spring but for Helidon
        class_pattern = r'(@\w+.*?)\n.*?class\s+(\w+)\s*[^{]*\{([^}]*)\}'
        matches = re.finditer(class_pattern, code, re.MULTILINE | re.DOTALL)
        
        for match in matches:
            annotations = match.group(1)
            class_name = match.group(2)
            
            if any(ann in annotations for ann in self.helidon_annotations):
                patterns.append({
                    'type': 'class',
                    'class_name': class_name,
                    'annotations': annotations,
                    'code': match.group(0),
                    'framework': 'helidon'
                })
        
        return patterns
    
    def create_migration_pair(
        self,
        spring_code: str,
        helidon_code: str,
        source: str = "scraped"
    ) -> Optional[Dict]:
        """Create a migration pattern pair"""
        try:
            # Extract Spring patterns
            spring_patterns = self.extract_spring_patterns(spring_code)
            helidon_patterns = self.extract_helidon_patterns(helidon_code)
            
            if spring_patterns and helidon_patterns:
                spring_pattern = spring_patterns[0]
                helidon_pattern = helidon_patterns[0]
                
                return {
                    "id": f"scraped-{hash(spring_code) % 1000000}",
                    "migration_type": "code_pattern",
                    "spring_pattern": spring_pattern.get('annotations', ''),
                    "helidon_pattern": helidon_pattern.get('annotations', ''),
                    "spring_code": spring_code[:500],  # Limit size
                    "helidon_code": helidon_code[:500],
                    "source_framework": "Spring Boot",
                    "target_framework": "Helidon MP",
                    "spring_version": "3.4.5",
                    "helidon_version": "4.0.0",
                    "description": f"Migration pattern from {source}",
                    "explanation": f"Extracted from {source}",
                    "complexity": "medium",
                    "source": source
                }
        
        except Exception as e:
            logger.error(f"Error creating migration pair: {str(e)}")
        
        return None
    
    def extract_dependency_patterns(self, pom_content: str) -> List[Dict]:
        """Extract dependency patterns from POM files"""
        patterns = []
        
        # Find Spring Boot dependencies
        spring_dep_pattern = r'<dependency>.*?<groupId>(.*?)</groupId>.*?<artifactId>(spring-boot.*?)</artifactId>.*?</dependency>'
        matches = re.finditer(spring_dep_pattern, pom_content, re.DOTALL)
        
        for match in matches:
            group_id = match.group(1)
            artifact_id = match.group(2)
            
            patterns.append({
                'type': 'dependency',
                'group_id': group_id,
                'artifact_id': artifact_id,
                'framework': 'spring'
            })
        
        return patterns


