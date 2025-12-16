import shutil
import os
from pathlib import Path
import zipfile

def package_db():
    source_dir = Path("migration_db")
    output_filename = "knowledge_base"
    
    if not source_dir.exists():
        print("Error: migration_db directory not found. Please run 'init' first.")
        return

    print(f"Packaging {source_dir} into {output_filename}.zip...")
    
    # Create zip file
    shutil.make_archive(output_filename, 'zip', source_dir)
    
    zip_path = Path(f"{output_filename}.zip")
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    
    print(f"✅ Success! Created {zip_path}")
    print(f"📦 Size: {size_mb:.2f} MB")
    print("\nINSTRUCTIONS:")
    print("1. Upload 'knowledge_base.zip' to GitHub Releases or share securely.")
    print("2. Users should unzip this into the 'migration_db' folder.")
    print("3. Users do NOT need to run 'init' or have the dataset.json.")

if __name__ == "__main__":
    package_db()
