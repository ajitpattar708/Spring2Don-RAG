#!/usr/bin/env python3
"""
Test Pattern Storage Optimization
Verifies that code patterns use version ranges and dependencies use individual versions
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.dataset.production_dataset_generator import ProductionDatasetGenerator
from src.agents.dependency_agent import DependencyAgent
from src.config.settings import Settings

def test_pattern_generation():
    """Test that patterns are generated correctly with optimization"""
    print("=" * 80)
    print("Testing Pattern Storage Optimization")
    print("=" * 80)
    print()
    
    generator = ProductionDatasetGenerator()
    
    # Test 1: Check version range is set
    print("[Test 1] Checking version range configuration...")
    assert hasattr(generator, 'helidon_version_range'), "Version range not set!"
    assert generator.helidon_version_range == "4.0.0-4.3.2", f"Expected '4.0.0-4.3.2', got '{generator.helidon_version_range}'"
    print(f"   ✅ Version range: {generator.helidon_version_range}")
    print()
    
    # Test 2: Generate a small sample of patterns
    print("[Test 2] Generating sample patterns...")
    
    # Generate annotation patterns (should use version range)
    annotation_patterns = generator._generate_core_annotation_patterns()
    print(f"   Generated {len(annotation_patterns)} annotation patterns")
    
    # Check first annotation pattern uses version range
    if annotation_patterns:
        first_anno = annotation_patterns[0]
        anno_version = first_anno.get('helidon_version', '')
        assert anno_version == "4.0.0-4.3.2", f"Annotation pattern should use range, got '{anno_version}'"
        print(f"   ✅ Annotation pattern version: {anno_version} (version range)")
    
    # Generate dependency patterns (should use individual versions)
    dependency_patterns = generator._generate_core_dependency_patterns()
    print(f"   Generated {len(dependency_patterns)} dependency patterns")
    
    # Check dependency patterns use individual versions
    if dependency_patterns:
        dep_versions = set()
        for dep in dependency_patterns[:10]:  # Check first 10
            dep_version = dep.get('helidon_version', '')
            dep_versions.add(dep_version)
            assert dep_version in generator.helidon_versions, f"Dependency should use individual version, got '{dep_version}'"
        
        print(f"   ✅ Dependency patterns use individual versions: {sorted(list(dep_versions))[:5]}...")
        print(f"   ✅ Total unique versions in dependencies: {len(dep_versions)}")
    
    # Generate synthetic patterns (should use version range)
    synthetic_patterns = generator._generate_synthetic_patterns(100)  # Small sample
    print(f"   Generated {len(synthetic_patterns)} synthetic patterns")
    
    if synthetic_patterns:
        synth_versions = set()
        for synth in synthetic_patterns:
            synth_version = synth.get('helidon_version', '')
            synth_versions.add(synth_version)
        
        assert len(synth_versions) == 1, f"Synthetic patterns should all use same version range, got {synth_versions}"
        assert "4.0.0-4.3.2" in synth_versions, f"Synthetic patterns should use version range, got {synth_versions}"
        print(f"   ✅ Synthetic patterns version: {list(synth_versions)[0]} (version range)")
    
    print()
    
    # Test 3: Count pattern types
    print("[Test 3] Pattern distribution...")
    all_patterns = generator.generate_all_patterns()
    print(f"   Total patterns generated: {len(all_patterns)}")
    
    # Count by type
    by_type = {}
    by_version_type = {}
    for pattern in all_patterns:
        ptype = pattern.get('migration_type', 'unknown')
        by_type[ptype] = by_type.get(ptype, 0) + 1
        
        version = pattern.get('helidon_version', '')
        if '-' in version:
            by_version_type['range'] = by_version_type.get('range', 0) + 1
        else:
            by_version_type['individual'] = by_version_type.get('individual', 0) + 1
    
    print(f"   Patterns by type:")
    for ptype, count in sorted(by_type.items()):
        print(f"      - {ptype}: {count}")
    
    print(f"   Patterns by version format:")
    print(f"      - Version range (code patterns): {by_version_type.get('range', 0)}")
    print(f"      - Individual versions (dependencies): {by_version_type.get('individual', 0)}")
    print()
    
    # Test 4: Verify version compatibility
    print("[Test 4] Testing version compatibility logic...")
    settings = Settings()
    settings.helidon_version = "4.3.2"
    agent = DependencyAgent(settings)
    
    test_cases = [
        ("4.0.0-4.3.2", "4.3.2", True, "Range contains target"),
        ("4.0.0-4.3.2", "4.0.0", True, "Range contains min"),
        ("4.0.0-4.3.2", "4.1.5", True, "Range contains middle"),
        ("4.0.0-4.3.2", "3.9.0", False, "Range doesn't contain older"),
        ("4.3.2", "4.3.2", True, "Exact match"),
        ("4.3.0", "4.3.2", True, "Same major.minor"),
    ]
    
    all_passed = True
    for pattern_ver, target_ver, expected, desc in test_cases:
        result = agent._is_version_compatible(pattern_ver, target_ver)
        status = "✅" if result == expected else "❌"
        if result != expected:
            all_passed = False
        print(f"   {status} {desc}: '{pattern_ver}' vs '{target_ver}' = {result} (expected {expected})")
    
    print()
    
    # Summary
    print("=" * 80)
    if all_passed:
        print("✅ All tests passed! Optimization is working correctly.")
    else:
        print("❌ Some tests failed. Please check the output above.")
    print("=" * 80)
    
    return all_passed

if __name__ == '__main__':
    try:
        success = test_pattern_generation()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

