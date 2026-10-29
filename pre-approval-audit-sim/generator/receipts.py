"""Synthetic receipt rendering (Pillow only, no external fonts).

Produces receipt artifacts in three formats standing in for the variety a real
OE would present (Tech Design 2.4):
  * photo       -> PNG, slightly rotated + noised to mimic a phone photo
  * scanned_pdf -> single-page PDF (image saved as PDF)
  * e_receipt   -> clean, high-contrast digital-style PNG

`manipulated=True` deliberately breaks the printed total so the (Phase 2)
verification agent has a subtotal-variance signal to catch.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date

from PIL import Image, ImageDraw, ImageFont

_W, _H = 520, 720
_FONT = ImageFont.load_default()

# Printed-label translations, keyed by ISO 639-1 code - matches
# `generator.yaml`'s `language_mix`. Deliberately a handful of real
# translations (not a claim of covering "90+ languages" - that figure is a
# property of the underlying vision model's training breadth, which this
# offline Pillow-rendered fixture can't itself demonstrate at that scale),
# so a synthetic receipt's rendered text and its `.sim.json` sidecar
# `language` field stay honest and consistent with each other.
_LABELS: dict[str, dict[str, str]] = {
    "en": {"header": "RECEIPT", "date": "Date", "subtotal": "Subtotal", "tax": "Tax", "total": "TOTAL"},
    "de": {"header": "QUITTUNG", "date": "Datum", "subtotal": "Zwischensumme", "tax": "MwSt", "total": "GESAMT"},
    # ASCII-only labels - Pillow's default bitmap font (`ImageFont.load_default()`)
    # has incomplete glyph coverage for accented characters.
    "fr": {"header": "RECU", "date": "Date", "subtotal": "Sous-total", "tax": "TVA", "total": "TOTAL"},
    "es": {"header": "RECIBO", "date": "Fecha", "subtotal": "Subtotal", "tax": "IVA", "total": "TOTAL"},
    "it": {"header": "RICEVUTA", "date": "Data", "subtotal": "Subtotale", "tax": "IVA", "total": "TOTALE"},
}


@dataclass(frozen=True)
class RenderedReceipt:
    data: bytes
    content_type: str
    ext: str


@dataclass(frozen=True)
class ReceiptLine:
    description: str
    amount: float


def _draw_base(
    vendor: str,
    txn_date: date,
    currency: str,
    lines: list[ReceiptLine],
    tax: float,
    printed_total: float,
    lang: str,
) -> Image.Image:
    img = Image.new("RGB", (_W, _H), "white")
    d = ImageDraw.Draw(img)
    y = 24

    def line(text: str, dy: int = 20, x: int = 24) -> None:
        nonlocal y
        d.text((x, y), text, fill="black", font=_FONT)
        y += dy

    labels = _LABELS.get(lang, _LABELS["en"])
    line(f"*** {vendor} ***", 26)
    line(labels["header"], 24)
    line(f"{labels['date']}: {txn_date.isoformat()}", 22)
    line("-" * 44, 22)
    for ln in lines:
        d.text((24, y), ln.description[:28], fill="black", font=_FONT)
        d.text((360, y), f"{ln.amount:>10.2f}", fill="black", font=_FONT)
        y += 20
    line("-" * 44, 22)
    subtotal = sum(l.amount for l in lines)
    line(f"{labels['subtotal']}: {subtotal:.2f} {currency}", 20)
    line(f"{labels['tax']}: {tax:.2f} {currency}", 20)
    line(f"{labels['total']}: {printed_total:.2f} {currency}", 24)
    return img


def render(
    fmt: str,
    *,
    vendor: str,
    txn_date: date,
    currency: str,
    lines: list[ReceiptLine],
    tax: float,
    printed_total: float,
    lang: str = "en",
    manipulated: bool = False,
) -> RenderedReceipt:
    img = _draw_base(vendor, txn_date, currency, lines, tax, printed_total, lang)

    if manipulated:
        # Faint tamper marker (kept subtle; the real signal is the total mismatch).
        ImageDraw.Draw(img).text((24, _H - 40), "[edited]", fill=(230, 230, 230), font=_FONT)

    if fmt == "photo":
        img = img.rotate(-3, expand=True, fillcolor="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return RenderedReceipt(buf.getvalue(), "image/png", "png")

    if fmt == "scanned_pdf":
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PDF")
        return RenderedReceipt(buf.getvalue(), "application/pdf", "pdf")

    if fmt == "e_receipt":
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return RenderedReceipt(buf.getvalue(), "image/png", "png")

    raise ValueError(f"unknown receipt format: {fmt!r}")
