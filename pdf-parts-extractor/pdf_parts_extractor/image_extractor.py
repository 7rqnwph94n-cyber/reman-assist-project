"""
Image extraction from PDF documents.
CRITICAL: Extracts section header images for use as section headers in the wizard.
"""
import os
from typing import List, Dict, Optional, Tuple
from PIL import Image
import io


class ExtractedImage:
    """Represents an extracted image with metadata."""

    def __init__(
        self,
        image: Image.Image,
        page_num: int,
        section_id: str,
        bbox: Tuple[float, float, float, float],
        position: str = "header",
    ):
        self.image = image
        self.page_num = page_num
        self.section_id = section_id
        self.bbox = bbox  # (x0, y0, x1, y1)
        self.position = position  # 'header', 'inline', etc.

    def get_filename(self, ext: str = "png") -> str:
        """
        Generate filename following pattern expected by wizard:
        {section_id}_diagram_p{page_num}.{ext}
        """
        return f"{self.section_id}_diagram_p{self.page_num}.{ext}"

    def save(self, output_dir: str, ext: str = "png") -> str:
        """
        Save image to output directory.

        Args:
            output_dir: Directory to save images (typically output/images/)
            ext: Image format extension

        Returns:
            Relative path to saved image
        """
        os.makedirs(output_dir, exist_ok=True)
        filename = self.get_filename(ext)
        filepath = os.path.join(output_dir, filename)

        # Convert CMYK to RGB if needed
        if self.image.mode == "CMYK":
            self.image = self.image.convert("RGB")

        self.image.save(filepath, format=ext.upper())
        return filename


def extract_images(pdf, sections: List, profile: Dict, debug: bool = False) -> List[ExtractedImage]:
    """
    Extract section header images from PDF.

    This is the CRITICAL function - extracts images to be used as section headers.

    Args:
        pdf: pdfplumber PDF object
        sections: List of Section objects from section_detector
        profile: Profile dict with image_extraction config
        debug: Enable debug output

    Returns:
        List of ExtractedImage objects
    """
    image_config = profile.get("image_extraction", {})
    min_width = image_config.get("min_width", 200)
    min_height = image_config.get("min_height", 200)
    mode = image_config.get("mode", "section_header")

    extracted = []

    if mode == "section_header":
        # Extract one primary image per section (the section header diagram)
        for section in sections:
            section_images = _extract_section_header_images(
                pdf, section, min_width, min_height, debug
            )
            extracted.extend(section_images)
    else:
        # Extract all images on all pages
        for page_num, page in enumerate(pdf.pages):
            # Find which section this page belongs to
            from .section_detector import find_section_for_page

            section = find_section_for_page(sections, page_num)
            if not section:
                continue

            page_images = _extract_images_from_page(
                page, page_num, section.section_id, min_width, min_height
            )
            extracted.extend(page_images)

    if debug:
        print(f"Extracted {len(extracted)} images total")

    return extracted


def _extract_section_header_images(
    pdf, section, min_width: int, min_height: int, debug: bool = False
) -> List[ExtractedImage]:
    """
    Extract the primary header image for a section.
    This is typically the diagram that appears above the parts table.
    """
    extracted = []

    # Get the section's starting page
    page = pdf.pages[section.page_num]

    # Extract all images from the first page of the section
    images = _extract_images_from_page(
        page, section.page_num, section.section_id, min_width, min_height
    )

    if not images:
        if debug:
            print(f"  No images found for section {section.section_id}")
        return []

    # For section header mode, take the largest image on the first page
    # (usually the diagram is the largest image)
    images.sort(key=lambda img: img.image.width * img.image.height, reverse=True)
    primary_image = images[0]
    primary_image.position = "header"

    if debug:
        print(
            f"  Section {section.section_id}: Using {primary_image.image.width}x{primary_image.image.height} image as header"
        )

    return [primary_image]


def _extract_images_from_page(
    page, page_num: int, section_id: str, min_width: int, min_height: int
) -> List[ExtractedImage]:
    """
    Extract all images from a single page.

    Args:
        page: pdfplumber page object
        page_num: Page number (0-indexed)
        section_id: Section ID for filename generation
        min_width: Minimum image width to extract
        min_height: Minimum image height to extract

    Returns:
        List of ExtractedImage objects
    """
    extracted = []

    # pdfplumber provides images via .images attribute
    for img_obj in page.images:
        try:
            # Get image dimensions
            x0, y0, x1, y1 = img_obj["x0"], img_obj["top"], img_obj["x1"], img_obj["bottom"]
            width = x1 - x0
            height = y1 - y0

            # Filter by size
            if width < min_width or height < min_height:
                continue

            # Extract the image data
            # pdfplumber uses pdfminer under the hood
            # We need to extract the actual image from the PDF
            image = _extract_image_from_obj(page, img_obj)
            if image is None:
                continue

            extracted_img = ExtractedImage(
                image=image,
                page_num=page_num,
                section_id=section_id,
                bbox=(x0, y0, x1, y1),
            )
            extracted.append(extracted_img)

        except Exception as e:
            # Skip problematic images
            continue

    return extracted


def _extract_image_from_obj(page, img_obj) -> Optional[Image.Image]:
    """
    Extract PIL Image from pdfplumber image object.
    """
    try:
        # Crop the image from the page
        # pdfplumber can crop regions and render them
        bbox = (img_obj["x0"], img_obj["top"], img_obj["x1"], img_obj["bottom"])

        # Get the page as an image and crop to bbox
        page_image = page.to_image(resolution=150)
        cropped = page_image.original.crop(
            (
                bbox[0] * page_image.original.width / page.width,
                bbox[1] * page_image.original.height / page.height,
                bbox[2] * page_image.original.width / page.width,
                bbox[3] * page_image.original.height / page.height,
            )
        )

        return cropped

    except Exception:
        return None


def save_all_images(images: List[ExtractedImage], output_dir: str, debug: bool = False) -> List[str]:
    """
    Save all extracted images to output directory.

    Args:
        images: List of ExtractedImage objects
        output_dir: Base output directory (images will be saved to output_dir/images/)
        debug: Enable debug output

    Returns:
        List of saved filenames
    """
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    saved_files = []

    for img in images:
        try:
            filename = img.save(images_dir, ext="png")
            saved_files.append(filename)
            if debug:
                print(f"  Saved: {filename}")
        except Exception as e:
            if debug:
                print(f"  Failed to save {img.get_filename()}: {e}")

    return saved_files
# End of image extractor module.
