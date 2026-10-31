"""
Profile management for PDF parts extraction.
Profiles define manufacturer-specific parsing rules.
"""
import os
import json
from typing import List, Dict, Optional


def get_profiles_dir() -> str:
    """
    Get the profiles directory from environment or use default.
    Returns absolute path to profiles directory.
    """
    profiles_dir = os.environ.get("PDF_EXTRACTOR_PROFILES_DIR")

    if profiles_dir:
        return os.path.abspath(profiles_dir)

    # Default: profiles/ directory next to this module
    module_dir = os.path.dirname(os.path.abspath(__file__))
    package_dir = os.path.dirname(module_dir)
    return os.path.join(package_dir, "profiles")


def list_profiles() -> List[str]:
    """
    List all available profile names.
    Expected by wizard code in templates/routes.py line 897.

    Returns:
        List of profile paths (absolute paths to .json files)
    """
    profiles_dir = get_profiles_dir()

    if not os.path.isdir(profiles_dir):
        return []

    profiles = []
    for fname in os.listdir(profiles_dir):
        if fname.endswith(".json"):
            full_path = os.path.join(profiles_dir, fname)
            profiles.append(full_path)

    return sorted(profiles)


def load_profile(profile_name: str) -> Optional[Dict]:
    """
    Load a profile by name or path.

    Args:
        profile_name: Profile name (e.g., "caterpillar") or full path

    Returns:
        Profile dict or None if not found
    """
    profiles_dir = get_profiles_dir()

    # If it's already a path, use it directly
    if os.path.isfile(profile_name) and profile_name.endswith(".json"):
        profile_path = profile_name
    else:
        # Try to find by name
        if not profile_name.endswith(".json"):
            profile_name = f"{profile_name}.json"
        profile_path = os.path.join(profiles_dir, profile_name)

    if not os.path.isfile(profile_path):
        return None

    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def detect_profile(pdf_path: str) -> Optional[str]:
    """
    Auto-detect the best profile for a PDF based on content analysis.

    Args:
        pdf_path: Path to PDF file

    Returns:
        Profile name (without .json) or None if no match
    """
    import pdfplumber

    # Read first few pages to detect format
    try:
        with pdfplumber.open(pdf_path) as pdf:
            sample_pages = pdf.pages[:3]  # Check first 3 pages
            sample_text = "\n".join(page.extract_text() or "" for page in sample_pages)
    except Exception:
        return None

    # Score each profile
    profiles_list = list_profiles()
    best_profile = None
    best_score = 0

    for profile_path in profiles_list:
        profile = load_profile(profile_path)
        if not profile:
            continue

        score = 0
        detection = profile.get("detection", {})

        # Check keywords
        keywords = detection.get("keywords", [])
        for keyword in keywords:
            if keyword.upper() in sample_text.upper():
                score += 10

        # Check patterns
        import re
        patterns = detection.get("patterns", [])
        for pattern in patterns:
            if re.search(pattern, sample_text, re.MULTILINE):
                score += 15

        if score > best_score:
            best_score = score
            # Extract profile name from path (e.g., "caterpillar" from "caterpillar.json")
            profile_name = os.path.basename(profile_path).replace(".json", "")
            best_profile = profile_name

    return best_profile if best_score > 0 else None


def get_profile_display_name(profile_path: str) -> str:
    """
    Get a human-readable display name for a profile.

    Args:
        profile_path: Path to profile JSON file

    Returns:
        Display name (e.g., "Caterpillar")
    """
    profile = load_profile(profile_path)
    if profile and "name" in profile:
        return profile["name"]

    # Fallback: filename without extension, title case
    basename = os.path.basename(profile_path)
    name = basename.replace(".json", "")
    return name.replace("_", " ").title()
# End of profiles module.
