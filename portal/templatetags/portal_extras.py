"""Small presentation-only template helpers.

These do formatting, never analysis -- all figures arrive already computed from
portal/analytics.py.
"""

from django import template

register = template.Library()

# Schedule variance, in points, that fills the full half-width of an inline bar.
# Anything worse is clipped rather than allowed to overflow its cell.
VARIANCE_FULL_SCALE = 40.0
BAR_HALF_WIDTH_PX = 52.0


@register.filter
def abs_val(value):
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return 0


@register.filter
def var_width(value):
    """Pixel width of an inline variance bar, clipped at the half-width."""
    try:
        magnitude = abs(float(value))
    except (TypeError, ValueError):
        return 0
    return round(min(magnitude / VARIANCE_FULL_SCALE, 1.0) * BAR_HALF_WIDTH_PX, 1)


@register.filter
def money(value):
    """Compact currency formatting: 1,750,000 -> 1.75M."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.2f}M"
    if amount >= 1_000:
        return f"{amount / 1_000:.0f}K"
    return f"{amount:.0f}"


@register.filter
def signed(value, places=1):
    """Render a number with an explicit + or - so variance never reads ambiguously."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{number:+.{int(places)}f}"
