from dataclasses import dataclass

from flask import current_app


@dataclass(frozen=True)
class ShippingQuote:
    method: str
    label: str
    shipping_cents: int
    currency: str = "BRL"
    estimated_days: int | None = None
    free_shipping: bool = False


def quote_shipping(*, subtotal_cents: int, postal_code: str, state: str) -> ShippingQuote:
    """Return the configured manual quote until a carrier integration is enabled."""
    normalized_postal_code = "".join(character for character in postal_code if character.isdigit())
    if len(normalized_postal_code) != 8:
        raise ValueError("Informe um CEP válido.")
    if not state or len(state.strip()) != 2:
        raise ValueError("Informe uma UF válida.")
    free_threshold = current_app.config["SHIPPING_FREE_THRESHOLD_CENTS"]
    is_free = free_threshold > 0 and subtotal_cents >= free_threshold
    return ShippingQuote(
        method=current_app.config["SHIPPING_METHOD"],
        label=current_app.config["SHIPPING_LABEL"],
        shipping_cents=0 if is_free else current_app.config["SHIPPING_FLAT_RATE_CENTS"],
        estimated_days=current_app.config["SHIPPING_ESTIMATED_DAYS"],
        free_shipping=is_free,
    )
