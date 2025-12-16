#!/usr/bin/env python3
"""
Verify Dataset Optimization
Checks that patterns are stored correctly with version ranges and individual versions
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.rag.knowledge_base import KnowledgeBase
from src.rag.embeddings import EmbeddingModel
from src.config.settings import Settings

def verify_dataset():
    """Verify the optimized dataset"""
    print("=" * 80)
    print("Verifying Dataset Optimization")
    print("=" * 80)
    print()
    
    settings = Settings()
    kb = KnowledgeBase(settings)
    embedding_model = EmbeddingModel(settings)
    
    # Test 1: Check dependency patterns (should have individual versions)
    print("[Test 1] Checking dependency patterns...")
    query_text = "Spring Boot dependency: spring-boot-starter-web"
    query_embedding = embedding_model.encode_single(query_text)
    
    results = kb.search(
        collection_name='dependencies',
        query_embedding=query_embedding,
        top_k=10
    )
    
    if results:
        versions_found = set()
        for result in results:
            metadata = result.get('metadata', {})
            version = metadata.get('helidon_version', '')
            versions_found.add(version)
        
        print(f"   Found {len(results)} dependency patterns")
        print(f"   Unique versions found: {sorted(list(versions_found))[:5]}...")
        
        # Check if we have individual versions (not ranges)
        has_ranges = any('-' in v for v in versions_found)
        if has_ranges:
            print("   ⚠️  Warning: Some dependency patterns use version ranges (should be individual)")
        else:
            print("   ✅ Dependency patterns use individual versions (correct)")
    else:
        print("   ❌ No dependency patterns found")
    
    print()
    
    # Test 2: Check code patterns (should have version ranges)
    print("[Test 2] Checking code patterns...")
    query_text = "Spring Boot @RestController to Helidon"
    query_embedding = embedding_model.encode_single(query_text)
    
    results = kb.search(
        collection_name='code_patterns',
        query_embedding=query_embedding,
        top_k=10
    )
    
    if results:
        versions_found = set()
        for result in results:
            metadata = result.get('metadata', {})
            version = metadata.get('helidon_version', '')
            versions_found.add(version)
        
        print(f"   Found {len(results)} code patterns")
        print(f"   Unique versions found: {list(versions_found)[:5]}")
        
        # Check if we have version ranges
        has_ranges = any('-' in v for v in versions_found)
        if has_ranges:
            print("   ✅ Code patterns use version ranges (correct)")
        else:
            print("   ⚠️  Warning: Code patterns use individual versions (should use ranges)")
    else:
        print("   ❌ No code patterns found")
    
    print()
    
    # Test 3: Test version compatibility search
    print("[Test 3] Testing version-specific search...")
    from src.agents.dependency_agent import DependencyAgent
    
    settings.helidon_version = "4.3.2"
    agent = DependencyAgent(settings)
    
    # Search for dependency with version filter
    query_text = "Spring Boot dependency: spring-boot-starter-web to Helidon 4.3.2"
    query_embedding = embedding_model.encode_single(query_text)
    
    results = kb.search(
        collection_name='dependencies',
        query_embedding=query_embedding,
        top_k=5
    )
    
    if results:
        print(f"   Found {len(results)} patterns")
        compatible_found = False
        for result in results:
            metadata = result.get('metadata', {})
            pattern_version = metadata.get('helidon_version', '')
            is_compatible = agent._is_version_compatible(pattern_version, "4.3.2")
            if is_compatible:
                compatible_found = True
                print(f"   ✅ Compatible pattern found: version '{pattern_version}' matches '4.3.2'")
                break
        
        if not compatible_found:
            print("   ⚠️  No compatible patterns found for version 4.3.2")
    else:
        print("   ❌ No patterns found")
    
    print()
    
    # Test 4: Check collection statistics
    print("[Test 4] Collection Statistics:")
    collections = ['annotations', 'dependencies', 'code_patterns', 'config']
    for coll_name in collections:
        try:
            stats = kb.get_collection_stats(coll_name)
            print(f"   - {coll_name}: {stats['count']} patterns")
        except Exception as e:
            print(f"   - {coll_name}: Error - {str(e)}")
    
    print()
    print("=" * 80)
    print("✅ Verification complete!")
    print("=" * 80)

if __name__ == '__main__':
    try:
        verify_dataset()
    except Exception as e:
        print(f"\n❌ Verification failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

