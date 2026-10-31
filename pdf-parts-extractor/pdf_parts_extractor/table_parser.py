"""
Table parsing from PDF documents.
Extracts parts data into structured format.
"""
import re
from typing import List, Dict, Optional, Any
import pandas as pd


def extract_tables(pdf, sections: List, profile: Dict, debug: bool = False) -> pd.DataFrame:
    """
    Extract parts tables from PDF based on profile rules.

    Args:
        pdf: pdfplumber PDF object
        sections: List of Section objects from section_detector
        profile: Profile dict with table_structure config
        debug: Enable debug output

    Returns:
        DataFrame with columns: section, pos, part_no, name, qty
    """
    table_config = profile.get("table_structure", {})
    column_defs = table_config.get("columns", [])

    all_rows = []

    for section in sections:
        if debug:
            print(f"\nProcessing section: {section.section_id} ({section.title})")

        # Get all pages for this section
        from .section_detector import get_section_pages

        section_pages = get_section_pages(section, pdf)

        for page in section_pages:
            # Extract tables from page
            tables = page.extract_tables()

            if not tables:
                continue

            for table in tables:
                if not table or len(table) < 2:  # Need header + at least one row
                    continue

                # Parse table with column mapping
                parsed_rows = _parse_table(
                    table, section.section_id, column_defs, debug
                )
                all_rows.extend(parsed_rows)

    # Convert to DataFrame
    if not all_rows:
        # Return empty DataFrame with required columns
        return pd.DataFrame(columns=["section", "pos", "part_no", "name", "qty"])

    df = pd.DataFrame(all_rows)

    # Ensure required columns exist
    required_cols = ["section", "pos", "part_no", "name", "qty"]
    for col in required_cols:
        if col not in df.columns:
            df[col] = ""

    # Reorder and select only required columns
    df = df[required_cols]

    # Clean up data
    df = _clean_dataframe(df)

    if debug:
        print(f"\nExtracted {len(df)} total rows")

    return df


def _parse_table(
    table: List[List[str]], section_id: str, column_defs: List[Dict], debug: bool = False
) -> List[Dict]:
    """
    Parse a single table into structured rows.

    Args:
        table: 2D list of table cells (rows x columns)
        section_id: Section ID to assign to rows
        column_defs: Column definitions from profile
        debug: Enable debug output

    Returns:
        List of row dicts with standardized column names
    """
    if not table or len(table) < 2:
        return []

    # First row is usually the header
    header = table[0]
    data_rows = table[1:]

    # Map header columns to standard names
    column_map = _map_columns(header, column_defs, debug)

    if not column_map:
        if debug:
            print(f"  Could not map columns for header: {header}")
        return []

    # Parse each data row
    parsed_rows = []

    for row in data_rows:
        if not row or all(cell is None or str(cell).strip() == "" for cell in row):
            continue  # Skip empty rows

        parsed_row = {"section": section_id}

        # Map columns
        for col_idx, col_name in column_map.items():
            if col_idx < len(row):
                value = row[col_idx]
                if value is not None:
                    parsed_row[col_name] = str(value).strip()

        # Only include rows with at least a part number or position
        if parsed_row.get("part_no") or parsed_row.get("pos"):
            parsed_rows.append(parsed_row)

    return parsed_rows


def _map_columns(header: List[str], column_defs: List[Dict], debug: bool = False) -> Dict[int, str]:
    """
    Map header columns to standard column names.

    Args:
        header: List of header cell values
        column_defs: Column definitions from profile
        debug: Enable debug output

    Returns:
        Dict mapping column index -> standard column name
    """
    column_map = {}

    for idx, cell in enumerate(header):
        if cell is None:
            continue

        cell_text = str(cell).strip().lower()

        # Try to match with column definitions
        for col_def in column_defs:
            col_name = col_def["name"]
            aliases = [a.lower() for a in col_def.get("aliases", [])]

            # Check if cell matches any alias
            if cell_text in aliases or any(alias in cell_text for alias in aliases):
                column_map[idx] = col_name
                break

    if debug and column_map:
        print(f"  Mapped columns: {column_map}")

    return column_map


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean and normalize the extracted DataFrame.

    Args:
        df: Raw DataFrame

    Returns:
        Cleaned DataFrame
    """
    # Remove rows with no part number
    df = df[df["part_no"].notna() & (df["part_no"] != "")]

    # Clean part numbers (remove extra spaces, special chars)
    df["part_no"] = df["part_no"].apply(_clean_part_number)

    # Clean quantities
    df["qty"] = df["qty"].apply(_clean_quantity)

    # Clean positions
    df["pos"] = df["pos"].apply(_clean_position)

    # Trim all string columns
    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].str.strip()

    # Remove duplicate rows
    df = df.drop_duplicates()

    # Reset index
    df = df.reset_index(drop=True)

    return df


def _clean_part_number(part_no: Any) -> str:
    """Clean and normalize part number."""
    if pd.isna(part_no):
        return ""

    part_no = str(part_no).strip()

    # Remove common noise
    part_no = part_no.replace("\n", " ")
    part_no = re.sub(r"\s+", " ", part_no)  # Collapse whitespace

    return part_no


def _clean_quantity(qty: Any) -> str:
    """Clean and normalize quantity."""
    if pd.isna(qty):
        return "1"

    qty_str = str(qty).strip()

    # Extract just the number
    match = re.search(r"(\d+)", qty_str)
    if match:
        return match.group(1)

    return qty_str if qty_str else "1"


def _clean_position(pos: Any) -> str:
    """Clean and normalize position/item number."""
    if pd.isna(pos):
        return ""

    pos = str(pos).strip()

    # Remove common prefixes
    pos = re.sub(r"^(pos|item|ref)[\s:]*", "", pos, flags=re.IGNORECASE)

    return pos


def save_csv(df: pd.DataFrame, output_path: str) -> None:
    """
    Save DataFrame to CSV in the expected format.

    Args:
        df: DataFrame with parts data
        output_path: Path to save CSV file
    """
    # Ensure we have the required columns in the right order
    required_cols = ["section", "pos", "part_no", "name", "qty"]
    df_output = df[required_cols].copy()

    # Save to CSV
    df_output.to_csv(output_path, index=False, encoding="utf-8")
# End of table parser module.
