"""CandidateTxn: the input unit for all resolver matchers."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CandidateTxn:
    idempotency_hash: str
    amount_paise: int
    value_date: date
    account_type: str
