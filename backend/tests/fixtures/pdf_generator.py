"""Synthetic PDF generator for bank statement fixtures (dev-only, uses fpdf2).

ADR-007: Only synthetic data in tests. No real statements committed.
Converts a statement dict (as produced by generate_statement or loaded from golden JSON)
into PDF bytes that faithfully reproduce the target bank's column layout.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal


def format_amount_cr_dr(amount_paise: int) -> str:
    """Format a signed paise integer as 'X,XXX.XX Cr' or 'X,XXX.XX Dr'."""
    rupees = Decimal(amount_paise).quantize(Decimal("0.01")) / 100
    formatted = f"{abs(rupees):,.2f}"
    suffix = "Cr" if amount_paise >= 0 else "Dr"
    return f"{formatted} {suffix}"


def format_date_hdfc(d: date) -> str:
    """Format date as HDFC uses: 'DD/MM/YYYY HH:MM:SS' (midnight for synthetic)."""
    return d.strftime("%d/%m/%Y 00:00:00")


def format_date_sbi(d: date) -> str:
    """Format date as SBI uses: 'DD/MM/YYYY'."""
    return d.strftime("%d/%m/%Y")


def dict_to_pdf_hdfc_cc(statement: dict[str, object]) -> bytes:
    """Convert a statement dict (hdfc_cc format) to synthetic PDF bytes.

    The PDF layout reproduces HDFC Swiggy Credit Card column order:
    DATE & TIME | TRANSACTION | DESCRIPTION | AMOUNT | PI
    """
    try:
        from fpdf import FPDF
    except ImportError as e:
        raise ImportError(
            "fpdf2 is required for PDF generation. Install with: pip install fpdf2"
        ) from e

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)

    # Header
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "HDFC Bank Swiggy Credit Card", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 8, f"Account: {statement.get('account_ref', '')}", new_x="LMARGIN", new_y="NEXT")
    period_start = statement.get("period_start")
    period_end = statement.get("period_end")
    if isinstance(period_start, date) and isinstance(period_end, date):
        start_str = period_start.strftime("%d/%m/%Y")
        end_str = period_end.strftime("%d/%m/%Y")
        pdf.cell(
            0,
            8,
            f"Statement Period: {start_str} to {end_str}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
    opening = statement.get("opening_balance_paise", 0)
    closing = statement.get("closing_balance_paise", 0)
    assert isinstance(opening, int)
    assert isinstance(closing, int)
    pdf.cell(
        0,
        8,
        f"Previous Balance: {format_amount_cr_dr(opening)}",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.ln(4)

    # Table header
    pdf.set_font("Helvetica", "B", 9)
    col_widths = [38, 30, 60, 30, 20]
    headers = ["DATE & TIME", "TRANSACTION", "DESCRIPTION", "AMOUNT", "PI"]
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, border=1)
    pdf.ln()

    # Rows
    pdf.set_font("Helvetica", size=9)
    transactions = statement.get("transactions", [])
    assert isinstance(transactions, list)
    for txn in transactions:
        assert isinstance(txn, dict)
        value_date = txn.get("value_date")
        narration = str(txn.get("narration", ""))
        amount_paise_raw = txn.get("amount_paise", 0)
        assert isinstance(amount_paise_raw, int)
        assert isinstance(value_date, date)

        row = [
            format_date_hdfc(value_date),
            narration[:20],  # TRANSACTION column — short merchant name
            narration,  # DESCRIPTION — full narration
            format_amount_cr_dr(amount_paise_raw),
            "0",  # PI — reward points placeholder
        ]
        for i, cell in enumerate(row):
            pdf.cell(col_widths[i], 7, str(cell)[:30], border=1)
        pdf.ln()

    # Footer
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 8, f"New Balance: {format_amount_cr_dr(closing)}", new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())


def dict_to_pdf_sbi_cc(statement: dict[str, object]) -> bytes:
    """Convert a statement dict (sbi_cc format) to synthetic PDF bytes.

    The PDF layout reproduces SBI Credit Card column order:
    Date | Transaction Details | Amount
    """
    try:
        from fpdf import FPDF
    except ImportError as e:
        raise ImportError(
            "fpdf2 is required for PDF generation. Install with: pip install fpdf2"
        ) from e

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)

    # Header
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "State Bank of India Credit Card", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 8, f"Account: {statement.get('account_ref', '')}", new_x="LMARGIN", new_y="NEXT")
    period_start = statement.get("period_start")
    period_end = statement.get("period_end")
    if isinstance(period_start, date) and isinstance(period_end, date):
        start_str = period_start.strftime("%d/%m/%Y")
        end_str = period_end.strftime("%d/%m/%Y")
        pdf.cell(
            0,
            8,
            f"Statement Period: {start_str} to {end_str}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
    opening = statement.get("opening_balance_paise", 0)
    closing = statement.get("closing_balance_paise", 0)
    assert isinstance(opening, int)
    assert isinstance(closing, int)
    pdf.cell(
        0,
        8,
        f"Previous Balance: {format_amount_cr_dr(opening)}",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.ln(4)

    # Table header
    pdf.set_font("Helvetica", "B", 9)
    col_widths = [40, 110, 40]
    headers = ["Date", "Transaction Details", "Amount"]
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, border=1)
    pdf.ln()

    # Rows
    pdf.set_font("Helvetica", size=9)
    transactions = statement.get("transactions", [])
    assert isinstance(transactions, list)
    for txn in transactions:
        assert isinstance(txn, dict)
        value_date = txn.get("value_date")
        narration = str(txn.get("narration", ""))
        amount_paise_raw = txn.get("amount_paise", 0)
        assert isinstance(amount_paise_raw, int)
        assert isinstance(value_date, date)

        row = [
            format_date_sbi(value_date),
            narration,
            format_amount_cr_dr(amount_paise_raw),
        ]
        for i, cell in enumerate(row):
            pdf.cell(col_widths[i], 7, str(cell)[:60], border=1)
        pdf.ln()

    # Footer
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 8, f"New Balance: {format_amount_cr_dr(closing)}", new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())


def dict_to_pdf(statement: dict[str, object], bank: str) -> bytes:
    """Dispatch to bank-specific PDF generator.

    Args:
        statement: Statement dict as produced by generate_statement() or loaded from JSON
                   (with date strings converted to date objects).
        bank: One of "hdfc_cc", "sbi_cc".

    Returns:
        PDF bytes.
    """
    generators = {
        "hdfc_cc": dict_to_pdf_hdfc_cc,
        "sbi_cc": dict_to_pdf_sbi_cc,
    }
    if bank not in generators:
        raise ValueError(f"Unknown bank: {bank!r}. Known: {list(generators)}")
    return generators[bank](statement)
