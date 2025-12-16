"""
Embedding Model Integration
Handles code embedding generation using CodeBERT and fallback models
"""

from typing import List, Optional
import torch
from sentence_transformers import SentenceTransformer
from src.config.settings import Settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Detect device
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
logger.info(f"Using device: {DEVICE}")


class EmbeddingModel:
    """Manages embedding model for code similarity"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = None
        self.fallback_model = None
        # Try to load model unless offline mode is explicitly requested in settings
        if getattr(self.settings, 'offline_mode', False):
            logger.info("Offline mode requested in settings")
            self.offline_mode = True
        else:
            try:
                # Load primary model
                logger.info(f"Loading embedding model: {self.settings.embedding_model}")
                self.model = SentenceTransformer(self.settings.embedding_model, device=DEVICE)
                
                # Load fallback model if different
                if self.settings.embedding_fallback != self.settings.embedding_model:
                    logger.info(f"Loading fallback model: {self.settings.embedding_fallback}")
                    self.fallback_model = SentenceTransformer(self.settings.embedding_fallback, device=DEVICE)
                
                logger.info("Embedding model loaded successfully")
                self.offline_mode = False
                
            except Exception as e:
                logger.error(f"Failed to load embedding model: {str(e)}")
                logger.warning("Falling back to offline mode with dummy embeddings")
                self.model = None
                self.fallback_model = None
                self.offline_mode = True

    def encode(
        self,
        texts: List[str],
        batch_size: Optional[int] = None,
        show_progress_bar: bool = False
    ) -> List[List[float]]:
        """
        Generate embeddings for text inputs
        
        Args:
            texts: List of text strings to embed
            batch_size: Batch size for encoding (uses settings default if None)
            show_progress_bar: Whether to show progress bar
            
        Returns:
            List of embedding vectors
        """
        if not texts:
            return []
            
        # Offline mode support
        if getattr(self, 'offline_mode', False):
            import hashlib
            import numpy as np
            
            logger.debug("Generating dummy embeddings in offline mode")
            embeddings = []
            dim = self.get_dimension()
            
            for text in texts:
                # Deterministic random vector based on text hash
                seed = int(hashlib.sha256(text.encode('utf-8')).hexdigest(), 16) % (2**32)
                np.random.seed(seed)
                # Generate normalized vector
                vec = np.random.rand(dim)
                vec = vec / np.linalg.norm(vec)
                embeddings.append(vec.tolist())
            
            return embeddings
        
        try:
            batch_size = batch_size or self.settings.batch_size
            
            # Generate embeddings
            embeddings = self.model.encode(
                texts,
                batch_size=batch_size,
                show_progress_bar=show_progress_bar,
                convert_to_numpy=True,
                normalize_embeddings=True  # Normalize for cosine similarity
            )
            
            # Convert to list of lists
            embeddings_list = embeddings.tolist()
            
            logger.debug(f"Generated {len(embeddings_list)} embeddings")
            return embeddings_list
            
        except Exception as e:
            logger.error(f"Embedding generation failed: {str(e)}")
            # Try fallback model if available
            if self.fallback_model and self.model != self.fallback_model:
                logger.warning("Trying fallback model...")
                try:
                    embeddings = self.fallback_model.encode(
                        texts,
                        batch_size=batch_size,
                        show_progress_bar=show_progress_bar,
                        convert_to_numpy=True,
                        normalize_embeddings=True
                    )
                    return embeddings.tolist()
                except Exception as e2:
                    logger.error(f"Fallback model also failed: {str(e2)}")
                    raise
            else:
                raise
    
    def encode_single(self, text: str) -> List[float]:
        """Generate embedding for a single text"""
        return self.encode([text])[0]
    
    def get_dimension(self) -> int:
        """Get embedding dimension"""
        if self.model:
            return self.model.get_sentence_embedding_dimension()
        return 768  # Default for CodeBERT
    
    def chunk_code(self, code: str, chunk_type: str = 'function') -> List[str]:
        """
        Chunk code into smaller pieces for embedding
        
        Args:
            code: Source code string
            chunk_type: Type of chunking ('function', 'class', 'file')
            
        Returns:
            List of code chunks
        """
        # TODO: Implement intelligent code chunking
        # For now, simple line-based chunking
        
        lines = code.split('\n')
        chunks = []
        
        if chunk_type == 'function':
            # Try to chunk by functions
            current_chunk = []
            for line in lines:
                current_chunk.append(line)
                # Simple heuristic: function ends with closing brace
                if line.strip().startswith('}'):
                    chunks.append('\n'.join(current_chunk))
                    current_chunk = []
            if current_chunk:
                chunks.append('\n'.join(current_chunk))
        else:
            # Default: return entire code as single chunk
            chunks = [code]
        
        return chunks

