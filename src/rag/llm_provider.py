"""
LLM Provider Abstraction
Supports multiple LLM providers: Ollama, OpenAI, Claude, Groq
"""

from typing import Optional, Dict, List
from abc import ABC, abstractmethod
from src.config.settings import Settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str:
        """Generate text from prompt"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is available"""
        pass


class OllamaProvider(LLMProvider):
    """Ollama LLM provider (local)"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.ollama_base_url
        self.model = settings.llm_model
        try:
            import ollama
            self.client = ollama
        except ImportError:
            logger.error("ollama package not installed")
            self.client = None
    
    def is_available(self) -> bool:
        """Check if Ollama is available"""
        if not self.client:
            return False
        try:
            # Try to list models to check connection
            self.client.list()
            return True
        except Exception as e:
            logger.warning(f"Ollama not available: {str(e)}")
            return False
    
    def generate(self, prompt: str, **kwargs) -> str:
        """Generate using Ollama"""
        if not self.is_available():
            raise RuntimeError("Ollama is not available")
        
        try:
            response = self.client.generate(
                model=self.model,
                prompt=prompt,
                **kwargs
            )
            return response.get('response', '')
        except Exception as e:
            logger.error(f"Ollama generation failed: {str(e)}")
            raise


class OpenAIProvider(LLMProvider):
    """OpenAI LLM provider"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.openai_api_key
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key) if self.api_key else None
        except ImportError:
            logger.error("openai package not installed")
            self.client = None
    
    def is_available(self) -> bool:
        """Check if OpenAI is available"""
        return self.client is not None and self.api_key is not None
    
    def generate(self, prompt: str, **kwargs) -> str:
        """Generate using OpenAI"""
        if not self.is_available():
            raise RuntimeError("OpenAI is not available")
        
        try:
            model = kwargs.pop('model', self.settings.llm_model)
            response = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                **kwargs
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI generation failed: {str(e)}")
            raise


class ClaudeProvider(LLMProvider):
    """Anthropic Claude LLM provider"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.anthropic_api_key
        try:
            from anthropic import Anthropic
            self.client = Anthropic(api_key=self.api_key) if self.api_key else None
        except ImportError:
            logger.error("anthropic package not installed")
            self.client = None
    
    def is_available(self) -> bool:
        """Check if Claude is available"""
        return self.client is not None and self.api_key is not None
    
    def generate(self, prompt: str, **kwargs) -> str:
        """Generate using Claude"""
        if not self.is_available():
            raise RuntimeError("Claude is not available")
        
        try:
            model = kwargs.pop('model', self.settings.llm_model)
            response = self.client.messages.create(
                model=model,
                max_tokens=kwargs.pop('max_tokens', 4096),
                messages=[{"role": "user", "content": prompt}],
                **kwargs
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Claude generation failed: {str(e)}")
            raise


class GroqProvider(LLMProvider):
    """Groq LLM provider"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.groq_api_key
        try:
            from groq import Groq
            self.client = Groq(api_key=self.api_key) if self.api_key else None
        except ImportError:
            logger.error("groq package not installed")
            self.client = None
    
    def is_available(self) -> bool:
        """Check if Groq is available"""
        return self.client is not None and self.api_key is not None
    
    def generate(self, prompt: str, **kwargs) -> str:
        """Generate using Groq"""
        if not self.is_available():
            raise RuntimeError("Groq is not available")
        
        try:
            model = kwargs.pop('model', self.settings.llm_model)
            response = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                **kwargs
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Groq generation failed: {str(e)}")
            raise


class MockProvider(LLMProvider):
    """Mock LLM provider for offline testing"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        
    def is_available(self) -> bool:
        return True
        
    def generate(self, prompt: str, **kwargs) -> str:
        """Generate mock response based on prompt patterns"""
        logger.info("Generating mock LLM response")
        
        # Simple heuristics for dependency mapping
        if "dependency" in prompt.lower() and "helidon" in prompt.lower():
            if "spring-boot-starter-web" in prompt:
                return "io.helidon.microprofile.bundles:helidon-microprofile:4.0.0"
            if "spring-boot-starter-data-jpa" in prompt:
                return "io.helidon.integrations.cdi:helidon-cdi-hibernate:4.0.0"
            if "spring-boot-starter-test" in prompt:
                return "io.helidon.microprofile.tests:helidon-microprofile-tests-junit5:4.0.0"
            
            # Generic fallback
            return "io.helidon.microprofile.bundles:helidon-microprofile:4.0.0"
            
        return "Mock response: Code transformation not implemented in mock mode."


class LLMProviderFactory:
    """Factory for creating LLM providers"""
    
    @staticmethod
    def create(settings: Settings) -> LLMProvider:
        """Create LLM provider based on settings"""
        provider_name = settings.llm_provider.lower()
        
        providers = {
            'ollama': OllamaProvider,
            'openai': OpenAIProvider,
            'claude': ClaudeProvider,
            'groq': GroqProvider,
            'mock': MockProvider
        }
        
        if provider_name not in providers:
            logger.warning(f"Unknown provider {provider_name}, defaulting to mock")
            return MockProvider(settings)
        
        provider_class = providers[provider_name]
        provider = provider_class(settings)
        
        if not provider.is_available():
            logger.warning(f"Provider {provider_name} is not available, trying fallback...")
            
            # Try Ollama as fallback
            if provider_name != 'ollama':
                fallback = OllamaProvider(settings)
                if fallback.is_available():
                    logger.info("Using Ollama as fallback")
                    return fallback
            
            # Fallback to Mock
            logger.warning("No real LLM provider available, using MockProvider")
            return MockProvider(settings)
        
        return provider

