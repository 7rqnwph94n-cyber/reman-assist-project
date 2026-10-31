import numpy as np
from PIL import Image


def _crop_diagram_area(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    arr = np.array(gray)
    height, width = arr.shape
    if height == 0 or width == 0:
        return image

    content = arr < 245
    row_counts = content.sum(axis=1)

    min_row_content = max(5, int(width * 0.003))
    rows = np.where(row_counts > min_row_content)[0]
    if rows.size == 0:
        return image

    first_row = int(rows[0])
    last_row = int(rows[-1])

    gap_min = int(height * 0.05)
    top_block_end = None
    prev = first_row
    for r in rows[1:]:
        if r - prev >= gap_min:
            top_block_end = prev
            break
        prev = r

    if top_block_end and (top_block_end - first_row) >= int(height * 0.15):
        crop_top = first_row
        crop_bottom = top_block_end
    else:
        crop_top = first_row
        crop_bottom = last_row

    cropped = arr[crop_top:crop_bottom + 1, :]
    if cropped.size == 0:
        return image

    col_counts = (cropped < 245).sum(axis=0)
    min_col_content = max(5, int((crop_bottom - crop_top + 1) * 0.003))
    cols = np.where(col_counts > min_col_content)[0]
    if cols.size == 0:
        return image

    left = int(cols[0])
    right = int(cols[-1])

    pad = 8
    left = max(0, left - pad)
    right = min(width - 1, right + pad)
    crop_top = max(0, crop_top - pad)
    crop_bottom = min(height - 1, crop_bottom + pad)

    return image.crop((left, crop_top, right + 1, crop_bottom + 1))


def render_cropped_page(pdf_page, zoom: float = 2.0):
    import fitz  # type: ignore

    pix = pdf_page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    cropped = _crop_diagram_area(img)
    return cropped, cropped.width, cropped.height
