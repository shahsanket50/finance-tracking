"""PDF reader: wraps pdfplumber.open() with password handling. Implements TRD §9.1."""

from __future__ import annotations

import io
from typing import Any

import pdfplumber


class PasswordRequiredError(Exception):
    """PDF is encrypted and no password was provided."""


class PasswordIncorrectError(Exception):
    """PDF is encrypted and the supplied password is wrong."""


def open_pdf(pdf_bytes: bytes, password: str | None = None) -> pdfplumber.PDF:  # type: ignore[name-defined]
    """Open a PDF from raw bytes, optionally decrypting with password.

    Raises:
        PasswordRequiredError: PDF is encrypted, no password given.
        PasswordIncorrectError: PDF is encrypted, password is wrong.
        pdfplumber.PDFSyntaxError or similar: malformed/garbage PDF — let caller handle.
    """
    kwargs: dict[str, Any] = {}
    if password is not None:
        kwargs["password"] = password

    try:
        return pdfplumber.open(io.BytesIO(pdf_bytes), **kwargs)
    except Exception as exc:
        # pdfminer wraps PDFPasswordIncorrect in PdfminerException with an empty
        # message — check the __context__ chain for the real cause before falling
        # back to string-matching (which covers older pdfminer versions that did
        # embed the class name in the message).
        ctx: BaseException | None = exc.__context__
        ctx_name = type(ctx).__name__ if ctx is not None else ""
        is_pdf_password_incorrect = (
            ctx_name == "PDFPasswordIncorrect" or "PDFPasswordIncorrect" in ctx_name
        )

        if is_pdf_password_incorrect:
            if password is None:
                raise PasswordRequiredError("PDF requires a password") from exc
            raise PasswordIncorrectError("PDF password is incorrect") from exc

        # Fallback: older pdfminer versions that embed the class name in str(exc)
        exc_str = str(exc).lower()
        if "password" in exc_str and "incorrect" in exc_str:
            raise PasswordIncorrectError("PDF password is incorrect") from exc
        if "encrypt" in exc_str or ("password" in exc_str and password is None):
            raise PasswordRequiredError("PDF requires a password") from exc

        # For other errors (garbage bytes, truncated file, image-only, etc.)
        # re-raise as-is so the caller can map to IngestionEvent(failed)
        raise
