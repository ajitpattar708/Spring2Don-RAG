# Spring Boot to Helidon MP Migration Agent

This AI-powered agent automates the migration of legacy Spring Boot applications to Helidon MP (MicroProfile). It uses Retrieval-Augmented Generation (RAG) and regex-based fallback mechanisms to ensure high-accuracy code transformation.

## 📋 Prerequisites

*   **Python 3.10+**: For running the migration agent.
*   **Java 21**: Required for building Helidon MP 4.x applications.
*   **Maven 3.8+**: For dependency management.
*   **Ollama (Optional)**: If you plan to use local LLM inference (e.g., CodeLlama).

## ⚙️ System Requirements & Performance

*   **Memory (RAM)**: Minimum 8GB recommended (16GB preferred if running local LLMs).
*   **Disk Space**: ~1GB free space (approx. 600MB for the Knowledge Base).
*   **Performance Estimates**:
    *   **Setup**: < 5 minutes (mostly download time).
    *   **Migration**: Fast (~2-5 seconds per file).
    *   **Initialization (Dev Mode)**: 10-15 minutes (CPU dependent) to generate embeddings.

## 🚀 Setup

1.  **Clone the repository**:
    ```bash
    git clone <repository-url>
    cd Spring2Don-RAG
    ```

2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure Environment**:
    Copy `.env.example` to `.env` (if available) or create a `.env` file with your preferences:
    ```ini
    # .env
    CHROMADB_PATH=./migration_db
    LLM_PROVIDER=ollama   # or openai, anthropic
    # OPENAI_API_KEY=sk-... (if using OpenAI)
    ```

## 🧠 Knowledge Base Setup

You have two options to set up the Agent's AI brain. **Option A is recommended for end-users.**

### Option A: Use Pre-built Knowledge Base (Recommended)
This ensures you use the exact same validated migration patterns as the development team.

1.  Download the **`knowledge_base.zip`** from the [Releases Page](<LINK_TO_RELEASES>).
2.  Unzip the file into the project root. You should see a folder named `migration_db`.
    ```bash
    # Structure should look like:
    Spring2Don-RAG/
    ├── migration_db/
    │   ├── chroma.sqlite3
    │   └── ...
    ├── src/
    └── ...
    ```
3.  **Skip** the `init` command. You are ready to migrate!

### Option B: Initialize from Source (For Contributors)
If you want to modify migration patterns or contribute to the project, you can generate the knowledge base locally.

```bash
# This generates migration_dataset_production.json and builds the vector DB
python migration_agent_main.py init
```

## 🤝 Contributing

We welcome community contributions! If you find a missing pattern or a better migration strategy:

1.  **Modify the Generator**:
    *   Edit `src/dataset/production_dataset_generator.py`.
    *   Add your new pattern to methods like `_generate_core_config_patterns` or `_generate_learned_code_patterns`.
    
2.  **Verify**:
    *   Run `python migration_agent_main.py init` to ensure the dataset generates correctly.
    *   Run `python migration_agent_main.py test` to verify no regressions.

3.  **Submit PR**:
    *   Commit your changes to the `.py` files.
    *   **Do NOT commit** the generated JSON files or `migration_db` folder (handled by `.gitignore`).
    *   Open a Pull Request describing your changes.

## 🔒 Data Privacy

*   **Logic vs Data**: The migration logic and patterns are open source in `src/`.
*   **Vector DB**: The compiled `migration_db` is local to your machine.
*   **Secrets**: Ensure `.env` is never committed.

## 🛠️ Usage

### Migrate a Project

Run the agent pointing to your source Spring Boot project and the desired output directory.

**Option 1: Default (Auto-Detect Versions)**
This mode detects the Spring Boot version from `pom.xml` and defaults Helidon to 4.x.
```bash
python migration_agent_main.py migrate \
  /path/to/source/spring-project \
  /path/to/target/helidon-project
```

**Option 2: Explicit Versions (Recommended)**
Specify exact source and target versions for precise migration patterns.
```bash
python migration_agent_main.py migrate \
  /path/to/source/spring-project \
  /path/to/target/helidon-project \
  --spring-version 3.4.5 \
  --helidon-version 4.3.2
```

### Run Tests (Verify Migration Logic)

To verify the agent works correctly against the included example project:

```bash
python migration_agent_main.py test
```

## 🔒 Data Privacy & Control

To ensure sensitive data and large datasets are not accidentally committed to GitHub, the `.gitignore` is configured to exclude:

*   `migration_db/` (The Vector Database)
*   `migration_dataset_*.json` (Generated Datasets)
*   `examples/helidon/` (Test Output)
*   `.env` (Secrets)

**What is committed:**
*   Agent Source Code (`src/`, `scripts/`)
*   Configuration logic
*   Generator scripts (which allows anyone to "rehydrate" the dataset locally using the `init` command without needing the raw data files in the repo).
