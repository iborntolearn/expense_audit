"""ID helpers.

`line_item_id` must be globally unique across submissions (it is the primary key
of extracted_line_items and the key receipt_embeddings references). The report
line_id ("LN-1") is only unique within a submission, so the global id namespaces
it by submission.
"""
from __future__ import annotations


def line_item_id(submission_id: str, line_id: str) -> str:
    return f"{submission_id}:{line_id}"
