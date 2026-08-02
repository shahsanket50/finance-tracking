"""H4: UTC storage, IST business logic.

Store all timestamps in UTC. All FY/period logic runs in IST (Asia/Kolkata).
A transaction at 2026-03-31T23:30:00Z is 2026-04-01T05:00 IST — FY 2026-27.
Getting this wrong misfiles income across tax years.

Implements TRD §3.6.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def utc_to_ist(utc_dt: datetime) -> datetime:
    """Convert a UTC-aware datetime to IST."""
    return utc_dt.astimezone(IST)


def ist_fy_year(utc_dt: datetime) -> int:
    """Return the financial year start year for a UTC datetime.

    Indian FY runs April 1 → March 31.
    FY 2025-26 started April 1, 2025 → label = 2025.
    FY 2026-27 starts April 1, 2026 → label = 2026.

    Formula: if IST month >= 4, FY = IST year; else FY = IST year - 1.
    """
    ist_dt = utc_to_ist(utc_dt)
    return ist_dt.year if ist_dt.month >= 4 else ist_dt.year - 1


def ist_statement_period(utc_dt: datetime) -> tuple[int, int]:
    """Return (fy_year, quarter_number) for a UTC datetime in IST.

    Quarter 1: Apr-Jun, Q2: Jul-Sep, Q3: Oct-Dec, Q4: Jan-Mar.
    """
    ist_dt = utc_to_ist(utc_dt)
    fy = ist_fy_year(utc_dt)
    month = ist_dt.month
    if month in (4, 5, 6):
        quarter = 1
    elif month in (7, 8, 9):
        quarter = 2
    elif month in (10, 11, 12):
        quarter = 3
    else:  # 1, 2, 3
        quarter = 4
    return fy, quarter
