#!/usr/bin/env python3
"""
Test Version Compatibility
Tests JDK requirements for all Helidon versions
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.version_compatibility import VersionCompatibility


def test_all_versions():
    """Test JDK requirements for all Helidon 4.x versions"""
    
    print("=" * 80)
    print("Helidon Version JDK Compatibility Test")
    print("=" * 80)
    print()
    
    # Test all Helidon 4.x versions
    test_versions = [
        "4.0.0", "4.0.1", "4.0.2",
        "4.1.0", "4.1.1", "4.1.2", "4.1.3", "4.1.4", "4.1.5",
        "4.2.0", "4.2.1", "4.2.2", "4.2.3",
        "4.3.0", "4.3.1", "4.3.2"
    ]
    
    print("Helidon 4.x JDK Requirements:")
    print("-" * 80)
    print(f"{'Version':<12} {'Required JDK':<15} {'Recommended JDK':<18} {'Maven':<12}")
    print("-" * 80)
    
    for version in test_versions:
        info = VersionCompatibility.get_version_info(version)
        required_jdk = info['required_jdk']
        recommended_jdk = info.get('recommended_jdk', '-')
        required_maven = info['required_maven']
        
        print(f"{version:<12} {required_jdk + '+':<15} {str(recommended_jdk):<18} {required_maven + '+':<12}")
    
    print("-" * 80)
    print()
    
    # Detailed test for 4.3.2
    print("Detailed Test for Helidon 4.3.2 (Latest):")
    print("-" * 80)
    info = VersionCompatibility.get_version_info("4.3.2")
    print(f"Version: {info['helidon_version']}")
    print(f"Required JDK: {info['required_jdk']}+")
    if 'recommended_jdk' in info:
        print(f"Recommended JDK: {info['recommended_jdk']} (for optimal performance)")
    print(f"Required Maven: {info['required_maven']}+")
    print(f"Jakarta EE: {info['jakarta_ee_version']}")
    print(f"MicroProfile: {info['microprofile_version']}")
    print()
    
    # Test version compatibility
    print("Version Compatibility Validation:")
    print("-" * 80)
    spring_version = "3.4.5"
    helidon_versions = ["4.0.0", "4.2.3", "4.3.2"]
    
    for helidon_version in helidon_versions:
        is_compatible, error_msg = VersionCompatibility.validate_compatibility(
            spring_version, helidon_version
        )
        status = "✅ Compatible" if is_compatible else "❌ Incompatible"
        print(f"Spring Boot {spring_version} → Helidon {helidon_version}: {status}")
        if error_msg:
            print(f"  ⚠️  {error_msg}")
    print()
    
    print("=" * 80)
    print("✅ All version compatibility checks completed!")
    print("=" * 80)


if __name__ == '__main__':
    test_all_versions()

