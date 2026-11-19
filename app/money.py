from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MAX_AMOUNT = Decimal("1000000")


def parse_amount(text):
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
    return f"${cents / 100:,.2f}"
