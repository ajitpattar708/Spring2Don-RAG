"""
Helidon MP Migration Dataset Builder
Builds comprehensive migration dataset for Spring Boot to Helidon MP
Based on the structure provided by the user, adapted for Helidon MP specifics.
"""

import requests
from bs4 import BeautifulSoup
import json
from pathlib import Path
from typing import List, Dict
import re

class HelidonDatasetBuilder:
    """Builds comprehensive migration dataset for Spring Boot to Helidon MP"""
    
    def __init__(self, output_dir: str = "./migration_dataset_helidon"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.annotation_mappings = []
        self.dependency_mappings = []
        self.config_mappings = []
        self.code_examples = []
        
    def scrape_official_docs(self):
        """Scrape Helidon migration guides (Placeholder for future implementation)"""
        print("📚 Scraping official documentation (Simulated for Helidon)...")
        # In a real scenario, we would parse https://helidon.io/docs/latest/mp/guides/migration
        pass

    def add_manual_patterns(self):
        """Add manually curated migration patterns for Helidon MP"""
        print("✍️  Adding manual patterns for Helidon MP...")
        
        # Helidon MP relies on Jakarta EE standards (JAX-RS, CDI, JSON-B/P)
        manual_annotations = [
            {
                'spring': '@RestController',
                'helidon': '@Path(...) + @ApplicationScoped',
                'description': 'REST controller class annotation. Helidon uses JAX-RS @Path and CDI @ApplicationScoped.',
                'example_spring': '''@RestController
@RequestMapping("/api")
public class MyController {}''',
                'example_helidon': '''@Path("/api")
@ApplicationScoped
public class MyController {}'''
            },
            {
                'spring': '@GetMapping',
                'helidon': '@GET @Path(...)',
                'description': 'HTTP GET endpoint. JAX-RS uses @GET. If path differs from class, add @Path.',
                'example_spring': '@GetMapping("/users/{id}")',
                'example_helidon': '@GET @Path("/users/{id}")'
            },
            {
                'spring': '@PostMapping',
                'helidon': '@POST @Path(...)',
                'description': 'HTTP POST endpoint',
                'example_spring': '@PostMapping("/users")',
                'example_helidon': '@POST @Path("/users")'
            },
            {
                'spring': '@PutMapping',
                'helidon': '@PUT @Path(...)',
                'description': 'HTTP PUT endpoint',
                'example_spring': '@PutMapping("/users/{id}")',
                'example_helidon': '@PUT @Path("/users/{id}")'
            },
            {
                'spring': '@DeleteMapping',
                'helidon': '@DELETE @Path(...)',
                'description': 'HTTP DELETE endpoint',
                'example_spring': '@DeleteMapping("/users/{id}")',
                'example_helidon': '@DELETE @Path("/users/{id}")'
            },
            {
                'spring': '@Autowired',
                'helidon': '@Inject',
                'description': 'Dependency injection. Helidon uses Jakarta CDI standard.',
                'example_spring': '''@Autowired
private UserService service;''',
                'example_helidon': '''@Inject
private UserService service;'''
            },
            {
                'spring': '@Service',
                'helidon': '@ApplicationScoped',
                'description': 'Service layer bean. CDI @ApplicationScoped is the closest equivalent.',
                'example_spring': '''@Service
public class UserService {}''',
                'example_helidon': '''@ApplicationScoped
public class UserService {}'''
            },
            {
                'spring': '@Component',
                'helidon': '@ApplicationScoped',
                'description': 'Generic component. Often @ApplicationScoped or @Dependent in CDI.',
                'example_spring': '''@Component
public class MyComponent {}''',
                'example_helidon': '''@ApplicationScoped
public class MyComponent {}'''
            },
            {
                'spring': '@Configuration',
                'helidon': '@ApplicationScoped',
                'description': 'Configuration class. In CDI, these are often just ApplicationScoped beans producing other beans.',
                'example_spring': '''@Configuration
public class AppConfig {}''',
                'example_helidon': '''@ApplicationScoped
public class AppConfig {}'''
            },
            {
                'spring': '@Bean',
                'helidon': '@Produces',
                'description': 'Bean definition method. CDI uses @Produces.',
                'example_spring': '''@Bean
public DataSource dataSource() {}''',
                'example_helidon': '''@Produces
public DataSource dataSource() {}'''
            },
            {
                'spring': '@Value("${property}")',
                'helidon': '@ConfigProperty(name="property")',
                'description': 'Property injection. MicroProfile Config standard.',
                'example_spring': '''@Value("${app.name}")
private String appName;''',
                'example_helidon': '''@Inject
@ConfigProperty(name="app.name")
private String appName;'''
            },
            {
                'spring': '@RequestBody',
                'helidon': '(No annotation)',
                'description': 'Request body. JAX-RS assumes the unannotated parameter is the body.',
                'example_spring': 'public void create(@RequestBody User user)',
                'example_helidon': 'public void create(User user)'
            },
            {
                'spring': '@PathVariable',
                'helidon': '@PathParam',
                'description': 'Path variable extraction',
                'example_spring': 'public User get(@PathVariable Long id)',
                'example_helidon': 'public User get(@PathParam("id") Long id)'
            },
            {
                'spring': '@RequestParam',
                'helidon': '@QueryParam',
                'description': 'Query parameter binding',
                'example_spring': 'public List<User> search(@RequestParam String name)',
                'example_helidon': 'public List<User> search(@QueryParam("name") String name)'
            },
            {
                'spring': '@ResponseStatus',
                'helidon': 'Response.status(...)',
                'description': 'Return types often wrap in Response object for status control.',
                'example_spring': '@ResponseStatus(HttpStatus.CREATED)',
                'example_helidon': 'return Response.status(Response.Status.CREATED).build();'
            },
            {
                'spring': '@ExceptionHandler',
                'helidon': '@Provider implements ExceptionMapper<T>',
                'description': 'Exception handling done via ExceptionMapper provider.',
                'example_spring': '(@ExceptionHandler)',
                'example_helidon': 'class MyMapper implements ExceptionMapper<MyException> ...'
            },
            {
                'spring': '@Transactional',
                'helidon': '@Transactional',
                'description': 'Transaction management (Jakarta Transactions).',
                'example_spring': '''@Transactional
public void save(User user)''',
                'example_helidon': '''@Transactional
public void save(User user)'''
            },
            {
                'spring': '@Scheduled',
                'helidon': '@Scheduled',
                'description': 'Scheduled tasks (Helidon Scheduling extension).',
                'example_spring': '@Scheduled(fixedRate = 5000)',
                'example_helidon': '@Scheduled(fixedRate = 5, timeUnit = TimeUnit.SECONDS)'
            }
        ]
        
        self.annotation_mappings.extend(manual_annotations)
        
        # Helidon Dependency Mappings
        manual_dependencies = [
            {
                'spring': 'spring-boot-starter-web',
                'helidon': 'helidon-microprofile',
                'group': 'io.helidon.microprofile',
                'description': 'Full MicroProfile bundle (includes Server, JAX-RS, CDI, etc)'
            },
            {
                'spring': 'spring-boot-starter-data-jpa',
                'helidon': 'helidon-integrations-cdi-jpa',
                'group': 'io.helidon.integrations.cdi',
                'description': 'JPA integration for CDI'
            },
            {
                'spring': 'spring-boot-starter-actuator',
                'helidon': 'helidon-microprofile-health',
                'group': 'io.helidon.microprofile.health',
                'description': 'Health checks'
            },
             {
                'spring': 'spring-boot-starter-actuator',
                'helidon': 'helidon-microprofile-metrics',
                'group': 'io.helidon.microprofile.metrics',
                'description': 'Metrics'
            },
            {
                'spring': 'spring-boot-starter-security',
                'helidon': 'helidon-microprofile-security',
                'group': 'io.helidon.microprofile.security',
                'description': 'Security integration'
            },
            {
                'spring': 'spring-kafka',
                'helidon': 'helidon-messaging-kafka',
                'group': 'io.helidon.messaging.kafka',
                'description': 'Kafka reactive messaging'
            },
            {
                'spring': 'spring-boot-starter-test',
                'helidon': 'helidon-microprofile-tests-junit5',
                'group': 'io.helidon.microprofile.tests',
                'description': 'JUnit 5 testing support'
            }
        ]
        
        self.dependency_mappings.extend(manual_dependencies)
        
        # Configuration mappings
        manual_configs = [
            {
                'spring': 'server.port',
                'helidon': 'server.port',
                'type': 'integer',
                'example_value': 8080,
                'note': 'Standard in Helidon Config'
            },
            {
                'spring': 'spring.datasource.url',
                'helidon': 'javax.sql.DataSource.dataSource.url',
                'type': 'string',
                'example_value': 'jdbc:postgresql://localhost/db',
                'note': 'Naming convention for default datasource'
            },
            {
                'spring': 'spring.datasource.username',
                'helidon': 'javax.sql.DataSource.dataSource.user',
                'type': 'string',
                'example_value': 'user'
            },
            {
                'spring': 'spring.datasource.password',
                'helidon': 'javax.sql.DataSource.dataSource.password',
                'type': 'string',
                'example_value': 'password'
            },
            {
                'spring': 'spring.jpa.show-sql',
                'helidon': 'javax.persistence.schema-generation.database.action',
                'type': 'string',
                'example_value': 'drop-and-create',
                'note': 'JPA standardized properties in persistence.xml or config'
            }
        ]
        
        self.config_mappings.extend(manual_configs)
        
        print(f"  ✓ Added {len(manual_annotations)} annotation patterns")
        print(f"  ✓ Added {len(manual_dependencies)} dependency mappings")
        print(f"  ✓ Added {len(manual_configs)} config mappings")

    def add_code_examples(self):
        """Add full code transformation examples for Helidon"""
        print("💻 Adding code examples for Helidon...")
        
        examples = [
            {
                'name': 'Simple REST Controller',
                'spring_code': '''package com.example.demo;

import org.springframework.web.bind.annotation.*;
import org.springframework.beans.factory.annotation.Autowired;
import java.util.List;

@RestController
@RequestMapping("/api/users")
public class UserController {
    
    @Autowired
    private UserService userService;
    
    @GetMapping
    public List<User> getAll() {
        return userService.findAll();
    }
    
    @GetMapping("/{id}")
    public User getById(@PathVariable Long id) {
        return userService.findById(id);
    }
    
    @PostMapping
    public User create(@RequestBody User user) {
        return userService.save(user);
    }
}''',
                'helidon_code': '''package com.example.demo;

import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import jakarta.ws.rs.*;
import jakarta.ws.rs.core.MediaType;
import java.util.List;

@Path("/api/users")
@ApplicationScoped
public class UserController {
    
    @Inject
    private UserService userService;
    
    @GET
    @Produces(MediaType.APPLICATION_JSON)
    public List<User> getAll() {
        return userService.findAll();
    }
    
    @GET
    @Path("/{id}")
    @Produces(MediaType.APPLICATION_JSON)
    public User getById(@PathParam("id") Long id) {
        return userService.findById(id);
    }
    
    @POST
    @Consumes(MediaType.APPLICATION_JSON)
    @Produces(MediaType.APPLICATION_JSON)
    public User create(User user) {
        return userService.save(user);
    }
}'''
            },
            {
                'name': 'Service with Repository',
                'spring_code': '''package com.example.demo;

import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional
public class UserService {
    
    @Autowired
    private UserRepository repository;
    
    public User save(User user) {
        return repository.save(user);
    }
}''',
                'helidon_code': '''package com.example.demo;

import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import jakarta.transaction.Transactional;

@ApplicationScoped
@Transactional
public class UserService {
    
    @Inject
    private UserRepository repository;
    
    public User save(User user) {
        return repository.save(user);
    }
}'''
            }
        ]
        
        self.code_examples.extend(examples)
        print(f"  ✓ Added {len(examples)} code examples")
        
    def save_dataset(self):
        """Save collected data to files"""
        print("\n💾 Saving dataset...")
        
        # We will also combine them into the single format our RAG expects
        combined_patterns = []
        
        # Convert annotations to combined format
        for m in self.annotation_mappings:
            combined_patterns.append({
                "id": f"helidon_manual_annotation_{len(combined_patterns)}",
                "migration_type": "annotation",
                "spring_pattern": m['spring'],
                "helidon_pattern": m['helidon'],
                "description": m['description'],
                "source_framework": "spring",
                "target_framework": "helidon",
                "spring_code": m['example_spring'],
                "helidon_code": m['example_helidon'],
                "metadata": {"source": "manual_builder", "confidence": 1.0}
            })

        # Convert dependencies
        for m in self.dependency_mappings:
            combined_patterns.append({
                "id": f"helidon_manual_dependency_{len(combined_patterns)}",
                "migration_type": "dependency",
                "spring_pattern": m['spring'],
                "helidon_pattern": m['helidon'],
                "description": m['description'],
                "source_framework": "spring",
                "target_framework": "helidon",
                "metadata": {"source": "manual_builder", "confidence": 1.0}
            })
            
         # Convert configs
        for m in self.config_mappings:
            combined_patterns.append({
                "id": f"helidon_manual_config_{len(combined_patterns)}",
                "migration_type": "configuration",
                "spring_pattern": m['spring'],
                "helidon_pattern": m['helidon'],
                "description": f"Map {m['spring']} to {m['helidon']}",
                "source_framework": "spring",
                "target_framework": "helidon",
                "metadata": {"source": "manual_builder", "confidence": 1.0}
            })
            
        # Code examples
        for m in self.code_examples:
            combined_patterns.append({
                 "id": f"helidon_manual_code_{len(combined_patterns)}",
                "migration_type": "code_pattern",
                "spring_pattern": "Full Class",
                "helidon_pattern": "Full Class",
                "description": f"Migration example: {m['name']}",
                "source_framework": "spring",
                "target_framework": "helidon",
                "spring_code": m['spring_code'],
                "helidon_code": m['helidon_code'],
                "metadata": {"source": "manual_builder", "confidence": 1.0}
            })

        output_file = Path('migration_dataset_helidon_manual.json')
        with open(output_file, 'w') as f:
            json.dump(combined_patterns, f, indent=2)
            
        print(f"\n✅ Combined dataset saved to: {output_file} ({len(combined_patterns)} items)")

    def build_complete_dataset(self):
        """Build complete migration dataset"""
        print("=" * 60)
        print("BUILDING HELIDON MIGRATION DATASET")
        print("=" * 60)
        
        self.add_manual_patterns()
        self.add_code_examples()
        self.save_dataset()

if __name__ == "__main__":
    builder = HelidonDatasetBuilder()
    builder.build_complete_dataset()
