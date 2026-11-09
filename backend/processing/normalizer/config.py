"""Merchant normalizer config. All thresholds are UNVERIFIED pending real usage data."""

# UNVERIFIED — calibrate against real statement data before live ingestion
NORMALIZATION_CONFIDENCE_THRESHOLD: int = 7000  # basis points
