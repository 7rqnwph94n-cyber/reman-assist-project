"""
Section detection in PDF documents.
Identifies section boundaries based on header patterns.
"""
import re
from typing import List, Dict, Optional, Tuple


class Section:
    """Represents a detected section in the PDF."""

    def __init__(self, section_id: str, title: str, page_num: int, y_position: float = 0):
        self.section_id = section_id  # e.g., "TA0101", "BASIC ENGINE"
        self.title = title  # Full header text
        self.page_num = page_num
        self.y_position = y_position  # Vertical position on page
        self.end_page = None  # Will be set when next section starts
        self.end_y = None

    def __repr__(self):
        return f"Section(id={self.section_id}, title={self.title}, page={self.page_num})"


def detect_sections(pdf, profile: Dict) -> List[Section]:
    """
    Detect all sections in a PDF based on profile rules.

    Args:
        pdf: pdfplumber PDF object
        profile: Profile dict with section_detection rules

    Returns:
        List of Section objects in document order
    """
    section_config = profile.get("section_detection", {})
    patterns = section_config.get("patterns", [])
    min_font_size = section_config.get("min_font_size", 10)

    sections = []

    for page_num, page in enumerate(pdf.pages):
        page_sections = _detect_sections_on_page(
            page, page_num, patterns, min_font_size
        )
        sections.extend(page_sections)

    # Set end boundaries for each section
    for i, section in enumerate(sections):
        if i + 1 < len(sections):
            next_section = sections[i + 1]
            section.end_page = next_section.page_num
            section.end_y = next_section.y_position
        else:
            # Last section goes to end of document
            section.end_page = len(pdf.pages) - 1
            section.end_y = 0

    return sections


def _detect_sections_on_page(
    page, page_num: int, patterns: List[str], min_font_size: float
) -> List[Section]:
    """Detect sections on a single page."""
    sections = []

    # Try to extract text with layout info
    text = page.extract_text() or ""
    lines = text.split("\n")

    # Also try to get char-level info for font detection
    chars = page.chars

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check if line matches any section pattern
        for pattern in patterns:
            match = re.match(pattern, line, re.MULTILINE)
            if match:
                # Extract section ID from the pattern
                section_id = _extract_section_id(line)

                # Check font size if we have char info
                if chars:
                    line_chars = [c for c in chars if c["text"] in line]
                    if line_chars:
                        avg_font_size = sum(c.get("size", 0) for c in line_chars) / len(
                            line_chars
                        )
                        if avg_font_size < min_font_size:
                            continue

                section = Section(
                    section_id=section_id, title=line, page_num=page_num
                )
                sections.append(section)
                break

    return sections


def _extract_section_id(header_text: str) -> str:
    """
    Extract a clean section ID from header text.

    Examples:
        "TA 0101 CYLINDERBLOCK" -> "TA0101"
        "BASIC ENGINE" -> "BASIC_ENGINE"
        "143-4118 CAMSHAFT AS" -> "143-4118"
        "D 0836 LE201 #003001000300 CRANKCASE" -> "D0836"
    """
    # Try to find common section ID patterns
    patterns = [
        r"(TA\s*\d{4})",  # Steyr: TA 0101
        r"(\d{3}-\d{4})",  # CAT: 143-4118
        r"(D\s*\d{4})",  # MAN: D 0836
        r"([A-Z]{2}\s*\d{4})",  # Kubota: AC 6047
    ]

    for pattern in patterns:
        match = re.search(pattern, header_text)
        if match:
            section_id = match.group(1).replace(" ", "")
            return section_id

    # Fallback: use first meaningful words, convert to ID format
    words = header_text.split()
    if words:
        # Take first 2-3 words, clean them
        id_words = []
        for word in words[:3]:
            # Remove special chars except alphanumeric and dash
            clean_word = re.sub(r"[^A-Za-z0-9-]", "", word)
            if clean_word:
                id_words.append(clean_word)
                if len("_".join(id_words)) > 15:
                    break

        if id_words:
            return "_".join(id_words).upper()

    # Last resort: hash of the text
    return f"SECTION_{abs(hash(header_text)) % 10000}"


def find_section_for_page(sections: List[Section], page_num: int) -> Optional[Section]:
    """
    Find which section a given page belongs to.

    Args:
        sections: List of detected sections
        page_num: Page number (0-indexed)

    Returns:
        Section object or None if no section found
    """
    for section in sections:
        if section.page_num <= page_num <= (section.end_page or float("inf")):
            return section
    return None


def get_section_pages(section: Section, pdf) -> List:
    """
    Get all pages belonging to a section.

    Args:
        section: Section object
        pdf: pdfplumber PDF object

    Returns:
        List of pdfplumber page objects
    """
    start = section.page_num
    end = section.end_page if section.end_page is not None else len(pdf.pages) - 1

    return pdf.pages[start : end + 1]
# End of section detector module.
