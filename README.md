# Spring Boot to Helidon MP Migration Agent

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Helidon](https://img.shields.io/badge/Helidon-4.x-green)](https://helidon.io/)
[![Status](https://img.shields.io/badge/status-active-green.svg)]()

> **Production Ready** - This project facilitates the migration of Spring Boot applications to Helidon MP 4.x with high fidelity.

An intelligent AI-powered RAG (Retrieval-Augmented Generation) agent that automatically migrates Spring Boot 3.x.x projects to Helidon MP 4.x.x projects with version-specific compatibility handling.

## Features
- **AI-Powered Migration** - Uses RAG (Retrieval-Augmented Generation) with regex fallback for high-fidelity transformations
- **Knowledge Base** - Vector database (ChromaDB) with 10,000+ migration patterns
- **Hybrid Intelligence** - Combines Vector Search (Semantics) with Deterministic Regex (Syntax)
- **Multi-LLM Support** - Ollama, OpenAI, Claude, or Groq
- **Version-Aware** - Handles Spring Boot 3.x.x → Helidon MP 4.x.x (Java 21)
- **Dependency Resolution** - Intelligent Maven dependency mapping and deduplication
- **Configuration Migration** - Automatic conversion to MicroProfile Config
- **Multi-Agent System** - Specialized agents for Dependencies, Code Transformation, and Validation

## Table of Contents
- [Quick Start](#quick-start)
- [User Guide](USER_GUIDE.md) **Start Here**
- [Installation](#installation)
- [Usage](#usage)
- [Architecture](#architecture)
- [What Gets Migrated](#what-gets-migrated)
- [Contributing](#contributing)
- [License](#license)

## Quick Start
### Prerequisites
- Python 3.10+
- Java 21 (for Helidon 4.x)
- Maven 3.8+

### Basic Usage
1.  **Clone the Repository**
2.  **Get the Brain**: Download `knowledge_base.zip` from [Releases](#) and unzip to `migration_db/`.
3.  **Migrate**:
    ```bash
    python migration_agent_main.py migrate \
        /path/to/source-spring-app \
        /path/to/target-helidon-app
    ```

## Architecture
The agent uses a Multi-Agent Orchestrator pattern:
1.  **Dependency Agent**: Scans `pom.xml`, removes Spring artifacts, adds Helidon Bundles (MP, CDI, etc.), and fixes parent POMs.
2.  **Code Transform Agent**:
    *   **RAG Lookup**: Finds semantic equivalents for Annotations and Classes.
    *   **Regex Engine**: Applies deterministic fixes (e.g., `RestTemplate` -> `ClientBuilder`, `ThreadPoolTaskExecutor` -> `ExecutorService`).
3.  **Knowledge Base**: A curated ChromaDB vector store containing typical migration patterns, "learned" through manual refinement.

## What Gets Migrated
### Supported Migrations
- **Annotations:** 
    - `@RestController` → `@Path`, `@ApplicationScoped`
    - `@GetMapping` → `@GET`, `@Path`
    - `@Autowired` → `@Inject`
    - `@Value` → `@ConfigProperty`
- **Dependencies:** Spring Boot Starters → Helidon MP Bundles
- **Configuration:** Spring Beans (`@Bean`) → CDI Producers (`@Produces`)
- **HTTP Client:** `RestTemplate` → JAX-RS `Client`
- **Threading:** `ThreadPoolTaskExecutor` → `ExecutorService`
- **Proxy:** Spring Cloud Gateway Proxy → JAX-RS Client Proxy

### Limitations
- Currently supports **Maven** only.
- **Java** only.
- Complex Spring Integration flows may require manual review.

## Contributing
We welcome contributions! Please see the [User Guide](USER_GUIDE.md#contributing) for details on how to generate the dataset locally and submit PRs.

## License
This project is licensed under the Apache 2.0 License.
