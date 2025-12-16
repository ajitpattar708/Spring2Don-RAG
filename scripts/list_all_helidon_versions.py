#!/usr/bin/env python3
"""
List all supported Helidon 4.x versions
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.dataset.production_dataset_generator import ProductionDatasetGenerator

generator = ProductionDatasetGenerator()
print("=" * 70)
print("All Supported Helidon 4.x Versions (4.0.0 to 4.3.2)")
print("=" * 70)
print(f"\nTotal versions: {len(generator.helidon_versions)}\n")

# Group by major.minor
versions_by_minor = {}
for version in generator.helidon_versions:
    major_minor = '.'.join(version.split('.')[:2])
    if major_minor not in versions_by_minor:
        versions_by_minor[major_minor] = []
    versions_by_minor[major_minor].append(version)

for minor in sorted(versions_by_minor.keys()):
    versions = sorted(versions_by_minor[minor])
    print(f"{minor}.x series ({len(versions)} versions):")
    for v in versions:
        print(f"  - {v}")
    print()

print("=" * 70)
print(f"✅ All {len(generator.helidon_versions)} Helidon 4.x versions are supported!")
print("=" * 70)

