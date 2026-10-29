"""Generate sample travel-expense invoice PDFs for manual upload/testing.

Not part of the audit pipeline or its synthetic generator (generator/) - this is
a standalone content-authoring utility that produces realistic-looking (but
entirely fictitious) travel expense invoices, styled after a reference
template: a colored decorative header banner, a logo placeholder, an
invoice-meta table (number/date/due date), bulleted client info, an itemised
services table, a totals table, and a payment-instructions footer.

Useful for testing the "custom submission" upload flow (System admin > Concur
simulator) with varied real-looking PDFs rather than only the pipeline's own
plain synthetic receipts.

Requires reportlab (pip install reportlab) - not a core app dependency, so it
is intentionally NOT added to pyproject.toml.

Usage (from repo root):
    python scripts/generate_sample_invoices.py
Writes 5 PDFs to ../sample_invoices/ (sibling to this repo, alongside the
design docs) so they stay clearly separate from the app's own .data/ store.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT_DIR = Path(__file__).resolve().parent.parent.parent / "sample_invoices"

PAGE_W, PAGE_H = letter
MARGIN = 0.55 * inch
GRAY_HEADER = colors.HexColor("#eef0f2")
GRAY_TEXT = colors.HexColor("#5a6472")
DARK_TEXT = colors.HexColor("#1c2430")
BORDER = colors.HexColor("#d6dae0")


def _hex_variants(base: str) -> tuple[colors.Color, colors.Color]:
    """Return (solid, lighter-for-overlap) versions of an accent color."""
    c = colors.HexColor(base)
    lighter = colors.Color(c.red, c.green, c.blue, alpha=0.55)
    return c, lighter


def _draw_header(c: canvas.Canvas, *, company: str, accent_hex: str, tagline: str):
    accent, accent_light = _hex_variants(accent_hex)
    banner_h = 1.35 * inch
    top = PAGE_H

    # banner background
    c.setFillColor(colors.HexColor("#fbfbfb"))
    c.rect(0, top - banner_h, PAGE_W, banner_h, stroke=0, fill=1)

    # decorative overlapping circles, clipped to the banner via a clip path
    c.saveState()
    p = c.beginPath()
    p.rect(0, top - banner_h, PAGE_W, banner_h)
    c.clipPath(p, stroke=0, fill=0)
    c.setFillColor(accent)
    c.circle(PAGE_W - 0.4 * inch, top - 0.15 * inch, 0.95 * inch, stroke=0, fill=1)
    c.setFillColor(accent_light)
    c.circle(PAGE_W - 1.15 * inch, top - 0.55 * inch, 0.55 * inch, stroke=0, fill=1)
    c.restoreState()

    # logo placeholder box (top-left)
    logo_x, logo_y, logo_s = MARGIN, top - 0.85 * inch, 0.55 * inch
    c.setStrokeColor(BORDER)
    c.setFillColor(colors.white)
    c.rect(logo_x, logo_y, logo_s, logo_s, stroke=1, fill=1)
    c.setFillColor(accent)
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(logo_x + logo_s / 2, logo_y + logo_s / 2 - 6, company[0])
    c.setFont("Helvetica", 5.5)
    c.setFillColor(GRAY_TEXT)
    c.drawCentredString(logo_x + logo_s / 2, logo_y + logo_s / 2 - 15, "LOGO")

    # company name + tagline
    text_x = logo_x + logo_s + 0.18 * inch
    c.setFillColor(accent)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(text_x, top - 0.42 * inch, company)
    c.setFillColor(GRAY_TEXT)
    c.setFont("Helvetica", 8)
    c.drawString(text_x, top - 0.62 * inch, tagline)

    return top - banner_h


def _section_table(c: canvas.Canvas, y: float, headers: list[str], values: list[str],
                   col_widths: list[float]) -> float:
    """A 1-header-row table (used for invoice-meta and totals blocks)."""
    row_h = 0.32 * inch
    x = MARGIN
    # header row
    c.setFillColor(GRAY_HEADER)
    c.rect(x, y - row_h, sum(col_widths), row_h, stroke=0, fill=1)
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(DARK_TEXT)
    cx = x
    for h, w in zip(headers, col_widths):
        c.drawString(cx + 8, y - row_h + 10, h)
        cx += w
    # value row
    c.setFont("Helvetica", 9)
    cx = x
    for v, w in zip(values, col_widths):
        c.drawString(cx + 8, y - row_h - row_h + 11, v)
        cx += w
    c.setStrokeColor(BORDER)
    c.rect(x, y - 2 * row_h, sum(col_widths), 2 * row_h, stroke=1, fill=0)
    cx = x
    for w in col_widths[:-1]:
        cx += w
        c.line(cx, y - 2 * row_h, cx, y)
    return y - 2 * row_h


def _bullets(c: canvas.Canvas, y: float, lines: list[str]) -> float:
    c.setFont("Helvetica", 9)
    c.setFillColor(DARK_TEXT)
    for line in lines:
        c.drawString(MARGIN + 4, y, f"• {line}")
        y -= 0.2 * inch
    return y


def _items_table(c: canvas.Canvas, y: float, rows: list[tuple[str, str]],
                 currency: str) -> float:
    col_widths = [4.6 * inch, 1.9 * inch]
    row_h = 0.3 * inch
    x = MARGIN
    header_h = 0.32 * inch
    c.setFillColor(GRAY_HEADER)
    c.rect(x, y - header_h, sum(col_widths), header_h, stroke=0, fill=1)
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(DARK_TEXT)
    c.drawString(x + 8, y - header_h + 10, "Description of Services")
    c.drawString(x + col_widths[0] + 8, y - header_h + 10, "Subtotal")

    body_top = y - header_h
    c.setFont("Helvetica", 9)
    ry = body_top
    for desc, amount in rows:
        ry -= row_h
        c.drawString(x + 8, ry + 9, desc)
        c.drawRightString(x + col_widths[0] + col_widths[1] - 8, ry + 9, f"{currency}{amount}")

    total_h = header_h + row_h * len(rows)
    c.setStrokeColor(BORDER)
    c.rect(x, y - total_h, sum(col_widths), total_h, stroke=1, fill=0)
    c.line(x + col_widths[0], y - total_h, x + col_widths[0], y)
    for i in range(len(rows)):
        ly = body_top - row_h * (i + 1)
        c.line(x, ly, x + sum(col_widths), ly)
    return y - total_h


def _footer(c: canvas.Canvas, y: float, *, company: str, address: str,
           phone: str, email: str):
    c.setFont("Helvetica", 8.5)
    c.setFillColor(DARK_TEXT)
    c.drawString(MARGIN, y, "Please make payment payable to:")
    y -= 0.19 * inch
    c.drawString(MARGIN + 4, y, f"• {company}")
    y -= 0.19 * inch
    c.drawString(MARGIN + 4, y, f"• {address}")
    y -= 0.24 * inch
    c.drawString(
        MARGIN, y,
        f"For any questions regarding this invoice, please contact us at: {phone} or "
        f"email at {email}.",
    )


def draw_invoice(path: Path, data: dict) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    y = _draw_header(c, company=data["company"], accent_hex=data["accent"],
                     tagline=data["tagline"])
    y -= 0.45 * inch

    c.setFont("Helvetica-Bold", 16)
    c.setFillColor(DARK_TEXT)
    c.drawCentredString(PAGE_W / 2, y, "Travel Expense Invoice")
    y -= 0.35 * inch

    y = _section_table(
        c, y, ["Invoice Number:", "Invoice Date:", "Due Date:"],
        [data["invoice_number"], data["invoice_date"], data["due_date"]],
        [2.166 * inch, 2.166 * inch, 2.166 * inch],
    )
    y -= 0.28 * inch

    y = _bullets(c, y, [
        f"Client Name: {data['client_name']}",
        f"Client Address: {data['client_address']}",
        f"Client Contact: {data['client_contact']}",
    ])
    y -= 0.12 * inch

    y = _items_table(c, y, data["line_items"], data["currency"])
    y -= 0.28 * inch

    y = _section_table(
        c, y, ["Subtotal", f"Tax ({data['tax_pct']}%)", "Total Amount Due"],
        [f"{data['currency']}{data['subtotal']}", f"{data['currency']}{data['tax_amount']}",
         f"{data['currency']}{data['total']}"],
        [2.166 * inch, 2.166 * inch, 2.166 * inch],
    )
    y -= 0.35 * inch

    _footer(c, y, company=data["company"], address=data["company_address"],
           phone=data["company_phone"], email=data["company_email"])

    c.showPage()
    c.save()


INVOICES = [
    dict(
        company="Skyline Travel Co.", accent="#2f7a4f",
        tagline="Chicago, IL 60601  |  billing@skylinetravel.example  |  312 555 0142",
        invoice_number="TRX-20260112", invoice_date="January 12, 2026", due_date="February 11, 2026",
        client_name="Marcus Webb", client_address="Chicago, IL 60614",
        client_contact="Marcus Webb, marcus.webb@clientco.example, 312 555 9981",
        line_items=[("Airfare - Round Trip", "980.00"),
                    ("Hotel - 3 Nights (Business Hotel)", "540.00"),
                    ("Airport Transfer", "85.00")],
        currency="$", tax_pct="8", subtotal="1,605.00", tax_amount="128.40", total="1,733.40",
        company_address="120 Lakeshore Ave, Chicago, IL 60601",
        company_phone="312 555 0142", company_email="billing@skylinetravel.example",
    ),
    dict(
        company="Meridian Business Travel", accent="#1f3d7a",
        tagline="Austin, TX 78701  |  accounts@meridianbiztravel.example  |  512 555 0187",
        invoice_number="TRX-20260228", invoice_date="February 28, 2026", due_date="March 30, 2026",
        client_name="Priya Sharma", client_address="Austin, TX 78704",
        client_contact="Priya Sharma, priya.sharma@clientco.example, 512 555 4420",
        line_items=[("Business Class Airfare", "2,400.00"),
                    ("Hotel - 6 Nights (Executive Suite)", "1,680.00"),
                    ("Rental Car - 6 Days", "360.00"),
                    ("Conference Registration", "450.00"),
                    ("Meals Per Diem - 6 Days", "300.00")],
        currency="$", tax_pct="10", subtotal="5,190.00", tax_amount="519.00", total="5,709.00",
        company_address="88 Congress Plaza, Austin, TX 78701",
        company_phone="512 555 0187", company_email="accounts@meridianbiztravel.example",
    ),
    dict(
        company="Redwood Expense Partners", accent="#7a2f3d",
        tagline="Seattle, WA 98101  |  invoices@redwoodexpense.example  |  206 555 0163",
        invoice_number="TRX-20260305", invoice_date="March 5, 2026", due_date="April 4, 2026",
        client_name="Daniel Osei", client_address="Seattle, WA 98109",
        client_contact="Daniel Osei, daniel.osei@clientco.example, 206 555 7734",
        line_items=[("Train Ticket - Round Trip", "210.00"),
                    ("Hotel - 2 Nights", "360.00")],
        currency="$", tax_pct="9", subtotal="570.00", tax_amount="51.30", total="621.30",
        company_address="45 Pine Street, Seattle, WA 98101",
        company_phone="206 555 0163", company_email="invoices@redwoodexpense.example",
    ),
    dict(
        company="Alpine Corporate Journeys", accent="#1f6b6b",
        tagline="Denver, CO 80202  |  billing@alpinecorpjourneys.example  |  303 555 0129",
        invoice_number="TRX-20260410", invoice_date="April 10, 2026", due_date="May 10, 2026",
        client_name="Laura Fitzgerald", client_address="Denver, CO 80203",
        client_contact="Laura Fitzgerald, laura.fitzgerald@clientco.example, 303 555 6612",
        line_items=[("Airfare - Round Trip", "1,150.00"),
                    ("Hotel - 4 Nights", "920.00"),
                    ("Rental Car - 4 Days", "240.00"),
                    ("Parking", "60.00")],
        currency="$", tax_pct="7.5", subtotal="2,370.00", tax_amount="177.75", total="2,547.75",
        company_address="700 16th Street, Denver, CO 80202",
        company_phone="303 555 0129", company_email="billing@alpinecorpjourneys.example",
    ),
    dict(
        company="Horizon Travel Solutions", accent="#5b2f7a",
        tagline="Miami, FL 33034  |  inquire@horizontravelsolutions.example  |  305 555 0155",
        invoice_number="TRX-20260522", invoice_date="May 22, 2026", due_date="June 21, 2026",
        client_name="Tomas Rivera", client_address="Miami, FL 33101",
        client_contact="Tomas Rivera, tomas.rivera@clientco.example, 305 555 3387",
        line_items=[("Airfare - Round Trip", "1,320.00"),
                    ("Hotel - 5 Nights", "1,100.00"),
                    ("Taxi / Rideshare", "140.00"),
                    ("Travel Insurance", "75.00")],
        currency="$", tax_pct="10", subtotal="2,635.00", tax_amount="263.50", total="2,898.50",
        company_address="500 Ocean Drive, Miami, FL 33034",
        company_phone="305 555 0155", company_email="inquire@horizontravelsolutions.example",
    ),
]


# --------------------------------------------------------------------------- #
# Rejection-case invoices: each is engineered to trip ONE specific check when
# uploaded via System admin -> Concur simulator -> custom submission, using the
# upload settings noted in `upload_as`. See config/policy_rules.yaml for the
# cap values these deliberately breach.
# --------------------------------------------------------------------------- #
REJECTION_INVOICES = [
    dict(
        slug="lodging_cap_violation",
        reason="Policy violation - LODGING-CAP-01 (USD cap is $275/night)",
        upload_as="category=lodging, currency=USD, entered amount=410.00",
        company="Grandview Luxury Suites", accent="#8a6d1f",
        tagline="Las Vegas, NV 89109  |  billing@grandviewsuites.example  |  702 555 0198",
        invoice_number="TRX-20260603", invoice_date="June 3, 2026", due_date="July 3, 2026",
        client_name="Alex Chen", client_address="Las Vegas, NV 89109",
        client_contact="Alex Chen, alex.chen@clientco.example, 702 555 2214",
        line_items=[("Hotel - 1 Night (Presidential Suite)", "410.00")],
        currency="$", tax_pct="10", subtotal="410.00", tax_amount="41.00", total="451.00",
        company_address="3 Grandview Blvd, Las Vegas, NV 89109",
        company_phone="702 555 0198", company_email="billing@grandviewsuites.example",
    ),
    dict(
        slug="entertainment_cap_violation",
        reason="Policy violation - ENTERTAINMENT-CAP-01 (USD cap is $90/line)",
        upload_as="category=entertainment, currency=USD, entered amount=260.00",
        company="The Vault Club", accent="#3d1f4a",
        tagline="New York, NY 10001  |  events@thevaultclub.example  |  212 555 0176",
        invoice_number="TRX-20260609", invoice_date="June 9, 2026", due_date="July 9, 2026",
        client_name="Alex Chen", client_address="New York, NY 10018",
        client_contact="Alex Chen, alex.chen@clientco.example, 212 555 8823",
        line_items=[("Client Entertainment - Private Room", "260.00")],
        currency="$", tax_pct="8.5", subtotal="260.00", tax_amount="22.10", total="282.10",
        company_address="19 Velvet Row, New York, NY 10001",
        company_phone="212 555 0176", company_email="events@thevaultclub.example",
    ),
    dict(
        slug="subtotal_mismatch",
        reason="Subtotal mismatch - enter an amount that doesn't match the printed total "
               "(> 5% tolerance)",
        upload_as="category=transport, currency=USD, entered amount=150.00 "
                  "(printed total is $85.00 - that mismatch is the point)",
        company="QuickCab Rideshare", accent="#1f4a3d",
        tagline="Boston, MA 02108  |  receipts@quickcab.example  |  617 555 0142",
        invoice_number="TRX-20260615", invoice_date="June 15, 2026", due_date="July 15, 2026",
        client_name="Alex Chen", client_address="Boston, MA 02110",
        client_contact="Alex Chen, alex.chen@clientco.example, 617 555 5541",
        line_items=[("Rideshare - Airport to Hotel", "85.00")],
        currency="$", tax_pct="0", subtotal="85.00", tax_amount="0.00", total="85.00",
        company_address="200 Beacon St, Boston, MA 02108",
        company_phone="617 555 0142", company_email="receipts@quickcab.example",
    ),
    dict(
        slug="ai_generated_flag",
        reason="AI-generated / tampered receipt flag - check the 'Simulate AI-generated / "
               "tampered receipt' box at upload (an ordinary-looking invoice; the flag comes "
               "from that checkbox, not the file's visual content)",
        upload_as="category=meals, currency=USD, entered amount=42.00, "
                  "+ check 'Simulate AI-generated / tampered receipt'",
        company="The Grill House", accent="#4a3d1f",
        tagline="Portland, OR 97201  |  billing@thegrillhouse.example  |  503 555 0134",
        invoice_number="TRX-20260620", invoice_date="June 20, 2026", due_date="July 20, 2026",
        client_name="Alex Chen", client_address="Portland, OR 97204",
        client_contact="Alex Chen, alex.chen@clientco.example, 503 555 7790",
        line_items=[("Business Lunch - 2 Attendees", "42.00")],
        currency="$", tax_pct="9", subtotal="42.00", tax_amount="3.78", total="45.78",
        company_address="88 Riverside Ave, Portland, OR 97201",
        company_phone="503 555 0134", company_email="billing@thegrillhouse.example",
    ),
]

# Near-duplicate pair: same vendor/employee/category, amounts within the 3%
# duplicate_amount_tolerance_pct - upload BOTH with the same Employee ID
# (duplicate_require_same_employee: true) to trip DUPLICATE detection on the
# second one.
DUPLICATE_PAIR = [
    dict(
        slug="duplicate_pair_1",
        reason="Duplicate detection - pair 1 of 2 (upload first)",
        upload_as="category=transport, currency=USD, entered amount=45.00, "
                  "employee=EMP-DUPTEST",
        company="ParkEasy Airport Parking", accent="#1f3d4a",
        tagline="Denver, CO 80249  |  receipts@parkeasy.example  |  303 555 0111",
        invoice_number="TRX-20260701", invoice_date="July 1, 2026", due_date="July 31, 2026",
        client_name="Alex Chen", client_address="Denver, CO 80202",
        client_contact="Alex Chen, alex.chen@clientco.example, 303 555 4471",
        line_items=[("Airport Parking - 5 Days", "45.00")],
        currency="$", tax_pct="0", subtotal="45.00", tax_amount="0.00", total="45.00",
        company_address="1 Airport Way, Denver, CO 80249",
        company_phone="303 555 0111", company_email="receipts@parkeasy.example",
    ),
    dict(
        slug="duplicate_pair_2",
        reason="Duplicate detection - pair 2 of 2 (upload second, SAME employee ID as pair 1 "
               "- amount jittered <3% to mimic a near-duplicate resubmission)",
        upload_as="category=transport, currency=USD, entered amount=45.90, "
                  "employee=EMP-DUPTEST (must match pair 1)",
        company="ParkEasy Airport Parking", accent="#1f3d4a",
        tagline="Denver, CO 80249  |  receipts@parkeasy.example  |  303 555 0111",
        invoice_number="TRX-20260701-B", invoice_date="July 1, 2026", due_date="July 31, 2026",
        client_name="Alex Chen", client_address="Denver, CO 80202",
        client_contact="Alex Chen, alex.chen@clientco.example, 303 555 4471",
        line_items=[("Airport Parking - 5 Days", "45.90")],
        currency="$", tax_pct="0", subtotal="45.90", tax_amount="0.00", total="45.90",
        company_address="1 Airport Way, Denver, CO 80249",
        company_phone="303 555 0111", company_email="receipts@parkeasy.example",
    ),
]


# Human-review case: a single clean line item, safely under its category cap,
# with a recent transaction date (no LATE-SUBMISSION-01 flag) - so nothing
# trips a policy violation. The only signal here is the printed tax line
# ($6.80 on an $85.00 base fare, 8%): our subtotal check compares the entered
# amount (base, pre-tax) against the extracted amount+tax, so this ~7.4%
# variance exceeds the 5% tolerance (config/pipeline.yaml verification.
# subtotal_tolerance_pct) on its own - pushing risk_score to 0.3 (the
# subtotal_variance weight), which lands between auto_approve_cutoff (0.2)
# and auto_reject_cutoff (0.75) -> human_review, with zero policy violations.
REVIEW_INVOICES = [
    dict(
        slug="airport_transfer_review",
        reason="Routes to human_review, not approve/reject - single clean transport line "
               "well under TRANSPORT-CAP-01, recent date (no LATE-SUBMISSION-01), but the "
               "printed 8% tax line makes entered-vs-receipt subtotal variance ~7.4%, just "
               "over the 5% tolerance (subtotal_variance check only - no rule violations)",
        upload_as="category=transport, currency=USD, entered amount=85.00, "
                  "employee=EMP-JBLAKE (Auto-detect mode recommended - let the AI read the "
                  "printed $85.00 base fare + $6.80 tax itself)",
        company="CityLink Airport Transfers", accent="#2f4a7a",
        tagline="San Diego, CA 92101  |  receipts@citylinktransfers.example  |  619 555 0148",
        invoice_number="TRX-20260705", invoice_date="July 5, 2026", due_date="August 4, 2026",
        client_name="Jordan Blake", client_address="San Diego, CA 92104",
        client_contact="Jordan Blake, jordan.blake@clientco.example, 619 555 3362",
        line_items=[("Airport Transfer - Sedan", "85.00")],
        currency="$", tax_pct="8", subtotal="85.00", tax_amount="6.80", total="91.80",
        company_address="10 Harbor Dr, San Diego, CA 92101",
        company_phone="619 555 0148", company_email="receipts@citylinktransfers.example",
    ),
]


# --------------------------------------------------------------------------- #
# Outcome-mix set (2026-07-21): one invoice per routing outcome, verified
# against the CURRENT config/policy_rules.yaml + config/pipeline.yaml at
# generation time (thresholds drift as Settings gets edited - e.g.
# subtotal_tolerance_pct moved from 5.0% to 10.0% since the review-case sample
# above was built, which is why this set uses different numbers for the same
# kind of signal). Active categories are still exactly
# meals/lodging/transport/entertainment/misc (config/generator.yaml).
# --------------------------------------------------------------------------- #
OUTCOME_MIX_INVOICES = [
    dict(
        slug="auto_approved_parking",
        outcome="Auto-approved",
        reason="Clean single line, well under TRANSPORT-CAP-01 ($130 USD), no printed tax "
               "(so subtotal variance is exactly 0%), recent date (no LATE-SUBMISSION-01), "
               "not a round multiple of 25 (no round-amount flag). Zero risk signals -> "
               "risk_score 0.0 <= auto_approve_cutoff (0.2).",
        upload_as="category=transport, currency=USD, entered amount=85.00, employee=EMP-MLEE",
        company="QuickPark Airport Services", accent="#1f6b4a",
        tagline="Denver, CO 80249  |  receipts@quickparkairport.example  |  303 555 0177",
        invoice_number="TRX-20260710", invoice_date="July 10, 2026", due_date="August 9, 2026",
        client_name="Morgan Lee", client_address="Denver, CO 80202",
        client_contact="Morgan Lee, morgan.lee@clientco.example, 303 555 6690",
        line_items=[("Airport Parking - 3 Days", "85.00")],
        currency="$", tax_pct="0", subtotal="85.00", tax_amount="0.00", total="85.00",
        company_address="1 Airport Way, Denver, CO 80249",
        company_phone="303 555 0177", company_email="receipts@quickparkairport.example",
    ),
    dict(
        slug="auto_rejected_lodging",
        outcome="Auto-rejected",
        reason="$600 lodging line breaches TWO distinct rules at once: LODGING-CAP-01 "
               "(600 > $275 USD cap) AND ROUND-AMOUNT-GLOBAL-01 (600 is a round multiple of "
               "25 and >= $100). 2 violations x 0.5 policy_violation weight = 1.0 (capped) "
               ">= auto_reject_cutoff (0.75) - well past the threshold even if weights get "
               "retuned. 10% printed tax stays within the lodging tax-ratio band (0-30%), "
               "so it doesn't also add a spurious subtotal-variance signal.",
        upload_as="category=lodging, currency=USD, entered amount=600.00, employee=EMP-RSINGH",
        company="Riverside Grand Hotel", accent="#8a1f2f",
        tagline="Chicago, IL 60601  |  billing@riversidegrandhotel.example  |  312 555 0193",
        invoice_number="TRX-20260713", invoice_date="July 13, 2026", due_date="August 12, 2026",
        client_name="Raj Singh", client_address="Chicago, IL 60614",
        client_contact="Raj Singh, raj.singh@clientco.example, 312 555 4471",
        line_items=[("Hotel - 1 Night (Deluxe Suite)", "600.00")],
        currency="$", tax_pct="10", subtotal="600.00", tax_amount="60.00", total="660.00",
        company_address="200 Riverside Dr, Chicago, IL 60601",
        company_phone="312 555 0193", company_email="billing@riversidegrandhotel.example",
    ),
    dict(
        slug="human_review_subtotal_variance",
        outcome="Human review",
        reason="Single clean transport line, well under TRANSPORT-CAP-01, recent date (no "
               "LATE-SUBMISSION-01) - zero policy violations. But the printed ~14% tax line "
               "(entered amount is the pre-tax $85.00 base fare) makes entered-vs-receipt "
               "subtotal variance 12.37%, over the CURRENT 10% tolerance "
               "(subtotal_variance_pct check only) -> risk_score 0.3, between "
               "auto_approve_cutoff (0.2) and auto_reject_cutoff (0.75).",
        upload_as="category=transport, currency=USD, entered amount=85.00, employee=EMP-TOKAFOR "
                  "(Auto-detect mode recommended - let the AI read the printed $85.00 base "
                  "fare + $12.00 tax itself)",
        company="MetroFleet Transfers", accent="#4a1f6b",
        tagline="Austin, TX 78701  |  receipts@metrofleettransfers.example  |  512 555 0166",
        invoice_number="TRX-20260714", invoice_date="July 14, 2026", due_date="August 13, 2026",
        client_name="Tokafor Osei", client_address="Austin, TX 78704",
        client_contact="Tokafor Osei, tokafor.osei@clientco.example, 512 555 8834",
        line_items=[("Airport Transfer - SUV", "85.00")],
        currency="$", tax_pct="14.1", subtotal="85.00", tax_amount="12.00", total="97.00",
        company_address="500 Congress Ave, Austin, TX 78701",
        company_phone="512 555 0166", company_email="receipts@metrofleettransfers.example",
    ),
]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for i, data in enumerate(INVOICES, start=1):
        fname = f"sample_travel_invoice_{i}_{data['company'].split()[0].lower()}.pdf"
        path = OUT_DIR / fname
        draw_invoice(path, data)
        print(f"wrote {path}")
    print(f"\n{len(INVOICES)} clean sample invoice(s) written to {OUT_DIR}")

    rej_dir = OUT_DIR / "rejection_cases"
    rej_dir.mkdir(parents=True, exist_ok=True)
    all_rejection = list(enumerate(REJECTION_INVOICES + DUPLICATE_PAIR, start=1))
    print(f"\nRejection-case invoices written to {rej_dir}:\n")
    for i, data in all_rejection:
        fname = f"reject_{i}_{data['slug']}.pdf"
        path = rej_dir / fname
        draw_invoice(path, data)
        print(f"  {fname}")
        print(f"    Reason:    {data['reason']}")
        print(f"    Upload as: {data['upload_as']}\n")
    print(f"{len(all_rejection)} rejection-case invoice(s) written to {rej_dir}")

    review_dir = OUT_DIR / "review_cases"
    review_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nHuman-review-case invoices written to {review_dir}:\n")
    for i, data in enumerate(REVIEW_INVOICES, start=1):
        fname = f"review_{i}_{data['slug']}.pdf"
        path = review_dir / fname
        draw_invoice(path, data)
        print(f"  {fname}")
        print(f"    Reason:    {data['reason']}")
        print(f"    Upload as: {data['upload_as']}\n")
    print(f"{len(REVIEW_INVOICES)} human-review-case invoice(s) written to {review_dir}")

    mix_dir = OUT_DIR / "outcome_mix"
    mix_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nOutcome-mix invoices written to {mix_dir}:\n")
    for i, data in enumerate(OUTCOME_MIX_INVOICES, start=1):
        fname = f"mix_{i}_{data['slug']}.pdf"
        path = mix_dir / fname
        draw_invoice(path, data)
        print(f"  {fname}  [{data['outcome']}]")
        print(f"    Reason:    {data['reason']}")
        print(f"    Upload as: {data['upload_as']}\n")
    print(f"{len(OUTCOME_MIX_INVOICES)} outcome-mix invoice(s) written to {mix_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
