"""Nature tagger configuration. Implements PRD §5.1."""

# Basis points. Below this, the LLM result goes to the review queue.
# Anchored loosely to CATEGORIZATION_CONFIDENCE_THRESHOLD (7500 bps).
# UNVERIFIED — calibrate against real data before Phase 3 exit.
NATURE_CONFIDENCE_THRESHOLD: int = 7500  # UNVERIFIED
