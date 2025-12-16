"""
Dataset Generator
Creates and manages migration pattern datasets
"""

import json
from pathlib import Path
from typing import List, Dict
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class DatasetGenerator:
    """Generates migration pattern datasets"""
    
    def __init__(self):
        self.patterns = []
    
    def add_pattern(self, pattern: Dict):
        """Add a migration pattern"""
        self.patterns.append(pattern)
    
    def generate_annotation_patterns(self) -> List[Dict]:
        """Generate annotation migration patterns"""
        patterns = []
        
        # REST Controller patterns
        patterns.append({
            "id": "spring-helidon-001",
            "migration_type": "annotation",
            "spring_pattern": "@RestController",
            "helidon_pattern": "@Path + @ApplicationScoped",
            "spring_code": """@RestController
@RequestMapping("/api/users")
public class UserController {
    @GetMapping("/{id}")
    public ResponseEntity<User> getUser(@PathVariable Long id) {
        return ResponseEntity.ok(userService.findById(id));
    }
}""",
            "helidon_code": """@Path("/api/users")
@ApplicationScoped
public class UserController {
    @GET
    @Path("/{id}")
    @Produces(MediaType.APPLICATION_JSON)
    public User getUser(@PathParam("id") Long id) {
        return userService.findById(id);
    }
}""",
            "source_framework": "Spring Boot",
            "target_framework": "Helidon MP",
            "spring_version": "3.4.5",
            "helidon_version": "4.0.0",
            "description": "REST controller annotation migration",
            "explanation": "Spring @RestController maps to JAX-RS @Path with CDI @ApplicationScoped",
            "complexity": "low",
            "category": "rest_controller",
            "metadata": {
                "requires_imports": ["jakarta.ws.rs.Path", "jakarta.enterprise.context.ApplicationScoped", "jakarta.ws.rs.GET", "jakarta.ws.rs.Produces", "jakarta.ws.rs.PathParam"],
                "breaking_changes": [],
                "notes": "Must add @Produces/@Consumes for content types"
            }
        })
        
        # GetMapping pattern
        patterns.append({
            "id": "spring-helidon-002",
            "migration_type": "annotation",
            "spring_pattern": "@GetMapping",
            "helidon_pattern": "@GET + @Path",
            "spring_code": """@GetMapping("/users")
public List<User> getUsers() {
    return userService.findAll();
}""",
            "helidon_code": """@GET
@Path("/users")
@Produces(MediaType.APPLICATION_JSON)
public List<User> getUsers() {
    return userService.findAll();
}""",
            "source_framework": "Spring Boot",
            "target_framework": "Helidon MP",
            "spring_version": "3.4.5",
            "helidon_version": "4.0.0",
            "description": "GET mapping annotation migration",
            "explanation": "Spring @GetMapping maps to JAX-RS @GET with @Path",
            "complexity": "low",
            "category": "rest_mapping"
        })
        
        # PostMapping pattern
        patterns.append({
            "id": "spring-helidon-003",
            "migration_type": "annotation",
            "spring_pattern": "@PostMapping",
            "helidon_pattern": "@POST + @Path",
            "spring_code": """@PostMapping("/users")
public ResponseEntity<User> createUser(@RequestBody User user) {
    User created = userService.save(user);
    return ResponseEntity.status(HttpStatus.CREATED).body(created);
}""",
            "helidon_code": """@POST
@Path("/users")
@Consumes(MediaType.APPLICATION_JSON)
@Produces(MediaType.APPLICATION_JSON)
public Response createUser(User user) {
    User created = userService.save(user);
    return Response.status(Response.Status.CREATED).entity(created).build();
}""",
            "source_framework": "Spring Boot",
            "target_framework": "Helidon MP",
            "spring_version": "3.4.5",
            "helidon_version": "4.0.0",
            "description": "POST mapping annotation migration",
            "explanation": "Spring @PostMapping maps to JAX-RS @POST with @Path and @Consumes",
            "complexity": "medium",
            "category": "rest_mapping"
        })
        
        # Autowired pattern
        patterns.append({
            "id": "spring-helidon-004",
            "migration_type": "annotation",
            "spring_pattern": "@Autowired",
            "helidon_pattern": "@Inject",
            "spring_code": """@Autowired
private UserService userService;""",
            "helidon_code": """@Inject
private UserService userService;""",
            "source_framework": "Spring Boot",
            "target_framework": "Helidon MP",
            "spring_version": "3.4.5",
            "helidon_version": "4.0.0",
            "description": "Dependency injection annotation migration",
            "explanation": "Spring @Autowired maps to CDI @Inject",
            "complexity": "low",
            "category": "dependency_injection"
        })
        
        # Service pattern
        patterns.append({
            "id": "spring-helidon-005",
            "migration_type": "annotation",
            "spring_pattern": "@Service",
            "helidon_pattern": "@ApplicationScoped",
            "spring_code": """@Service
public class UserService {
    @Autowired
    private UserRepository userRepository;
}""",
            "helidon_code": """@ApplicationScoped
public class UserService {
    @Inject
    private UserRepository userRepository;
}""",
            "source_framework": "Spring Boot",
            "target_framework": "Helidon MP",
            "spring_version": "3.4.5",
            "helidon_version": "4.0.0",
            "description": "Service annotation migration",
            "explanation": "Spring @Service maps to CDI @ApplicationScoped",
            "complexity": "low",
            "category": "service"
        })
        
        # Component pattern
        patterns.append({
            "id": "spring-helidon-006",
            "migration_type": "annotation",
            "spring_pattern": "@Component",
            "helidon_pattern": "@ApplicationScoped",
            "spring_code": """@Component
public class MyComponent {
}""",
            "helidon_code": """@ApplicationScoped
public class MyComponent {
}""",
            "source_framework": "Spring Boot",
            "target_framework": "Helidon MP",
            "spring_version": "3.4.5",
            "helidon_version": "4.0.0",
            "description": "Component annotation migration",
            "explanation": "Spring @Component maps to CDI @ApplicationScoped",
            "complexity": "low",
            "category": "component"
        })
        
        # Configuration pattern
        patterns.append({
            "id": "spring-helidon-007",
            "migration_type": "annotation",
            "spring_pattern": "@Configuration",
            "helidon_pattern": "@ApplicationScoped + @Produces",
            "spring_code": """@Configuration
public class AppConfig {
    @Bean
    public DataSource dataSource() {
        return new HikariDataSource();
    }
}""",
            "helidon_code": """@ApplicationScoped
public class AppConfig {
    @Produces
    public DataSource dataSource() {
        return new HikariDataSource();
    }
}""",
            "source_framework": "Spring Boot",
            "target_framework": "Helidon MP",
            "spring_version": "3.4.5",
            "helidon_version": "4.0.0",
            "description": "Configuration annotation migration",
            "explanation": "Spring @Configuration with @Bean maps to CDI @ApplicationScoped with @Produces",
            "complexity": "medium",
            "category": "configuration"
        })
        
        # Value annotation pattern
        patterns.append({
            "id": "spring-helidon-008",
            "migration_type": "annotation",
            "spring_pattern": "@Value",
            "helidon_pattern": "@ConfigProperty",
            "spring_code": """@Value("${server.port}")
private int serverPort;""",
            "helidon_code": """@ConfigProperty(name = "server.port")
private int serverPort;""",
            "source_framework": "Spring Boot",
            "target_framework": "Helidon MP",
            "spring_version": "3.4.5",
            "helidon_version": "4.0.0",
            "description": "Configuration property injection migration",
            "explanation": "Spring @Value maps to MicroProfile @ConfigProperty",
            "complexity": "low",
            "category": "config_property"
        })
        
        return patterns
    
    def generate_dependency_patterns(self) -> List[Dict]:
        """Generate dependency migration patterns"""
        patterns = []
        
        # Web starter
        patterns.append({
            "id": "spring-helidon-dep-001",
            "migration_type": "dependency",
            "spring_pattern": "spring-boot-starter-web",
            "helidon_pattern": "io.helidon.microprofile.bundles:helidon-microprofile",
            "spring_code": """<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId>
    <version>3.4.5</version>
</dependency>""",
            "helidon_code": """<dependency>
    <groupId>io.helidon.microprofile.bundles</groupId>
    <artifactId>helidon-microprofile</artifactId>
    <version>4.0.0</version>
</dependency>""",
            "source_framework": "Spring Boot",
            "target_framework": "Helidon MP",
            "spring_version": "3.4.5",
            "helidon_version": "4.0.0",
            "description": "Web server dependency migration",
            "explanation": "Spring Boot web starter to Helidon MicroProfile bundle",
            "complexity": "low",
            "category": "web_server"
        })
        
        # JPA starter
        patterns.append({
            "id": "spring-helidon-dep-002",
            "migration_type": "dependency",
            "spring_pattern": "spring-boot-starter-data-jpa",
            "helidon_pattern": "io.helidon.integrations.cdi:helidon-cdi-hibernate",
            "spring_code": """<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-data-jpa</artifactId>
    <version>3.4.5</version>
</dependency>""",
            "helidon_code": """<dependency>
    <groupId>io.helidon.integrations.cdi</groupId>
    <artifactId>helidon-cdi-hibernate</artifactId>
    <version>4.0.0</version>
</dependency>""",
            "source_framework": "Spring Boot",
            "target_framework": "Helidon MP",
            "spring_version": "3.4.5",
            "helidon_version": "4.0.0",
            "description": "JPA dependency migration",
            "explanation": "Spring Boot JPA starter to Helidon CDI Hibernate",
            "complexity": "medium",
            "category": "jpa"
        })
        
        # Security starter
        patterns.append({
            "id": "spring-helidon-dep-003",
            "migration_type": "dependency",
            "spring_pattern": "spring-boot-starter-security",
            "helidon_pattern": "io.helidon.security:helidon-security",
            "spring_code": """<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-security</artifactId>
    <version>3.4.5</version>
</dependency>""",
            "helidon_code": """<dependency>
    <groupId>io.helidon.security</groupId>
    <artifactId>helidon-security</artifactId>
    <version>4.0.0</version>
</dependency>""",
            "source_framework": "Spring Boot",
            "target_framework": "Helidon MP",
            "spring_version": "3.4.5",
            "helidon_version": "4.0.0",
            "description": "Security dependency migration",
            "explanation": "Spring Boot security starter to Helidon Security",
            "complexity": "high",
            "category": "security"
        })
        
        return patterns
    
    def generate_config_patterns(self) -> List[Dict]:
        """Generate configuration migration patterns"""
        patterns = []
        
        # Server port
        patterns.append({
            "id": "spring-helidon-config-001",
            "migration_type": "config",
            "spring_pattern": "server.port",
            "helidon_pattern": "server.port",
            "spring_code": """server:
  port: 8080""",
            "helidon_code": """server.port=8080""",
            "source_framework": "Spring Boot",
            "target_framework": "Helidon MP",
            "spring_version": "3.4.5",
            "helidon_version": "4.0.0",
            "description": "Server port configuration",
            "explanation": "Same property name, different format (YAML to properties)",
            "complexity": "low",
            "category": "server_config"
        })
        
        # DataSource configuration
        patterns.append({
            "id": "spring-helidon-config-002",
            "migration_type": "config",
            "spring_pattern": "spring.datasource",
            "helidon_pattern": "javax.sql.DataSource",
            "spring_code": """spring:
  datasource:
    url: jdbc:postgresql://localhost:5432/mydb
    username: user
    password: pass""",
            "helidon_code": """javax.sql.DataSource.myDS.dataSource.url=jdbc:postgresql://localhost:5432/mydb
javax.sql.DataSource.myDS.dataSource.user=user
javax.sql.DataSource.myDS.dataSource.password=pass""",
            "source_framework": "Spring Boot",
            "target_framework": "Helidon MP",
            "spring_version": "3.4.5",
            "helidon_version": "4.0.0",
            "description": "DataSource configuration migration",
            "explanation": "Spring Boot datasource to MicroProfile DataSource format",
            "complexity": "medium",
            "category": "datasource"
        })
        
        return patterns
    
    def generate_import_patterns(self) -> List[Dict]:
        """Generate import statement migration patterns"""
        patterns = []
        
        # REST imports
        patterns.append({
            "id": "spring-helidon-import-001",
            "migration_type": "import",
            "spring_pattern": "org.springframework.web.bind.annotation.*",
            "helidon_pattern": "jakarta.ws.rs.*",
            "spring_code": """import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;""",
            "helidon_code": """import jakarta.ws.rs.Path;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.PathParam;""",
            "source_framework": "Spring Boot",
            "target_framework": "Helidon MP",
            "spring_version": "3.4.5",
            "helidon_version": "4.0.0",
            "description": "REST annotation imports migration",
            "explanation": "Spring MVC annotations to JAX-RS annotations",
            "complexity": "low",
            "category": "rest_imports"
        })
        
        # CDI imports
        patterns.append({
            "id": "spring-helidon-import-002",
            "migration_type": "import",
            "spring_pattern": "org.springframework.beans.factory.annotation.*",
            "helidon_pattern": "jakarta.inject.*",
            "spring_code": """import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;""",
            "helidon_code": """import jakarta.inject.Inject;
import jakarta.enterprise.context.ApplicationScoped;""",
            "source_framework": "Spring Boot",
            "target_framework": "Helidon MP",
            "spring_version": "3.4.5",
            "helidon_version": "4.0.0",
            "description": "Dependency injection imports migration",
            "explanation": "Spring DI annotations to CDI annotations",
            "complexity": "low",
            "category": "cdi_imports"
        })
        
        return patterns
    
    def generate_all_patterns(self) -> List[Dict]:
        """Generate all migration patterns"""
        all_patterns = []
        all_patterns.extend(self.generate_annotation_patterns())
        all_patterns.extend(self.generate_dependency_patterns())
        all_patterns.extend(self.generate_config_patterns())
        all_patterns.extend(self.generate_import_patterns())
        return all_patterns
    
    def save_to_json(self, filepath: Path):
        """Save patterns to JSON file"""
        patterns = self.generate_all_patterns()
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(patterns, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(patterns)} patterns to {filepath}")


