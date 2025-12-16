"""
RAG Knowledge Base
Manages ChromaDB vector database for migration patterns
"""

from typing import List, Dict, Optional
import chromadb
from chromadb.config import Settings as ChromaSettings
from pathlib import Path
from src.config.settings import Settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class KnowledgeBase:
    """Manages the vector database for migration patterns"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = None
        self.collections = {}
        self._initialize()
    
    def _initialize(self):
        """Initialize ChromaDB client and collections"""
        try:
            print("--- Initializing ChromaDB ---", flush=True)
            # Create persistent client
            self.client = chromadb.PersistentClient(
                path=self.settings.chromadb_path,
                settings=ChromaSettings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            
            # Initialize collections for different pattern types
            self._create_collections()
            
            logger.info(f"Knowledge base initialized at: {self.settings.chromadb_path}")
            
        except Exception as e:
            logger.error(f"Failed to initialize knowledge base: {str(e)}")
            raise
    
    def _create_collections(self):
        """Create ChromaDB collections for different pattern types"""
        collections_config = [
            ('annotations', 'Annotation migration patterns'),
            ('dependencies', 'Dependency migration patterns'),
            ('code_patterns', 'Code pattern migrations'),
            ('config', 'Configuration migration patterns'),
            ('imports', 'Import statement migrations')
        ]
        
        for collection_name, description in collections_config:
            try:
                collection = self.client.get_or_create_collection(
                    name=collection_name,
                    metadata={"description": description}
                )
                self.collections[collection_name] = collection
                logger.debug(f"Collection '{collection_name}' ready")
            except Exception as e:
                logger.error(f"Failed to create collection '{collection_name}': {str(e)}")
                raise
    
    def add_patterns(self, collection_name: str, patterns: List[Dict]):
        """
        Add migration patterns to knowledge base
        
        Args:
            collection_name: Name of the collection
            patterns: List of pattern dictionaries with 'id', 'text', 'embedding', 'metadata'
        """
        if collection_name not in self.collections:
            raise ValueError(f"Collection '{collection_name}' not found")
        
        collection = self.collections[collection_name]
        
        try:
            # Extract data from patterns
            ids = [p['id'] for p in patterns]
            texts = [p.get('text', '') for p in patterns]
            embeddings = [p.get('embedding') for p in patterns]
            metadatas = [p.get('metadata', {}) for p in patterns]
            
            # Filter out None embeddings (will be computed by ChromaDB)
            if all(e is None for e in embeddings):
                embeddings = None
            
            collection.add(
                ids=ids,
                documents=texts if texts else None,
                embeddings=embeddings,
                metadatas=metadatas
            )
            
            logger.info(f"Added {len(patterns)} patterns to '{collection_name}' collection")
            
        except Exception as e:
            logger.error(f"Failed to add patterns: {str(e)}")
            raise
    
    def search(
        self,
        collection_name: str,
        query_embedding: Optional[List[float]] = None,
        query_text: Optional[str] = None,
        top_k: int = 5,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Search for similar patterns in knowledge base
        
        Args:
            collection_name: Name of the collection to search
            query_embedding: Query embedding vector
            query_text: Query text (if embedding not provided)
            top_k: Number of results to return
            filters: Metadata filters
            
        Returns:
            List of similar patterns with scores
        """
        if collection_name not in self.collections:
            raise ValueError(f"Collection '{collection_name}' not found")
        
        collection = self.collections[collection_name]
        
        try:
            # Convert filters to ChromaDB format if provided
            chroma_where = None
            if filters:
                # ChromaDB expects filters in format: {"$and": [{"field": "value"}, ...]}
                # or {"field": "value"} for single filter
                if len(filters) == 1:
                    # Single filter - direct format
                    key, value = list(filters.items())[0]
                    chroma_where = {key: {"$eq": value}}
                else:
                    # Multiple filters - use $and
                    chroma_where = {
                        "$and": [{key: {"$eq": value}} for key, value in filters.items()]
                    }
            
            if query_embedding:
                results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=top_k,
                    where=chroma_where
                )
            elif query_text:
                results = collection.query(
                    query_texts=[query_text],
                    n_results=top_k,
                    where=chroma_where
                )
            else:
                raise ValueError("Either query_embedding or query_text must be provided")
            
            # Format results
            patterns = []
            if results['ids'] and len(results['ids'][0]) > 0:
                for i in range(len(results['ids'][0])):
                    pattern = {
                        'id': results['ids'][0][i],
                        'text': results['documents'][0][i] if results['documents'] else '',
                        'metadata': results['metadatas'][0][i] if results['metadatas'] else {},
                        'distance': results['distances'][0][i] if results['distances'] else None,
                        'similarity': 1 - results['distances'][0][i] if results['distances'] else None
                    }
                    patterns.append(pattern)
            
            logger.debug(f"Found {len(patterns)} patterns in '{collection_name}'")
            return patterns
            
        except Exception as e:
            logger.error(f"Search failed: {str(e)}")
            raise
    
    def get_collection_stats(self, collection_name: str) -> Dict:
        """Get statistics for a collection"""
        if collection_name not in self.collections:
            raise ValueError(f"Collection '{collection_name}' not found")
        
        collection = self.collections[collection_name]
        count = collection.count()
        
        return {
            'name': collection_name,
            'count': count
        }

