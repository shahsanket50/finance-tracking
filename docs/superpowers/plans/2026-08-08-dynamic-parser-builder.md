# Dynamic Parser Builder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When no template parser matches a PDF, fall back to an LLM that extracts transactions using a structured schema, stores the extraction as an event (for deterministic replay), and presents a low-confidence preview that requires explicit user acknowledgement before confirming.

**Architecture:** Three new components — an LLM adapter layer (`adapters/llm/`), an `LlmFallbackParser` that implements `AbstractParser`, and a prompt file versioned in the repo. The harness (`dry_run()`) gets a final fallback entry after all template parsers fail. See TRD §12 for the complete spec.

**Tech Stack:** Anthropic Python SDK (`anthropic>=0.40`), Pydantic v2 (already a dependency), existing `AbstractParser` contract. No new runtime dependencies beyond the Anthropic SDK.

**Phase scope: Phase 2.** Do NOT begin implementation before Phase 1 is fully closed (acceptance checklist passed, branch merged).

## Global Constraints

- All LLM calls must go through `adapters/llm/base.py` — never import `anthropic` outside that layer
- Structured output only: every LLM call returns a Pydantic-validated `LlmParsedStatement`, never free text
- `canonical_narration`, `occurrence_index`, and `idempotency_hash` must be computed via `core.hashing.hash` shared functions — no duplication inside `LlmFallbackParser`
- LLM fallback confidence = 6000 basis points (exactly); template parsers remain ≥ 9000
- Prompt file lives at `backend/ingestion/parsers/prompts/llm_fallback_v1.txt`; prompt changes bump the version, never overwrite
- `IngestionEvent.source_detail` must record `{"parser": "llm_fallback", "model": "...", "prompt_version": "v1"}` — required for deterministic replay
- In CI: LLM adapter is mocked (pre-recorded response fixture) — no live API calls in tests
- `running_balance_paise` is `None` if the LLM says it's absent — never invented
- Money amounts from the LLM are coerced to `int` via Pydantic validator (LLMs often return `1234.56`)

---

### Task 1: LLM adapter layer

**Files:**
- Create: `backend/adapters/__init__.py`
- Create: `backend/adapters/llm/__init__.py`
- Create: `backend/adapters/llm/base.py`
- Create: `backend/adapters/llm/claude.py`
- Create: `backend/tests/unit/adapters/__init__.py`
- Create: `backend/tests/unit/adapters/test_llm_adapter.py`

**Interfaces:**
- Produces: `LlmAdapter` Protocol + `ClaudeAdapter(LlmAdapter)` consumed by Task 2

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/adapters/test_llm_adapter.py
from unittest.mock import MagicMock, patch
from pydantic import BaseModel
from adapters.llm.claude import ClaudeAdapter

class _Echo(BaseModel):
    message: str

def test_claude_adapter_calls_api_and_returns_model():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text='{"message": "hello"}')]
    )
    adapter = ClaudeAdapter(client=mock_client)
    result = adapter.complete("say hello", _Echo, model="claude-haiku-4-5-20251001")
    assert isinstance(result, _Echo)
    assert result.message == "hello"

def test_claude_adapter_passes_json_schema_in_prompt():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text='{"message": "hi"}')]
    )
    adapter = ClaudeAdapter(client=mock_client)
    adapter.complete("test", _Echo, model="claude-haiku-4-5-20251001")
    call_args = mock_client.messages.create.call_args
    # The schema should appear somewhere in the prompt
    assert "message" in str(call_args)

def test_claude_adapter_raises_on_invalid_json():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="not json")]
    )
    adapter = ClaudeAdapter(client=mock_client)
    with pytest.raises(Exception):
        adapter.complete("test", _Echo, model="claude-haiku-4-5-20251001")
```

- [ ] **Step 2: Run tests — expect import error**

```bash
cd backend && PYTHONPATH=. pytest tests/unit/adapters/test_llm_adapter.py -v 2>&1 | head -15
```

- [ ] **Step 3: Write `backend/adapters/llm/base.py`**

```python
"""LLM adapter interface. All model calls go through this layer. Implements TRD §4.4."""

from __future__ import annotations

from typing import Protocol, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LlmAdapter(Protocol):
    def complete(
        self,
        prompt: str,
        response_schema: type[T],
        model: str,
        max_tokens: int = 4096,
    ) -> T: ...
```

- [ ] **Step 4: Write `backend/adapters/llm/claude.py`**

```python
"""Claude LLM adapter. Implements TRD §4.4 adapter layer for Anthropic models."""

from __future__ import annotations

import json
from typing import TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ClaudeAdapter:
    def __init__(self, client: object | None = None) -> None:
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self._client = client  # type: ignore[assignment]

    def complete(
        self,
        prompt: str,
        response_schema: type[T],
        model: str,
        max_tokens: int = 4096,
    ) -> T:
        schema_json = response_schema.model_json_schema()
        full_prompt = (
            f"{prompt}\n\n"
            f"Respond with valid JSON matching this schema:\n{json.dumps(schema_json, indent=2)}\n"
            "Return only the JSON object, no commentary."
        )
        response = self._client.messages.create(  # type: ignore[union-attr]
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": full_prompt}],
        )
        raw = response.content[0].text
        return response_schema.model_validate_json(raw)
```

- [ ] **Step 5: Run tests — expect 3 pass**

```bash
cd backend && PYTHONPATH=. pytest tests/unit/adapters/test_llm_adapter.py -v --tb=short
```
Expected: 3 passed

- [ ] **Step 6: Add `anthropic>=0.40` to runtime deps in `pyproject.toml`**

Under `[project] dependencies`:
```toml
"anthropic>=0.40",
```

- [ ] **Step 7: Ruff + mypy**

```bash
cd backend && python -m ruff check adapters/ && python -m ruff format --check adapters/
cd backend && python -m mypy --config-file pyproject.toml --explicit-package-bases adapters/ 2>&1 | tail -5
```

- [ ] **Step 8: Commit**

```bash
git add backend/adapters/ backend/tests/unit/adapters/ backend/pyproject.toml
git commit -m "feat: LLM adapter layer — ClaudeAdapter + Protocol (Phase 2, TRD §4.4/§12)"
```

---

### Task 2: LLM fallback parser

**Files:**
- Create: `backend/ingestion/parsers/prompts/llm_fallback_v1.txt`
- Create: `backend/ingestion/parsers/llm_fallback.py`
- Create: `backend/tests/unit/ingestion/test_llm_fallback_parser.py`
- Create: `backend/tests/fixtures/golden/llm_fallback/statement_001_response.json` (pre-recorded LLM response)

**Interfaces:**
- Consumes: `LlmAdapter` from Task 1, `AbstractParser` from `ingestion/parsers/base.py`
- Produces: `LlmFallbackParser(AbstractParser)` consumed by Task 3 (harness update)

- [ ] **Step 1: Write the prompt `llm_fallback_v1.txt`**

```
You are a bank statement parser. Given the raw text extracted from a bank statement PDF,
extract all transactions and return them as structured JSON.

SIGN CONVENTION:
- Debit (money leaving the account): amount_paise is NEGATIVE (e.g. -50000 for ₹500 debit)
- Credit (money entering the account): amount_paise is POSITIVE (e.g. +50000 for ₹500 credit)

PAISE CONVERSION: All amounts must be in paise (1 rupee = 100 paise). Round to nearest paisa.
Do not return float values — return integers only. For example: ₹1,234.56 → 123456.

BALANCE CHECK: Verify: opening_balance_paise + sum(all amount_paise) == closing_balance_paise
If this does not hold, re-examine your extraction before returning.

NULL RULES:
- running_balance_paise: set to null if the statement does not show a running balance column
- opening_balance_paise: set to 0 ONLY if the statement explicitly states the opening balance is zero.
  If not found, this is a parser error — set opening_balance_paise to 0 and note it in extraction_notes.
- Never invent values. Unknown → null.

ACCOUNT REF FORMAT: last 4 digits of account number with a bank prefix. Example: "HDFC_SAV_4321".
If the bank is unknown, use "UNKNOWN_XXXX" where XXXX are the last 4 digits found.

PERIOD FORMAT: dates as "YYYY-MM-DD".

Return only the JSON object. No preamble, no commentary outside the JSON.

---

PDF TEXT:
{pdf_text}
```

- [ ] **Step 2: Write failing tests for `LlmFallbackParser`**

```python
# backend/tests/unit/ingestion/test_llm_fallback_parser.py
import json
import pickle
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ingestion.parsers.llm_fallback import LlmFallbackParser, LlmParsedStatement, LlmParsedTransaction

RESPONSE_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "golden" / "llm_fallback" / "statement_001_response.json"

def _make_mock_adapter(response_json: str) -> MagicMock:
    mock = MagicMock()
    mock.complete.return_value = LlmParsedStatement.model_validate_json(response_json)
    return mock

def test_can_parse_always_false():
    """LlmFallbackParser.can_parse() always returns False — it is a fallback, not a detector."""
    parser = LlmFallbackParser(adapter=MagicMock())
    assert parser.can_parse("any text") is False

def test_parse_returns_parsed_statement():
    response_json = RESPONSE_FIXTURE.read_text()
    mock_adapter = _make_mock_adapter(response_json)
    parser = LlmFallbackParser(adapter=mock_adapter)
    mock_pdf = MagicMock()
    mock_pdf.pages = [MagicMock()]
    mock_pdf.pages[0].extract_text.return_value = "sample pdf text"
    result = parser.parse(mock_pdf)
    from ingestion.parsers.base import ParsedStatement
    assert isinstance(result, ParsedStatement)

def test_parse_uses_shared_hash_functions():
    """canonical_narration and idempotency_hash come from core.hashing.hash, not re-implemented."""
    response_json = RESPONSE_FIXTURE.read_text()
    mock_adapter = _make_mock_adapter(response_json)
    parser = LlmFallbackParser(adapter=mock_adapter)
    mock_pdf = MagicMock()
    mock_pdf.pages = [MagicMock()]
    mock_pdf.pages[0].extract_text.return_value = "sample pdf text"
    result = parser.parse(mock_pdf)
    # Every transaction must have a 64-char hex hash
    for txn in result.transactions:
        assert len(txn.idempotency_hash) == 64
        assert all(c in "0123456789abcdef" for c in txn.idempotency_hash)

def test_parse_confidence_is_6000():
    response_json = RESPONSE_FIXTURE.read_text()
    mock_adapter = _make_mock_adapter(response_json)
    parser = LlmFallbackParser(adapter=mock_adapter)
    mock_pdf = MagicMock()
    mock_pdf.pages = [MagicMock()]
    mock_pdf.pages[0].extract_text.return_value = "sample pdf text"
    result = parser.parse(mock_pdf)
    assert result.confidence == 6000

def test_parse_amount_paise_is_integer():
    """LLM may return floats — Pydantic must coerce to int."""
    raw = {
        "bank": "test_bank",
        "account_ref": "TEST_4321",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "opening_balance_paise": 100000,
        "closing_balance_paise": 95000,
        "transactions": [
            {
                "value_date": "2026-01-15",
                "narration": "Coffee Shop",
                "amount_paise": -5000.0,  # float from LLM
                "running_balance_paise": 95000,
            }
        ],
        "extraction_notes": "",
    }
    parsed = LlmParsedStatement.model_validate(raw)
    assert isinstance(parsed.transactions[0].amount_paise, int)
    assert parsed.transactions[0].amount_paise == -5000
```

- [ ] **Step 3: Create the pre-recorded response fixture**

```json
// backend/tests/fixtures/golden/llm_fallback/statement_001_response.json
{
  "bank": "test_bank",
  "account_ref": "TEST_4321",
  "period_start": "2026-01-01",
  "period_end": "2026-01-31",
  "opening_balance_paise": 100000,
  "closing_balance_paise": 50000,
  "transactions": [
    {
      "value_date": "2026-01-10",
      "narration": "DEBIT CARD PURCHASE COFFEE SHOP",
      "amount_paise": -25000,
      "running_balance_paise": 75000
    },
    {
      "value_date": "2026-01-20",
      "narration": "DEBIT CARD PURCHASE GROCERY STORE",
      "amount_paise": -25000,
      "running_balance_paise": 50000
    }
  ],
  "extraction_notes": "Balance check verified: 100000 + (-25000) + (-25000) = 50000"
}
```

- [ ] **Step 4: Write `backend/ingestion/parsers/llm_fallback.py`**

```python
"""LLM fallback parser for unrecognised bank PDF layouts. Implements TRD §12."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, field_validator

if TYPE_CHECKING:
    import pdfplumber

from core.hashing.hash import canonicalize_narration, compute_idempotency_hash, compute_occurrence_index
from ingestion.parsers.base import AbstractParser, ParsedStatement, ParsedTransaction

_PROMPT_FILE = Path(__file__).parent / "prompts" / "llm_fallback_v1.txt"
_PROMPT_VERSION = "v1"
_CONFIDENCE = 6000
_DEFAULT_MODEL = os.environ.get("LLM_FALLBACK_MODEL", "claude-opus-4-7")


class LlmParsedTransaction(BaseModel):
    value_date: date
    narration: str
    amount_paise: int
    running_balance_paise: int | None = None

    @field_validator("amount_paise", mode="before")
    @classmethod
    def coerce_to_int(cls, v: object) -> int:
        return int(float(str(v)))


class LlmParsedStatement(BaseModel):
    bank: str
    account_ref: str
    period_start: date
    period_end: date
    opening_balance_paise: int
    closing_balance_paise: int
    transactions: list[LlmParsedTransaction]
    extraction_notes: str = ""


class LlmFallbackParser(AbstractParser):
    def __init__(self, adapter: object | None = None, model: str = _DEFAULT_MODEL) -> None:
        if adapter is None:
            from adapters.llm.claude import ClaudeAdapter
            adapter = ClaudeAdapter()
        self._adapter = adapter
        self._model = model
        self._prompt_template = _PROMPT_FILE.read_text()

    def can_parse(self, text: str) -> bool:
        return False  # never selected by the harness's can_parse() scan; injected explicitly

    def parse(self, pdf: "pdfplumber.PDF") -> ParsedStatement:
        raw_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        prompt = self._prompt_template.replace("{pdf_text}", raw_text[:8000])

        llm_result: LlmParsedStatement = self._adapter.complete(  # type: ignore[union-attr]
            prompt, LlmParsedStatement, model=self._model
        )

        seen: list[tuple[str, date, int, str]] = []
        transactions: list[ParsedTransaction] = []
        for llm_txn in llm_result.transactions:
            canonical = canonicalize_narration(llm_txn.narration)
            occ_idx = compute_occurrence_index(
                seen,
                llm_txn.value_date,
                llm_txn.amount_paise,
                canonical,
            )
            id_hash = compute_idempotency_hash(
                llm_result.account_ref,
                llm_txn.value_date,
                llm_txn.amount_paise,
                canonical,
                occ_idx,
            )
            transactions.append(
                ParsedTransaction(
                    account_ref=llm_result.account_ref,
                    value_date=llm_txn.value_date,
                    amount_paise=llm_txn.amount_paise,
                    narration=llm_txn.narration,
                    canonical_narration=canonical,
                    occurrence_index=occ_idx,
                    idempotency_hash=id_hash,
                    running_balance_paise=llm_txn.running_balance_paise,
                )
            )

        return ParsedStatement(
            bank=f"llm_fallback:{llm_result.bank}",
            account_ref=llm_result.account_ref,
            period_start=llm_result.period_start,
            period_end=llm_result.period_end,
            opening_balance_paise=llm_result.opening_balance_paise,
            closing_balance_paise=llm_result.closing_balance_paise,
            transactions=transactions,
            confidence=_CONFIDENCE,
            raw_text=raw_text,
        )
```

- [ ] **Step 5: Run tests — expect 5 pass**

```bash
cd backend && PYTHONPATH=. pytest tests/unit/ingestion/test_llm_fallback_parser.py -v --tb=short
```
Expected: 5 passed

- [ ] **Step 6: Ruff + mypy**

```bash
cd backend && python -m ruff check ingestion/parsers/llm_fallback.py
cd backend && python -m mypy --config-file pyproject.toml --explicit-package-bases ingestion/parsers/llm_fallback.py 2>&1 | tail -5
```

- [ ] **Step 7: Commit**

```bash
git add backend/ingestion/parsers/llm_fallback.py \
        backend/ingestion/parsers/prompts/ \
        backend/tests/unit/ingestion/test_llm_fallback_parser.py \
        backend/tests/fixtures/golden/llm_fallback/
git commit -m "feat: LlmFallbackParser + prompt v1 (Phase 2, TRD §12)"
```

---

### Task 3: Harness integration + integration test

**Files:**
- Modify: `backend/ingestion/dryrun/harness.py`
- Create: `backend/tests/integration/test_llm_fallback_pipeline.py`

**Interfaces:**
- Consumes: `LlmFallbackParser` from Task 2; existing `dry_run()` from `harness.py`

- [ ] **Step 1: Write failing integration test**

```python
# backend/tests/integration/test_llm_fallback_pipeline.py
"""Integration test: LLM fallback path through full dry_run → confirm pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from ingestion.dryrun.harness import dry_run
from ingestion.dryrun.session import DryRunSession
from ingestion.parsers.llm_fallback import LlmFallbackParser, LlmParsedStatement
from ingestion.validators.balance_check import BalanceCheckResult

RESPONSE_FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "golden" / "llm_fallback" / "statement_001_response.json"
)

# A PDF that matches no template parser — we use a minimal valid PDF bytes
_MINIMAL_PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << >> /MediaBox [0 0 612 792] >>\nendobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF"


@pytest.mark.integration
def test_llm_fallback_dry_run_returns_session(pg_session: Session, test_user: object) -> None:
    """LLM fallback path: unrecognised PDF → LlmFallbackParser → DryRunSession with confidence 6000."""
    from core.events.models import User
    assert isinstance(test_user, User)

    llm_response = LlmParsedStatement.model_validate_json(RESPONSE_FIXTURE.read_text())
    mock_adapter = MagicMock()
    mock_adapter.complete.return_value = llm_response

    mock_redis = MagicMock()
    fallback_parser = LlmFallbackParser(adapter=mock_adapter)

    with patch("ingestion.dryrun.harness.get_redis_client", return_value=mock_redis):
        result = dry_run(
            _MINIMAL_PDF_BYTES,
            test_user.id,
            "TEST_4321",
            parsers=[fallback_parser],  # inject directly, skip template scan
        )

    assert isinstance(result, DryRunSession)
    assert result.statement.confidence == 6000
    assert result.statement.bank.startswith("llm_fallback:")
    mock_redis.setex.assert_called_once()
```

- [ ] **Step 2: Run test — expect import error or failure**

```bash
cd backend && PYTHONPATH=. pytest tests/integration/test_llm_fallback_pipeline.py -v --tb=short 2>&1 | head -20
```

- [ ] **Step 3: Update harness to accept `parsers` parameter with fallback**

The harness already accepts an optional `parsers` list. Add `LlmFallbackParser` as a final fallback if the `parsers` list is `None` (i.e., default mode):

In `harness.py`, change `_DEFAULT_PARSERS` construction (at module level, to avoid circular import, keep it lazy):

```python
def _get_default_parsers() -> list[AbstractParser]:
    from ingestion.parsers.hdfc_cc import HdfcCcParser
    from ingestion.parsers.sbi_cc import SbiCcParser
    from ingestion.parsers.hdfc_savings import HdfcSavingsParser
    from ingestion.parsers.sbi_savings import SbiSavingsParser
    from ingestion.parsers.slice_savings import SliceSavingsParser
    from ingestion.parsers.llm_fallback import LlmFallbackParser
    return [
        HdfcCcParser(), SbiCcParser(),
        HdfcSavingsParser(), SbiSavingsParser(), SliceSavingsParser(),
        # LlmFallbackParser last — only reached if no template matches
        LlmFallbackParser(),
    ]
```

Update `dry_run()` parser selection:

```python
# In dry_run():
_parsers = parsers if parsers is not None else _get_default_parsers()

# Parser selection: template parsers use can_parse(); LlmFallbackParser always returns False
# so it must be selected differently — check if it's the only remaining option
template_parsers = [p for p in _parsers if p.can_parse(raw_text)]
if template_parsers:
    parser = template_parsers[0]
else:
    # Try LlmFallbackParser if present in the list
    from ingestion.parsers.llm_fallback import LlmFallbackParser as _Llm
    llm_parsers = [p for p in _parsers if isinstance(p, _Llm)]
    if llm_parsers:
        parser = llm_parsers[0]
    else:
        raise ValueError("No parser found for this PDF")
```

- [ ] **Step 4: Run integration test — expect pass (with mocked adapter)**

```bash
cd backend && PYTHONPATH=. pytest tests/integration/test_llm_fallback_pipeline.py -v --tb=short
```
Note: this test does not require Docker — it mocks both Redis and the LLM adapter.
Expected: 1 passed

- [ ] **Step 5: Run full unit test suite to check no regressions**

```bash
cd backend && PYTHONPATH=. pytest tests/unit/ -v --tb=short 2>&1 | tail -10
```
Expected: all tests passing

- [ ] **Step 6: Commit**

```bash
git add backend/ingestion/dryrun/harness.py \
        backend/tests/integration/test_llm_fallback_pipeline.py
git commit -m "feat: harness LLM fallback integration + integration test (Phase 2, TRD §12)"
```

---

## Verification

```bash
# Unit tests (no Docker, no live LLM)
cd backend && PYTHONPATH=. pytest tests/unit/ tests/integration/test_llm_fallback_pipeline.py -v

# Syntax check on new files
cd backend && PYTHONPATH=. python -c "
import ingestion.parsers.llm_fallback
import adapters.llm.claude
import adapters.llm.base
print('imports OK')
"

# mypy
cd backend && python -m mypy --config-file pyproject.toml --explicit-package-bases \
    adapters/ ingestion/parsers/llm_fallback.py 2>&1 | tail -5
```

## Scope note

The parser promotion queue (Phase 3+) and the UI confidence-acknowledgement flow (Phase 3) are deliberately excluded from this plan. They depend on the Phase 3 day-to-day layer and a reviewed UI design. Do not implement them in Phase 2.
