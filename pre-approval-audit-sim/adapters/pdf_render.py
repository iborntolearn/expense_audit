"""Render a PDF receipt's first page to PNG bytes for vision-LLM calls.

Vision chat-completions APIs (both Claude's image content block and Azure
OpenAI's image_url) accept only raster image formats (png/jpeg/gif/webp) - never
raw PDF bytes. A `scanned_pdf`-format synthetic receipt (generator/receipts.py)
is a genuine PDF, so it must be rasterised before being sent, exactly like a
real scanned document would need to be. Uses pdfplumber (same choice as the SOA
Layout Agent app's pdf_render.py) - no external system binary (e.g. poppler)
required.
"""
from __future__ import annotations

import io


def pdf_first_page_to_png(pdf_bytes: bytes, dpi: int = 150) -> bytes:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        img = page.to_image(resolution=dpi).original.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def is_pdf(data: bytes) -> bool:
    """Detect by magic bytes rather than trusting the URL's extension."""
    return data[:5] == b"%PDF-"
