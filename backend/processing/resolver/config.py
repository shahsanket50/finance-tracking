"""Resolver configuration constants.

All match windows are named constants — never bare literals in matching logic.
Calibration risk: these values are working assumptions; calibrate against real
statement data before Phase 2 closes. See PROJECT_STATE.md §Standing risks.
"""

# Calendar days (IST) a savings-account debit may precede or follow a paired credit.
# Calibration is a standing risk — see PROJECT_STATE.md.
TRANSFER_MATCH_WINDOW_DAYS: int = 3
CC_PAYMENT_MATCH_WINDOW_DAYS: int = 3  # CC bill typically clears 1–3 days after savings debit
FD_BOOKING_MATCH_WINDOW_DAYS: int = 3

# Confidence floor below which a resolver match is not auto-committed (basis points, 0–10000).
RESOLVER_CONFIDENCE_THRESHOLD: int = 8500
