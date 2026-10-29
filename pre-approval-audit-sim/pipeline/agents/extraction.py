"""Extraction agent (Milestone 4).

Vision-LLM line-item extraction behind the VisionExtractor adapter. Guardrail
(Tech Design 5): every line gets a confidence score; illegible fields come back
null with low confidence rather than a silent guess. Routing on low confidence
is the risk agent's job - extraction only reports.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from adapters.vision import VisionExtractor, load_itemization
from common.schemas import AuditState, ExtractedLine, SubmissionCreatedEvent
from data.interfaces import BlobStore

logger = logging.getLogger("pipeline.agents.extraction")


class ExtractionAgent:
    def __init__(self, blobs: BlobStore, extractor: VisionExtractor):
        self._blobs = blobs
        self._extractor = extractor

    def run(self, state: AuditState, event: SubmissionCreatedEvent) -> None:
        # Multiple report_lines can share one receipt_url when a single
        # multi-item invoice was auto-split into several lines (System admin ->
        # Concur simulator -> custom submission -> Auto-detect line items). The
        # itemization step that built those lines already read the document
        # once via `extract_items()` and cached the per-line result
        # (`.items.json`, see adapters/vision.py) - reuse it here instead of
        # calling the single-field `extract()` again per line, which would
        # re-read the same pixels and (for `amount`) very likely return the
        # same value for every line rather than each line's own figure.
        lines_by_url: dict[str, list] = defaultdict(list)
        for line in event.report_lines:
            lines_by_url[line.receipt_url].append(line)

        extracted_by_id: dict[str, ExtractedLine] = {}
        for url, lines in lines_by_url.items():
            items = load_itemization(self._blobs, url)
            if items:
                for line, item in zip(lines, items):
                    extracted_by_id[line.line_id] = ExtractedLine(
                        line_id=line.line_id, vendor=item.vendor, date=item.date,
                        amount=item.amount, tax=item.tax, currency=item.currency,
                        confidence=item.confidence,
                    )
                # Cached itemization had fewer entries than lines built from it
                # (shouldn't happen when the cache and the lines came from the
                # same call) - extract the remainder normally rather than
                # leaving them silently unextracted.
                for line in lines[len(items):]:
                    extracted_by_id[line.line_id] = self._extractor.extract(
                        self._blobs, url, line.line_id, event.currency
                    )
            else:
                for line in lines:
                    extracted_by_id[line.line_id] = self._extractor.extract(
                        self._blobs, url, line.line_id, event.currency
                    )

        for line in event.report_lines:
            state.extracted_lines.append(extracted_by_id[line.line_id])

        logger.debug(
            "extracted %d lines for %s", len(state.extracted_lines), event.submission_id
        )
