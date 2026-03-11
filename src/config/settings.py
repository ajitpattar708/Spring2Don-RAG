"""
Configuration settings for the migration agent
"""

import os
from typing import Optional
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@dataclass
class Settings:
    """Application settings loaded from environment variables"""
    
    # LLM Configuration
    llm_provider: str = os.getenv('LLM_PROVIDER', 'ollama')
    llm_model: str = os.getenv('LLM_MODEL', 'codellama:7b')
    openai_api_key: Optional[str] = os.getenv('OPENAI_API_KEY')
    anthropic_api_key: Optional[str] = os.getenv('ANTHROPIC_API_KEY')
    groq_api_key: Optional[str] = os.getenv('GROQ_API_KEY')
    
    # Embedding Model
    embedding_model: str = os.getenv('EMBEDDING_MODEL', 'microsoft/codebert-base')
    embedding_fallback: str = os.getenv('EMBEDDING_FALLBACK', 'sentence-transformers/all-MiniLM-L6-v2')
    
    # ChromaDB Configuration
    chromadb_path: str = os.getenv('CHROMADB_PATH', './migration_db')
    
    # Ollama Configuration
    ollama_base_url: str = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
    
    # Performance Settings
    batch_size: int = int(os.getenv('BATCH_SIZE', '32'))
    max_workers: int = int(os.getenv('MAX_WORKERS', '4'))
    
    # RAG Settings
    top_k: int = int(os.getenv('TOP_K', '5'))
    similarity_threshold: float = float(os.getenv('SIMILARITY_THRESHOLD', '0.7'))
    
    # Logging
    log_level: str = os.getenv('LOG_LEVEL', 'INFO')
    
    # Migration versions (set during migration)
    spring_version: Optional[str] = None
    helidon_version: Optional[str] = None
    
    # Offline Mode
    offline_mode: bool = os.getenv('OFFLINE_MODE', 'false').lower() == 'true'

    # GA Guardrails
    require_kb: bool = os.getenv('REQUIRE_KB', 'true').lower() == 'true'
    require_llm_consent: bool = os.getenv('REQUIRE_LLM_CONSENT', 'true').lower() == 'true'
    llm_consent: str = os.getenv('LLM_CONSENT', '').lower()
    llm_validation_strict: bool = os.getenv('LLM_VALIDATION_STRICT', 'true').lower() == 'true'
    migration_report_path: str = os.getenv('MIGRATION_REPORT_PATH', 'migration_report.json')
    datasource_name: str = os.getenv('DATASOURCE_NAME', 'myDS')
    
    def validate(self) -> bool:
        """Validate settings"""
        if self.llm_provider == 'openai' and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when using OpenAI provider")
        if self.llm_provider == 'claude' and not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when using Claude provider")
        if self.llm_provider == 'groq' and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when using Groq provider")

        # Enforce explicit consent for remote LLMs (GA safety)
        if self.require_llm_consent and self.llm_provider in {'openai', 'claude', 'groq'}:
            if self.llm_consent not in {'yes', 'true'}:
                raise ValueError(
                    "LLM_CONSENT must be set to 'yes' or 'true' to use remote LLM providers. "
                    "Set REQUIRE_LLM_CONSENT=false to override."
                )
        return True

