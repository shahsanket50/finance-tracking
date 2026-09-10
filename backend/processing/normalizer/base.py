"""Merchant normalizer public interface. Implements PRD §4 (Step 4: Merchant normalization)."""

from __future__ import annotations

from processing.normalizer.normalizer import normalize_merchant

__all__ = ["normalize_merchant"]
