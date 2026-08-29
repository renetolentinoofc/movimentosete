from dataclasses import dataclass
from typing import Any

import requests
from flask import current_app


@dataclass(frozen=True)
class ShippingQuote:
    method: str
    label: str
    shipping_cents: int
    currency: str = "BRL"
    estimated_days: int | None = None
    free_shipping: bool = False
    provider_reference: str | None = None


class ShippingProviderError(RuntimeError):
    pass


def _validate_destination(postal_code: str, state: str) -> tuple[str, str]:
    normalized = "".join(character for character in postal_code if character.isdigit())
    normalized_state = state.strip().upper()
    if len(normalized) != 8:
        raise ValueError("Informe um CEP válido.")
    if len(normalized_state) != 2 or not normalized_state.isalpha():
        raise ValueError("Informe uma UF válida.")
    allowed_states = {
        item.strip().upper()
        for item in str(current_app.config.get("SHIPPING_ALLOWED_STATES", "")).split(",")
        if item.strip()
    }
    if allowed_states and normalized_state not in allowed_states:
        raise ValueError("Ainda não atendemos esta região.")
    return normalized, normalized_state


def _manual_quote(subtotal_cents: int) -> ShippingQuote:
    free_threshold = current_app.config["SHIPPING_FREE_THRESHOLD_CENTS"]
    is_free = free_threshold > 0 and subtotal_cents >= free_threshold
    return ShippingQuote(
        method=current_app.config["SHIPPING_METHOD"],
        label=current_app.config["SHIPPING_LABEL"],
        shipping_cents=0 if is_free else current_app.config["SHIPPING_FLAT_RATE_CENTS"],
        estimated_days=current_app.config["SHIPPING_ESTIMATED_DAYS"],
        free_shipping=is_free,
    )


def _melhor_envio_quote(
    *, subtotal_cents: int, postal_code: str, state: str, products: list[dict[str, Any]]
) -> ShippingQuote:
    token = str(current_app.config.get("MELHOR_ENVIO_ACCESS_TOKEN", "")).strip()
    if not token:
        raise ShippingProviderError("MELHOR_ENVIO_ACCESS_TOKEN não configurado")
    default_product = {
        "weight": current_app.config["SHIPPING_DEFAULT_WEIGHT_KG"],
        "width": current_app.config["SHIPPING_DEFAULT_WIDTH_CM"],
        "height": current_app.config["SHIPPING_DEFAULT_HEIGHT_CM"],
        "length": current_app.config["SHIPPING_DEFAULT_LENGTH_CM"],
    }
    items = [
        {**default_product, **product}
        for product in products
    ] or [
        {
            "id": "movimento7-order",
            **default_product,
            "quantity": 1,
            "insurance_value": subtotal_cents / 100,
        }
    ]
    try:
        response = requests.post(
            f"{current_app.config['MELHOR_ENVIO_API_BASE_URL']}/shipment/calculate",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": current_app.config["MELHOR_ENVIO_USER_AGENT"],
            },
            json={
                "from": {"postal_code": current_app.config["SHIPPING_ORIGIN_POSTAL_CODE"]},
                "to": {"postal_code": postal_code, "state_abbr": state},
                "products": items,
                "options": {"receipt": False, "own_hand": False, "collect": False},
            },
            timeout=10,
        )
        response.raise_for_status()
        options = response.json()
    except (requests.RequestException, ValueError) as error:
        raise ShippingProviderError("Não foi possível obter cotação no Melhor Envio") from error
    if not isinstance(options, list):
        raise ShippingProviderError("Resposta inválida do Melhor Envio")
    available = [option for option in options if option.get("error") is None]
    if not available:
        raise ShippingProviderError("Nenhuma opção de entrega disponível para este CEP")
    selected = min(
        available,
        key=lambda option: float(option.get("custom_price") or option.get("price") or 0),
    )
    price = float(selected.get("custom_price") or selected.get("price") or 0)
    days = selected.get("custom_delivery_time") or selected.get("delivery_time")
    company = selected.get("company") or {}
    return ShippingQuote(
        method="melhor_envio",
        label=str(selected.get("name") or company.get("name") or "Entrega"),
        shipping_cents=round(price * 100),
        estimated_days=int(days) if days is not None else None,
        provider_reference=str(selected.get("id")) if selected.get("id") else None,
    )


def quote_shipping(
    *,
    subtotal_cents: int,
    postal_code: str,
    state: str,
    fulfillment_method: str = "delivery",
    products: list[dict[str, Any]] | None = None,
) -> ShippingQuote:
    """Cota entrega/retirada e aplica as regras de região configuradas."""
    normalized_postal_code, normalized_state = _validate_destination(postal_code, state)
    if fulfillment_method == "pickup":
        if not current_app.config["SHIPPING_PICKUP_ENABLED"]:
            raise ValueError("Retirada no local não está disponível.")
        return ShippingQuote(
            method="pickup",
            label=current_app.config["SHIPPING_PICKUP_LABEL"],
            shipping_cents=0,
            estimated_days=0,
            free_shipping=True,
        )
    if fulfillment_method != "delivery":
        raise ValueError("Método de entrega inválido.")
    if current_app.config["SHIPPING_PROVIDER"] == "melhor_envio":
        return _melhor_envio_quote(
            subtotal_cents=subtotal_cents,
            postal_code=normalized_postal_code,
            state=normalized_state,
            products=products or [],
        )
    return _manual_quote(subtotal_cents)
