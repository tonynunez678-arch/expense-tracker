"""Helpers for converting between user-typed amounts and integer cents."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MAX_AMOUNT = Decimal("1000000")


def parse_amount(text):
    """Turn text like "$1,234.50" into integer cents (123450).

    Raises ValueError with a user-friendly message if the input is invalid.
    """
    cleaned = (text or "").strip().replace("$", "").replace(",", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError("Amount must be a number, like 12.50.") from None

    if not value.is_finite() or value <= 0:
        raise ValueError("Amount must be greater than 0.")
    if value > MAX_AMOUNT:
        raise ValueError("Amount must be $1,000,000 or less.")

    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_cents(cents):
    """Turn integer cents (123450) into display text ("$1,234.50")."""
    return f"${cents / 100:,.2f}"
