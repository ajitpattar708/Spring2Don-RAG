
import json
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_subset():
    project_root = Path(__file__).parent.parent
    full_dataset_path = project_root / 'migration_dataset_full.json'
    target_dataset_path = project_root / 'migration_dataset.json'
    
    TARGET_SIZE = 10000  # Target number of patterns
    
    if not full_dataset_path.exists():
        logger.error(f"Full dataset not found at {full_dataset_path}")
        return

    logger.info(f"Reading full dataset from {full_dataset_path}...")
    try:
        with open(full_dataset_path, 'r', encoding='utf-8') as f:
            full_data = json.load(f)
            
        total_count = len(full_data)
        logger.info(f"Full dataset contains {total_count} patterns.")
        
        if total_count <= TARGET_SIZE:
            logger.info(f"Total count {total_count} is less than or equal to target {TARGET_SIZE}. Using full dataset.")
            subset_data = full_data
        else:
            logger.info(f"Slicing first {TARGET_SIZE} patterns...")
            subset_data = full_data[:TARGET_SIZE]
            
        logger.info(f"Writing {len(subset_data)} patterns to {target_dataset_path}...")
        with open(target_dataset_path, 'w', encoding='utf-8') as f:
            json.dump(subset_data, f, indent=2)
            
        logger.info("Subset creation complete.")
        
    except Exception as e:
        logger.error(f"Error creating subset: {str(e)}")

if __name__ == '__main__':
    create_subset()
