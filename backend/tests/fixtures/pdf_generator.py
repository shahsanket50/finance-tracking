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


def dict_to_pdf_hdfc_savings(statement: dict[str, object]) -> bytes:
    """Convert a statement dict (hdfc_savings format) to synthetic PDF bytes.

    The PDF layout reproduces the HDFC Savings column format:
    Date | Narration | Chq./Ref.No. | ValueDt | WithdrawalAmt. | DepositAmt. | ClosingBalance

    Key PDF characteristics that can_parse relies on:
    - Header line: "StatementFrom : DD/MM/YYYY To : DD/MM/YYYY" (no space in "StatementFrom")
    - Column header line with "WithdrawalAmt." and "DepositAmt." (no spaces around dots)
    - Account line: "AccountNo : XXXXXXXXXXX"
    - Text-extracted (not table-based) — use plain text cells, not borders
    - Transaction date format: DD/MM/YY (two-digit year)
    - Each row includes a synthetic reference number (REF001, REF002, ...) in Chq./Ref.No.
      so the parser's ROW_RE can unambiguously split narration from ValueDt.
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

    # Header block
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "HDFC Bank - Statement of Account", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    # "AccountNo" (no space) — parser regex: AccountNo\s*:\s*(\S+)
    pdf.cell(0, 8, f"AccountNo : {statement.get('account_ref', '')}", new_x="LMARGIN", new_y="NEXT")

    period_start = statement.get("period_start")
    period_end = statement.get("period_end")
    if isinstance(period_start, date) and isinstance(period_end, date):
        start_str = period_start.strftime("%d/%m/%Y")
        end_str = period_end.strftime("%d/%m/%Y")
        # "StatementFrom" (no space) — required for can_parse
        pdf.cell(
            0,
            8,
            f"StatementFrom : {start_str} To : {end_str}",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    pdf.ln(4)

    # Column header — WithdrawalAmt. and DepositAmt. must appear verbatim for can_parse
    pdf.set_font("Helvetica", "B", 8)
    col_widths = [22, 50, 22, 22, 28, 25, 31]
    headers = [
        "Date",
        "Narration",
        "Chq./Ref.No.",
        "ValueDt",
        "WithdrawalAmt.",
        "DepositAmt.",
        "ClosingBalance",
    ]
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, border=1)
    pdf.ln()

    # Rows — transaction dates use DD/MM/YY (two-digit year)
    pdf.set_font("Helvetica", size=8)
    transactions = statement.get("transactions", [])
    assert isinstance(transactions, list)
    for seq, txn in enumerate(transactions, start=1):
        assert isinstance(txn, dict)
        value_date = txn.get("value_date")
        narration = str(txn.get("narration", ""))
        amount_paise_raw = txn.get("amount_paise", 0)
        # Support both field names: spec uses running_balance_paise
        running_paise = txn.get("running_balance_paise", txn.get("closing_balance_paise", 0))
        assert isinstance(amount_paise_raw, int)
        assert isinstance(running_paise, int)
        assert isinstance(value_date, date)

        date_str = value_date.strftime("%d/%m/%y")  # two-digit year
        ref_no = f"REF{seq:03d}"
        closing_str = f"{abs(Decimal(running_paise)) / 100:,.2f}"

        if amount_paise_raw >= 0:
            withdrawal_str = ""
            deposit_str = f"{Decimal(amount_paise_raw) / 100:,.2f}"
        else:
            withdrawal_str = f"{abs(Decimal(amount_paise_raw)) / 100:,.2f}"
            deposit_str = ""

        row = [date_str, narration[:35], ref_no, date_str, withdrawal_str, deposit_str, closing_str]
        for i, cell in enumerate(row):
            pdf.cell(col_widths[i], 7, str(cell)[:35], border=1)
        pdf.ln()

    return bytes(pdf.output())


def dict_to_pdf_sbi_savings(statement: dict[str, object]) -> bytes:
    """Convert a statement dict (sbi_savings format) to synthetic PDF bytes.

    Layout reproduces SBI Savings column order (table-based):
    Txn Date | Value Date | Description | Ref No./Cheque No. | Debit | Credit | Balance
    Header: "Balance as on DD Mon YYYY : X,XXX.XX"
    Header: "Account Statement from DD Mon YYYY to DD Mon YYYY"
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

    # Header block
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "State Bank of India - Savings Account Statement", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)

    account_ref = statement.get("account_ref", "")
    pdf.cell(0, 8, f"Account Number : {account_ref}", new_x="LMARGIN", new_y="NEXT")

    period_start = statement.get("period_start")
    period_end = statement.get("period_end")
    if isinstance(period_start, date) and isinstance(period_end, date):
        start_str = period_start.strftime("%d %b %Y")
        end_str = period_end.strftime("%d %b %Y")
        pdf.cell(
            0,
            8,
            f"Account Statement from {start_str} to {end_str}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        # Opening balance line — uses period_start date
        opening = statement.get("opening_balance_paise", 0)
        assert isinstance(opening, int)
        opening_str = f"{abs(Decimal(opening)) / Decimal('100'):,.2f}"
        pdf.cell(
            0,
            8,
            f"Balance as on {start_str} : {opening_str}",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    pdf.ln(4)

    # Table header
    pdf.set_font("Helvetica", "B", 8)
    col_widths = [22, 22, 55, 25, 22, 22, 22]
    headers = [
        "Txn Date",
        "Value Date",
        "Description",
        "Ref No./Cheque No.",
        "Debit",
        "Credit",
        "Balance",
    ]
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, border=1)
    pdf.ln()

    # Rows
    pdf.set_font("Helvetica", size=8)
    transactions = statement.get("transactions", [])
    assert isinstance(transactions, list)
    for seq, txn in enumerate(transactions, start=1):
        assert isinstance(txn, dict)
        value_date = txn.get("value_date")
        narration = str(txn.get("narration", ""))
        amount_paise_raw = txn.get("amount_paise", 0)
        running_paise = txn.get("running_balance_paise", 0)
        assert isinstance(amount_paise_raw, int)
        assert isinstance(running_paise, int)
        assert isinstance(value_date, date)

        # Date cell: "DD Mon\nYYYY" — pdfplumber extracts newline from multi-line table cells
        date_str = value_date.strftime("%d %b\n%Y")
        ref_no = f"REF{seq:06d}"
        balance_str = f"{abs(Decimal(running_paise)) / Decimal('100'):,.2f}"

        if amount_paise_raw >= 0:
            debit_str = ""
            credit_str = f"{Decimal(amount_paise_raw) / Decimal('100'):,.2f}"
        else:
            debit_str = f"{abs(Decimal(amount_paise_raw)) / Decimal('100'):,.2f}"
            credit_str = ""

        row = [date_str, date_str, narration[:40], ref_no, debit_str, credit_str, balance_str]
        for i, cell in enumerate(row):
            # Use multi_cell for Txn Date / Value Date to get the newline rendering
            if i in (0, 1):
                pdf.multi_cell(col_widths[i], 4, str(cell), border=1, new_x="RIGHT", new_y="TOP")
            else:
                pdf.cell(col_widths[i], 8, str(cell)[:35], border=1)
        pdf.ln()

    return bytes(pdf.output())


def dict_to_pdf(statement: dict[str, object], bank: str) -> bytes:
    """Dispatch to bank-specific PDF generator.

    Args:
        statement: Statement dict as produced by generate_statement() or loaded from JSON
                   (with date strings converted to date objects).
        bank: One of "hdfc_cc", "sbi_cc", "hdfc_savings", "sbi_savings".

    Returns:
        PDF bytes.
    """
    generators = {
        "hdfc_cc": dict_to_pdf_hdfc_cc,
        "sbi_cc": dict_to_pdf_sbi_cc,
        "hdfc_savings": dict_to_pdf_hdfc_savings,
        "sbi_savings": dict_to_pdf_sbi_savings,
    }
    if bank not in generators:
        raise ValueError(f"Unknown bank: {bank!r}. Known: {list(generators)}")
    return generators[bank](statement)
