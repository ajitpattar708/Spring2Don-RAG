#!/usr/bin/env python3
"""Test JDK options for production"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.version_compatibility import VersionCompatibility

info = VersionCompatibility.get_version_info('4.3.2')
print("=" * 70)
print("Helidon 4.3.2 JDK Options for Production")
print("=" * 70)
print(f"Required (minimum):    Java {info['required_jdk']}+")
print(f"Production (LTS):     Java {info['production_jdk']} ✅ RECOMMENDED")
print(f"Performance (non-LTS): Java {info.get('recommended_jdk', 'N/A')}")
print()
print("💡 Recommendation: Use Java 21 (LTS) for production stability")
print("   Consider Java 25 only for performance-critical applications")
print("=" * 70)

