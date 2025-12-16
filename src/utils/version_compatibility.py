"""
Version Compatibility Module
Handles JDK, Maven, and framework version compatibility
"""

from typing import Dict, Optional, Tuple
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class VersionCompatibility:
    """Manages version compatibility for Spring Boot, Helidon, JDK, and Maven"""
    
    # Helidon version ranges to JDK mapping
    # ALL Helidon 4.x versions (4.0.0 to 4.3.2) require Java 21+ (Java 25 recommended)
    # Per official Helidon documentation: https://github.com/helidon-io/helidon/releases
    HELIDON_JDK_MATRIX = {
        # ALL Helidon 4.x series (4.0.0 to 4.3.2) - all require Java 21+ (Java 25 recommended)
        "4.0": "21",
        "4.1": "21",
        "4.2": "21",
        "4.3": "21",
        # Helidon 3.x series
        "3.0": "17",
        "3.1": "17",
        "3.2": "17",
        # Helidon 2.x series
        "2.0": "11",
        # Helidon 1.x series
        "1.0": "11",
    }
    
    # Recommended JDK versions (for optimal performance)
    # ALL Helidon 4.x versions recommend Java 25
    HELIDON_RECOMMENDED_JDK = {
        # All 4.0.x versions
        "4.0.0": "25", "4.0.1": "25", "4.0.2": "25",
        # All 4.1.x versions
        "4.1.0": "25", "4.1.1": "25", "4.1.2": "25", "4.1.3": "25", "4.1.4": "25", "4.1.5": "25", "4.1.6": "25",
        # All 4.2.x versions
        "4.2.0": "25", "4.2.1": "25", "4.2.2": "25", "4.2.3": "25", "4.2.4": "25", "4.2.7": "25",
        # All 4.3.x versions
        "4.3.0": "25", "4.3.1": "25", "4.3.2": "25",  # Java 25 recommended for all Helidon 4.x
    }
    
    # Helidon version to Maven version mapping
    # Helidon 4.3.2 requires Maven 3.8+ (per documentation)
    # Earlier 4.x versions may work with 3.6.0+, but 3.8.0+ is recommended
    HELIDON_MAVEN_MATRIX = {
        # All Helidon 4.x versions - Maven 3.8.0+ recommended (3.6.0+ minimum)
        "4.0": "3.8.0",  # 3.8.0+ recommended for all 4.x
        "4.1": "3.8.0",
        "4.2": "3.8.0",
        "4.3": "3.8.0",  # Helidon 4.3.2 requires Maven 3.8+ (per documentation)
        # Helidon 3.x
        "3.0": "3.6.0",
        "3.1": "3.6.0",
        "3.2": "3.6.0",
    }
    
    # Spring Boot to JDK mapping
    SPRING_JDK_MATRIX = {
        "3.4": "17",
        "3.3": "17",
        "3.2": "17",
        "3.1": "17",
        "3.0": "17",
        "2.7": "11",
        "2.6": "11",
    }
    
    # Helidon version to Jakarta EE version
    HELIDON_JAKARTA_MATRIX = {
        # All Helidon 4.x versions use Jakarta EE 10.0
        "4.0": "10.0",
        "4.1": "10.0",
        "4.2": "10.0",
        "4.3": "10.0",  # Jakarta EE version same, but JDK requirement is 21+
        # Helidon 3.x uses Jakarta EE 9.1
        "3.0": "9.1",
        "3.1": "9.1",
    }
    
    # Helidon version to MicroProfile version
    HELIDON_MP_MATRIX = {
        # All Helidon 4.x versions use MicroProfile 6.0
        "4.0": "6.0",
        "4.1": "6.0",
        "4.2": "6.0",
        "4.3": "6.0",  # MicroProfile version same, but JDK requirement is 21+
        # Helidon 3.x uses MicroProfile 5.0
        "3.0": "5.0",
        "3.1": "5.0",
    }
    
    # Supported Helidon 4.x version range
    HELIDON_4_MIN_VERSION = "4.0.0"
    HELIDON_4_MAX_VERSION = "4.3.2"
    
    # Helidon 4.x requires Java 21+ (minimum)
    # Java 21 (LTS) recommended for production stability
    # Java 25 recommended for optimal performance (non-LTS)
    HELIDON_4_MIN_JDK = "21"
    HELIDON_4_LTS_JDK = "21"  # LTS - recommended for production
    HELIDON_4_PERFORMANCE_JDK = "25"  # Non-LTS - for performance-critical apps
    
    @staticmethod
    def get_required_jdk(helidon_version: str) -> str:
        """
        Get required JDK version for Helidon version
        Checks each version individually for accurate JDK requirements
        
        Args:
            helidon_version: Helidon version (e.g., "4.0.0", "4.1.5", "4.3.2")
            
        Returns:
            Required JDK version (e.g., "17" or "21")
        """
        # First, check exact version match in matrix
        if helidon_version in VersionCompatibility.HELIDON_JDK_MATRIX:
            return VersionCompatibility.HELIDON_JDK_MATRIX[helidon_version]
        
        # Extract version parts
        version_parts = helidon_version.split('.')
        if len(version_parts) < 2:
            logger.warning(f"Invalid Helidon version format: {helidon_version}")
            return "17"  # Safe default
        
        major = int(version_parts[0])
        minor = int(version_parts[1])
        patch = int(version_parts[2]) if len(version_parts) > 2 else 0
        
        # Check if it's Helidon 4.x (4.0.0 to 4.3.2)
        if major == 4:
            # Validate version is within supported range
            if VersionCompatibility._is_version_in_range(
                helidon_version, 
                VersionCompatibility.HELIDON_4_MIN_VERSION,
                VersionCompatibility.HELIDON_4_MAX_VERSION
            ):
                # ALL Helidon 4.x versions require Java 21+ (Java 25 recommended)
                return "21"  # All Helidon 4.x versions require Java 21+
            else:
                logger.warning(f"Helidon version {helidon_version} is outside supported range (4.0.0-4.3.2)")
                # Default for Helidon 4.x
                return "21"
        
        # Check major.minor match in matrix
        major_minor = f"{major}.{minor}"
        if major_minor in VersionCompatibility.HELIDON_JDK_MATRIX:
            return VersionCompatibility.HELIDON_JDK_MATRIX[major_minor]
        
        # Default based on major version
        if major >= 4:
            # ALL Helidon 4.x versions require Java 21+ (Java 25 recommended)
            return "21"  # All Helidon 4.x versions require Java 21+
        elif major >= 3:
            return "17"  # Helidon 3.x requires JDK 17+
        else:
            return "11"  # Helidon 2.x and below require JDK 11+
    
    @staticmethod
    def get_recommended_jdk(helidon_version: str) -> Optional[str]:
        """
        Get recommended JDK version for Helidon version (for optimal performance)
        
        Args:
            helidon_version: Helidon version
            
        Returns:
            Recommended JDK version or None if not specified
        """
        # Check exact version match
        if helidon_version in VersionCompatibility.HELIDON_RECOMMENDED_JDK:
            return VersionCompatibility.HELIDON_RECOMMENDED_JDK[helidon_version]
        
        # ALL Helidon 4.x versions recommend Java 25
        version_parts = helidon_version.split('.')
        if len(version_parts) >= 2:
            major = int(version_parts[0])
            if major == 4:
                return "25"  # Java 25 recommended for all Helidon 4.x versions
        
        return None
    
    @staticmethod
    def get_production_jdk(helidon_version: str) -> str:
        """
        Get production-recommended JDK version (LTS for stability)
        For production, Java 21 (LTS) is recommended over Java 25 (non-LTS)
        
        Args:
            helidon_version: Helidon version
            
        Returns:
            Production-recommended JDK version (Java 21 LTS)
        """
        # Check if it's Helidon 4.x
        version_parts = helidon_version.split('.')
        if len(version_parts) >= 2:
            major = int(version_parts[0])
            if major == 4:
                return "21"  # Java 21 (LTS) recommended for production stability
        
        # Default to required JDK
        return VersionCompatibility.get_required_jdk(helidon_version)
    
    @staticmethod
    def _is_version_in_range(version: str, min_version: str, max_version: str) -> bool:
        """Check if version is within range"""
        try:
            version_parts = [int(x) for x in version.split('.')]
            min_parts = [int(x) for x in min_version.split('.')]
            max_parts = [int(x) for x in max_version.split('.')]
            
            # Compare version components
            for i in range(max(len(version_parts), len(min_parts), len(max_parts))):
                v = version_parts[i] if i < len(version_parts) else 0
                min_v = min_parts[i] if i < len(min_parts) else 0
                max_v = max_parts[i] if i < len(max_parts) else 0
                
                if v < min_v or v > max_v:
                    return False
                if v > min_v and v < max_v:
                    return True
            
            return True
        except:
            return True  # Default to True if parsing fails
    
    @staticmethod
    def get_required_maven(helidon_version: str) -> str:
        """
        Get required Maven version for Helidon version
        
        Args:
            helidon_version: Helidon version (e.g., "4.0.0", "4.1.5", "4.3.2")
            
        Returns:
            Required Maven version (e.g., "3.6.0")
        """
        # Extract major.minor version
        version_parts = helidon_version.split('.')
        major = int(version_parts[0])
        minor = int(version_parts[1]) if len(version_parts) > 1 else 0
        major_minor = f"{major}.{minor}"
        
        # Helidon 4.x versions - Maven 3.8.0+ recommended
        if major == 4:
            # All Helidon 4.x versions - Maven 3.8.0+ recommended (3.6.0+ minimum)
            return "3.8.0"
        
        # Check major.minor match in matrix
        if major_minor in VersionCompatibility.HELIDON_MAVEN_MATRIX:
            return VersionCompatibility.HELIDON_MAVEN_MATRIX[major_minor]
        
        # Default
        return "3.6.0"
    
    @staticmethod
    def get_jakarta_version(helidon_version: str) -> str:
        """Get Jakarta EE version for Helidon version"""
        version_parts = helidon_version.split('.')
        major = int(version_parts[0])
        minor = int(version_parts[1]) if len(version_parts) > 1 else 0
        major_minor = f"{major}.{minor}"
        
        # All Helidon 4.x versions use Jakarta EE 10.0
        if major == 4:
            return "10.0"
        
        # Check major.minor match in matrix
        if major_minor in VersionCompatibility.HELIDON_JAKARTA_MATRIX:
            return VersionCompatibility.HELIDON_JAKARTA_MATRIX[major_minor]
        
        # Default
        return "10.0" if major >= 4 else "9.1"
    
    @staticmethod
    def get_microprofile_version(helidon_version: str) -> str:
        """Get MicroProfile version for Helidon version"""
        version_parts = helidon_version.split('.')
        major = int(version_parts[0])
        minor = int(version_parts[1]) if len(version_parts) > 1 else 0
        major_minor = f"{major}.{minor}"
        
        # All Helidon 4.x versions use MicroProfile 6.0
        if major == 4:
            return "6.0"
        
        # Check major.minor match in matrix
        if major_minor in VersionCompatibility.HELIDON_MP_MATRIX:
            return VersionCompatibility.HELIDON_MP_MATRIX[major_minor]
        
        # Default
        return "6.0" if major >= 4 else "5.0"
    
    @staticmethod
    def validate_compatibility(spring_version: str, helidon_version: str) -> Tuple[bool, Optional[str]]:
        """
        Validate compatibility between Spring Boot and Helidon versions
        
        Args:
            spring_version: Spring Boot version
            helidon_version: Helidon version
            
        Returns:
            Tuple of (is_compatible, error_message)
        """
        # Extract major.minor for Spring Boot
        spring_parts = spring_version.split('.')
        spring_major_minor = f"{spring_parts[0]}.{spring_parts[1]}" if len(spring_parts) > 1 else spring_parts[0]
        spring_jdk = VersionCompatibility.SPRING_JDK_MATRIX.get(spring_major_minor, "17")
        
        helidon_jdk = VersionCompatibility.get_required_jdk(helidon_version)
        
        # Validate Helidon version is in supported range
        helidon_parts = helidon_version.split('.')
        helidon_major = int(helidon_parts[0])
        
        if helidon_major == 4:
            if not VersionCompatibility._is_version_in_range(
                helidon_version,
                VersionCompatibility.HELIDON_4_MIN_VERSION,
                VersionCompatibility.HELIDON_4_MAX_VERSION
            ):
                return False, f"Helidon version {helidon_version} is not in supported range ({VersionCompatibility.HELIDON_4_MIN_VERSION} to {VersionCompatibility.HELIDON_4_MAX_VERSION})"
        
        # Both should support the same JDK version
        spring_jdk_int = int(spring_jdk)
        helidon_jdk_int = int(helidon_jdk)
        
        if spring_jdk_int > helidon_jdk_int:
            return False, f"Spring Boot {spring_version} requires JDK {spring_jdk}, but Helidon {helidon_version} requires JDK {helidon_jdk}. Please use JDK {spring_jdk} or higher."
        
        return True, None
    
    @staticmethod
    def get_version_info(helidon_version: str) -> Dict[str, str]:
        """
        Get complete version information for Helidon version
        
        Args:
            helidon_version: Helidon version
            
        Returns:
            Dictionary with version information
        """
        required_jdk = VersionCompatibility.get_required_jdk(helidon_version)
        recommended_jdk = VersionCompatibility.get_recommended_jdk(helidon_version)  # For performance
        production_jdk = VersionCompatibility.get_production_jdk(helidon_version)  # LTS for production
        
        info = {
            "helidon_version": helidon_version,
            "required_jdk": required_jdk,
            "production_jdk": production_jdk,  # LTS version for production
            "required_maven": VersionCompatibility.get_required_maven(helidon_version),
            "jakarta_ee_version": VersionCompatibility.get_jakarta_version(helidon_version),
            "microprofile_version": VersionCompatibility.get_microprofile_version(helidon_version),
        }
        
        if recommended_jdk:
            info["recommended_jdk"] = recommended_jdk  # For performance (non-LTS)
        
        return info

