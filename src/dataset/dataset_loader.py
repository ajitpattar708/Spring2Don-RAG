"""
Dataset Loader
Loads migration patterns into ChromaDB knowledge base
"""

import json
from pathlib import Path
from typing import List, Dict
from src.rag.knowledge_base import KnowledgeBase
from src.rag.embeddings import EmbeddingModel
from src.config.settings import Settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class DatasetLoader:
    """Loads migration patterns into the knowledge base"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.knowledge_base = KnowledgeBase(settings)
        self.embedding_model = EmbeddingModel(settings)
    
    def load_from_json(self, json_file: Path):
        """Load patterns from JSON file into knowledge base"""
        logger.info(f"Loading patterns from {json_file}")
        
        with open(json_file, 'r', encoding='utf-8') as f:
            patterns = json.load(f)
        
        logger.info(f"Found {len(patterns)} patterns to load")
        
        # Group patterns by type
        patterns_by_type = {}
        for pattern in patterns:
            pattern_type = pattern.get('migration_type', 'unknown')
            if pattern_type not in patterns_by_type:
                patterns_by_type[pattern_type] = []
            patterns_by_type[pattern_type].append(pattern)
        
        # Load into appropriate collections
        collection_mapping = {
            'annotation': 'annotations',
            'dependency': 'dependencies',
            'config': 'config',
            'code_pattern': 'code_patterns',
            'import': 'imports'
        }
        
        for pattern_type, patterns_list in patterns_by_type.items():
            collection_name = collection_mapping.get(pattern_type, 'code_patterns')
            self._load_patterns_to_collection(collection_name, patterns_list)
        
        logger.info("Dataset loading completed")
    
    def _load_patterns_to_collection(self, collection_name: str, patterns: List[Dict]):
        """Load patterns into a specific collection"""
        logger.info(f"Loading {len(patterns)} patterns into '{collection_name}' collection")
        
        # Prepare patterns for ChromaDB
        chroma_patterns = []
        
        # Batch processing for embeddings
        batch_texts = []
        batch_patterns = []
        
        # 1. Collect all texts and patterns
        for pattern in patterns:
            # Create text representation for embedding
            text_parts = []
            if pattern.get('spring_code'):
                text_parts.append(f"Spring Code:\n{pattern['spring_code']}")
            if pattern.get('helidon_code'):
                text_parts.append(f"Helidon Code:\n{pattern['helidon_code']}")
            if pattern.get('explanation'):
                text_parts.append(f"Explanation: {pattern['explanation']}")
            
            text = "\n\n".join(text_parts)
            batch_texts.append(text)
            batch_patterns.append(pattern)

        # 2. Generate embeddings in bulk (Much Faster)
        logger.info(f"Generating embeddings for {len(batch_texts)} patterns...")
        all_embeddings = self.embedding_model.encode(batch_texts, batch_size=64, show_progress_bar=True)
        
        # 3. Assemble ChromaDB documents
        for i, pattern in enumerate(batch_patterns):
            embedding = all_embeddings[i]
            
            # Prepare metadata
            metadata = {
                'id': pattern.get('id', ''),
                'migration_type': pattern.get('migration_type', ''),
                'spring_pattern': pattern.get('spring_pattern', ''),
                'helidon_pattern': pattern.get('helidon_pattern', ''),
                'spring_version': pattern.get('spring_version', ''),
                'helidon_version': pattern.get('helidon_version', ''),
                'complexity': pattern.get('complexity', ''),
                'category': pattern.get('category', ''),
                'description': pattern.get('description', '')
            }
            
            chroma_patterns.append({
                'id': pattern.get('id', f"{collection_name}-{i}"),
                'text': batch_texts[i],
                'embedding': embedding,
                'metadata': metadata
            })
            
        # Add to knowledge base with batching
        try:
            BATCH_SIZE = 5000  # Safe batch size under 5461 limit
            total = len(chroma_patterns)
            
            for i in range(0, total, BATCH_SIZE):
                batch = chroma_patterns[i:i + BATCH_SIZE]
                logger.info(f"Adding batch {i//BATCH_SIZE + 1}/{(total-1)//BATCH_SIZE + 1} ({len(batch)} patterns)")
                self.knowledge_base.add_patterns(collection_name, batch)
                
            logger.info(f"Successfully loaded {len(chroma_patterns)} patterns into '{collection_name}'")
        except Exception as e:
            logger.error(f"Failed to load patterns into '{collection_name}': {str(e)}")
            raise
    
    def initialize_knowledge_base(self, dataset_file: Path):
        """Initialize knowledge base with dataset"""
        if not dataset_file.exists():
            logger.warning(f"Dataset file not found: {dataset_file}")
            logger.info("Creating sample dataset...")
            self._create_sample_dataset(dataset_file)
        
        self.load_from_json(dataset_file)
        
        # Print statistics
        for collection_name in self.knowledge_base.collections.keys():
            stats = self.knowledge_base.get_collection_stats(collection_name)
            logger.info(f"Collection '{collection_name}': {stats['count']} patterns")
    
    def _create_sample_dataset(self, dataset_file: Path):
        """Create sample dataset if it doesn't exist"""
        from src.dataset.dataset_generator import DatasetGenerator
        
        generator = DatasetGenerator()
        generator.save_to_json(dataset_file)
        logger.info(f"Created sample dataset at {dataset_file}")


