"""
Detects and strips near-blank pages before OCR runs.
Doing this pre-OCR saves the Pi from wasting cycles OCR'ing empty pages,
and shrinks the final file since there's nothing to compress on those pages.

Method: render each page at low DPI, measure the fraction of near-white
pixels. Real-estate scans are almost always plain white paper, so a simple
threshold works reliably without needing a trained model.
"""
import fitz  # PyMuPDF
import pikepdf
import logging

logger = logging.getLogger(__name__)


def _page_is_blank(page: "fitz.Page", threshold: float) -> bool:
    # Render small — we only need a coverage estimate, not detail. Keeps this
    # fast on the Pi's CPU even for a 20-page document.
    pix = page.get_pixmap(dpi=72, colorspace=fitz.csGRAY)
    samples = pix.samples  # raw bytes, one per pixel (grayscale)
    total = len(samples)
    if total == 0:
        return True
    white_count = sum(1 for b in samples if b > 250)
    white_fraction = white_count / total
    return white_fraction >= threshold


def strip_blank_pages(input_path: str, output_path: str, threshold: float = 0.995) -> tuple[int, int]:
    """
    Returns (pages_kept, pages_removed).
    Writes a new PDF to output_path with blank pages removed.
    If ALL pages are judged blank (e.g. mis-scan), keeps the original
    untouched rather than producing an empty file.
    """
    doc = fitz.open(input_path)
    blank_indices = []
    for i, page in enumerate(doc):
        if _page_is_blank(page, threshold):
            blank_indices.append(i)
    doc.close()

    total_pages = _page_count(input_path)

    if len(blank_indices) == total_pages:
        logger.warning("All pages flagged blank for %s — keeping original, likely a bad scan", input_path)
        _copy(input_path, output_path)
        return total_pages, 0

    if not blank_indices:
        _copy(input_path, output_path)
        return total_pages, 0

    with pikepdf.open(input_path) as pdf:
        # delete from the end so earlier indices don't shift
        for idx in sorted(blank_indices, reverse=True):
            del pdf.pages[idx]
        pdf.save(output_path)

    kept = total_pages - len(blank_indices)
    return kept, len(blank_indices)


def _page_count(path: str) -> int:
    doc = fitz.open(path)
    n = doc.page_count
    doc.close()
    return n


def _copy(src: str, dst: str):
    import shutil
    shutil.copyfile(src, dst)
