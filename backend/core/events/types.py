"""Domain enumerations for event classification. Implements TRD §3.1, T16."""

from enum import StrEnum


class TransactionType(StrEnum):
    income = "income"
    expense = "expense"
    transfer = "transfer"
    investment = "investment"


class Actor(StrEnum):
    system = "system"
    user = "user"
    ai = "ai"


class BalanceCheck(StrEnum):
    pass_ = "pass"
    fail = "fail"


class IngestionStatus(StrEnum):
    success = "success"
    partial = "partial"
    failed = "failed"
    rejected = "rejected"
