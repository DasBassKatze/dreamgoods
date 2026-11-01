"""Точные денежные расчёты; наружу остаются обычные JSON-числа."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def decimal(value):
    try:
        result = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("неверная денежная сумма") from None
    if not result.is_finite():
        raise ValueError("денежная сумма должна быть конечным числом")
    return result


def money(value, places=2):
    try:
        result = decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError("слишком большая денежная сумма") from None
    if abs(result) >= Decimal("1000000000000"):
        raise ValueError("слишком большая денежная сумма")
    return float(result)
