"""
Main extraction entry point for PDF parts catalogs.
Produces parts.csv and section header images.
"""
import os
from typing import Optional

import pdfplumber

from .profiles import detect_profile, load_profile
from .section_detector import detect_sections
from .table_parser import extract_tables, save_csv
from .image_extractor import extract_images, save_all_images


def run_extract(
    pdf_path: str,
    output_dir: str,
    profile_name: str = "auto",
    debug: bool = False,
) -> None:
    """
    Extract parts tables and section header images from a PDF.

    Args:
        pdf_path: Path to input PDF
        output_dir: Directory to write outputs (parts.csv and images/)
        profile_name: Profile name or "auto" to detect
        debug: Enable debug logging
    """
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    os.makedirs(output_dir, exist_ok=True)

    if profile_name == "auto":
        detected = detect_profile(pdf_path)
        if not detected:
            raise ValueError("Unable to auto-detect profile for PDF")
        profile_name = detected

    profile = load_profile(profile_name)
    if not profile:
        raise ValueError(f"Profile not found: {profile_name}")

    if debug:
        print(f"Using profile: {profile.get('name', profile_name)}")

    with pdfplumber.open(pdf_path) as pdf:
        sections = detect_sections(pdf, profile)
        if debug:
            print(f"Detected {len(sections)} sections")

        df = extract_tables(pdf, sections, profile, debug=debug)
        parts_csv_path = os.path.join(output_dir, "parts.csv")
        save_csv(df, parts_csv_path)
        if debug:
            print(f"Saved parts CSV: {parts_csv_path}")

        images = extract_images(pdf, sections, profile, debug=debug)
        save_all_images(images, output_dir, debug=debug)


def main() -> None:
    """CLI entry point for manual runs."""
    import argparse

    parser = argparse.ArgumentParser(description="PDF parts extractor")
    parser.add_argument("pdf_path", help="Path to input PDF")
    parser.add_argument("output_dir", help="Output directory")
    parser.add_argument(
        "--profile",
        default="auto",
        help="Profile name or 'auto' to detect",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    run_extract(args.pdf_path, args.output_dir, args.profile, debug=args.debug)


if __name__ == "__main__":
    main()