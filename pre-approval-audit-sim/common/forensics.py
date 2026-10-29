"""Real (non-simulated) receipt forensics - image metadata, PDF metadata, and
JPEG Error-Level-Analysis (ELA) for structural/paste-anomaly detection.

Unlike `pipeline/agents/verification.py::VerificationAgent._authenticity()`
(which only ever reads a `.sim.json` test sidecar), everything here operates
on REAL bytes - a real uploaded photo, screenshot, or PDF - using only
Pillow and pdfplumber (both already project dependencies; no new library).

Deliberately pure functions: no BlobStore, no config object, just bytes in
and flag strings out, so this is trivially unit-testable with hand-built
fixtures. Every function degrades to `[]` on anything it can't parse or
doesn't apply to (corrupt bytes, non-JPEG for ELA, etc.) rather than raising -
"can't assess" is not itself a fraud signal here (see the open question in
the plan about whether that should change).
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from PIL import ExifTags, Image

# Image-editing tools that have no business touching a genuine, unedited
# receipt photo/scan. Deliberately excludes ordinary document producers
# (Word, LibreOffice, Chrome's print-to-PDF, Acrobat) - those are common and
# legitimate for a real invoice PDF; the tools below are photo/image editors.
_EDITING_SOFTWARE_MARKERS = (
    "photoshop", "gimp", "canva", "snapseed", "affinity photo", "lightroom",
)

# Weak signal: some AI image generators embed these as PNG text chunks -
# trivially stripped by anyone who bothers, so this alone should never carry
# much weight (see RiskAgent's STRONG_FORENSICS_FLAGS split).
_AI_GENERATOR_MARKERS = (
    "stable diffusion", "midjourney", "dall-e", "dalle", "comfyui",
    "steps:", "cfg scale", "sampler:",
)


def _parse_exif_datetime(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _parse_pdf_date(value) -> Optional[datetime]:
    """PDF trailer dates look like `D:20260722153000+05'00'` (or without the
    `D:` prefix). Only the leading YYYYMMDDHHMMSS digits are needed here."""
    if not value:
        return None
    s = str(value)
    if s.startswith("D:"):
        s = s[2:]
    digits = "".join(ch for ch in s[:14] if ch.isdigit())
    if len(digits) < 8:
        return None
    digits = digits.ljust(14, "0")
    try:
        return datetime.strptime(digits, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def analyze_image_metadata(data: bytes, *, expected_format_hint: Optional[str] = None) -> list[str]:
    """EXIF (JPEG) / text-chunk (PNG) analysis.

    `expected_format_hint` is the line's declared receipt format
    ("photo" | "scanned_pdf" | "e_receipt") - `missing_exif_camera_data` only
    ever fires for `"photo"`. An e-receipt or a phone screenshot legitimately
    has no camera Make/Model EXIF and must never be penalised for it."""
    try:
        img = Image.open(io.BytesIO(data))
    except Exception:
        return []

    flags: set[str] = set()
    fmt = (img.format or "").upper()

    if fmt in ("JPEG", "TIFF"):
        exif = img.getexif()
        tags = {ExifTags.TAGS.get(tag_id, tag_id): value for tag_id, value in exif.items()}

        software = str(tags.get("Software", "")).lower()
        if any(marker in software for marker in _EDITING_SOFTWARE_MARKERS):
            flags.add("editing_software_signature")

        if not (tags.get("Make") or tags.get("Model")) and expected_format_hint == "photo":
            flags.add("missing_exif_camera_data")

        modified = _parse_exif_datetime(tags.get("DateTime"))
        original = _parse_exif_datetime(tags.get("DateTimeOriginal"))
        if modified and original and (modified - original) > timedelta(minutes=5):
            flags.add("modify_after_create_mismatch")

    elif fmt == "PNG":
        # PNGs (incl. phone screenshots) have no camera-EXIF convention at
        # all - never flag missing camera data here, only look for AI-
        # generator provenance chunks some tools embed.
        info_text = " ".join(str(v).lower() for v in img.info.values())
        if any(marker in info_text for marker in _AI_GENERATOR_MARKERS):
            flags.add("ai_generator_metadata_signature")

    return sorted(flags)


def analyze_pdf_metadata(data: bytes) -> list[str]:
    """PDF trailer `/Info` dict (Creator/Producer/CreationDate/ModDate) via
    pdfplumber - same library already used for PDF rasterisation
    (`adapters/pdf_render.py`)."""
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            meta = pdf.metadata or {}
    except Exception:
        return []

    flags: set[str] = set()
    combined = f"{meta.get('Creator', '')} {meta.get('Producer', '')}".lower()
    if any(marker in combined for marker in _EDITING_SOFTWARE_MARKERS):
        flags.add("editing_software_signature")

    created = _parse_pdf_date(meta.get("CreationDate"))
    modified = _parse_pdf_date(meta.get("ModDate"))
    if created and modified and (modified - created) > timedelta(minutes=5):
        flags.add("modify_after_create_mismatch")

    return sorted(flags)


def error_level_analysis(
    data: bytes, *, quality: int = 90, diff_threshold: int = 40,
    region_frac_threshold: float = 0.02, block_size: int = 16,
) -> list[str]:
    """JPEG-only structural-anomaly check. Recompresses in-memory at
    `quality`, diffs against the original per-pixel, tiles into
    `block_size`x`block_size` blocks, and flags `ela_local_anomaly` if the
    fraction of blocks whose mean channel-summed error exceeds
    `diff_threshold` is >= `region_frac_threshold`. A pasted/edited region
    typically re-compresses differently than the surrounding untouched
    pixels, showing up as a spatially-clustered high-error patch - a single
    globally-recompressed (but otherwise untouched) photo does not. Returns
    `[]` for anything that isn't JPEG (detected via `Image.format`, not the
    file extension) - ELA needs lossy compression to be meaningful, so a PNG
    or PDF page has nothing for it to measure."""
    try:
        img = Image.open(io.BytesIO(data))
        if (img.format or "").upper() != "JPEG":
            return []
        img = img.convert("RGB")
    except Exception:
        return []

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    try:
        recompressed = Image.open(buf).convert("RGB")
    except Exception:
        return []

    orig = np.asarray(img, dtype=np.int16)
    recomp = np.asarray(recompressed, dtype=np.int16)
    if orig.shape != recomp.shape:
        return []

    diff = np.abs(orig - recomp).sum(axis=2)  # per-pixel error summed over R/G/B
    h, w = diff.shape
    bh, bw = h // block_size, w // block_size
    if bh == 0 or bw == 0:
        return []

    trimmed = diff[: bh * block_size, : bw * block_size]
    blocks = trimmed.reshape(bh, block_size, bw, block_size).mean(axis=(1, 3))
    anomalous_frac = float((blocks > diff_threshold).sum()) / blocks.size
    return ["ela_local_anomaly"] if anomalous_frac >= region_frac_threshold else []


def analyze_receipt_bytes(
    data: bytes, *,
    expected_format_hint: Optional[str] = None,
    ela_quality: int = 90,
    ela_diff_threshold: int = 40,
    ela_region_frac_threshold: float = 0.02,
) -> list[str]:
    """Single entry point `VerificationAgent` calls: sniffs type by magic
    bytes (not the URL/extension), dispatches to the metadata + ELA checks
    above, and unions the flags."""
    from adapters.pdf_render import is_pdf

    flags: set[str] = set()
    if is_pdf(data):
        flags.update(analyze_pdf_metadata(data))
    else:
        flags.update(analyze_image_metadata(data, expected_format_hint=expected_format_hint))
        flags.update(error_level_analysis(
            data, quality=ela_quality, diff_threshold=ela_diff_threshold,
            region_frac_threshold=ela_region_frac_threshold,
        ))
    return sorted(flags)
