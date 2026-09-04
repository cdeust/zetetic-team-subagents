"""Synthetic fixture for the `test` bench task: a small pure function with
edge cases a test plan should surface. Fixed benchmark input only."""


def calculate_discount(price: float, pct: float, is_member: bool) -> float:
    """Return the discounted price.

    pct is a fraction in [0, 1]. Members get an extra flat 5-currency-unit
    discount applied after the percentage discount, but the result never
    goes below zero.
    """
    if price < 0:
        raise ValueError("price must be non-negative")
    if not (0 <= pct <= 1):
        raise ValueError("pct must be within [0, 1]")

    discounted = price * (1 - pct)
    if is_member:
        discounted -= 5
    return max(discounted, 0.0)
