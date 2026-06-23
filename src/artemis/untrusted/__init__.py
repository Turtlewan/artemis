"""Reusable untrusted-content security primitives.

This package provides spotlighting plus a toolless, schema-constrained
quarantined reader. DR-c is the first consumer; M3 ingestion and connectors can
reuse the same primitive later.
"""

from artemis.untrusted.quarantine import (
    EXTRACTION_SCHEMA,
    Extract,
    QuarantinedReader,
    QuarantineError,
)
from artemis.untrusted.spotlight import SPOTLIGHT_INSTRUCTION, spotlight

__all__ = [
    "EXTRACTION_SCHEMA",
    "SPOTLIGHT_INSTRUCTION",
    "Extract",
    "QuarantineError",
    "QuarantinedReader",
    "spotlight",
]
