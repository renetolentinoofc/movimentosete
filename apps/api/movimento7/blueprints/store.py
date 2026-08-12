import json
import secrets
from datetime import UTC, datetime, timedelta

from flask import Blueprint, current_app, request
from sqlalchemy import select

from ..extensions import db
from ..http import failure, success
from ..models import (
    Address,
    Cart,
    CartItem,
    Customer,
    IdempotencyKey,
    InventoryReservation,
    Order,
    OrderItem,
    OrderStatusHistory,
    Payment,
    Product,
    ProductMedia,
    ProductVariant,
)
from ..security import rate_limited, sha256
from ..validation import normalize_phone, parse_uuid

bp = Blueprint("store", __name__)


def product_json(product: Product, detail: bool = False) -> dict:
    variants = db.session.scalars(
        select(ProductVariant)
        .where(ProductVariant.product_id == product.id, ProductVariant.active.is_(True))
        .order_by(ProductVariant.name)
        .limit(100)
    ).all()
    media = db.session.scalars(
        select(ProductMedia)
        .where(ProductMedia.product_id == product.id, ProductMedia.active.is_(True))
        .order_by(ProductMedia.display_order)
        .limit(20)
    ).all()
    result = {
        "id": str(product.id),
        "name": product.name,
        "slug": product.slug,
        "description": product.description,
        "price_cents": product.price_cents,
        "currency": "BRL",
        "featured": product.featured,
        "available": any(v.stock_quantity - v.reserved_quantity > 0 for v in variants),
        "media": [
            {"url": m.storage_key, "alt": m.alt_text, "width": m.width, "height": m.height}
            for m in media
        ],
    }
    if detail:
        result["composition"] = product.composition
        result["variants"] = [
            {
                "id": str(v.id),
                "sku": v.sku,
                "name": v.name,
                "size": v.size,
                "color": v.color,
                "price_cents": v.price_override_cents
                if v.price_override_cents is not None
                else product.price_cents,
                "available_quantity": max(0, v.stock_quantity - v.reserved_quantity),
            }
            for v in variants
        ]
    return result


@bp.get("/products")
def products():
    rows = db.session.scalars(
        select(Product)
        .where(Product.status == "published")
        .order_by(Product.display_order)
        .limit(100)
    ).all()
    return success([product_json(row) for row in rows])


@bp.get("/products/<slug>")
def product(slug: str):
    row = db.session.scalar(
        select(Product).where(Product.slug == slug, Product.status == "published")
    )
    if not row:
        return failure("not_found", "Produto não encontrado.", status=404)
    return success(product_json(row, detail=True))


@bp.post("/carts")
def create_cart():
    raw = secrets.token_urlsafe(32)
    row = Cart(token_hash=sha256(raw), expires_at=datetime.now(UTC) + timedelta(days=14))
    db.session.add(row)
    db.session.commit()
    return success({"cart_token": raw, "expires_at": row.expires_at, "items": []}, status=201)


@bp.post("/carts/view")
def view_cart():
    body = request.get_json(silent=True) or {}
    cart = get_cart(body)
    if not cart:
        return failure("cart_invalid", "Carrinho inexistente ou expirado.", status=404)
    items = db.session.scalars(select(CartItem).where(CartItem.cart_id == cart.id).limit(100)).all()
    variants = (
        {
            row.id: row
            for row in db.session.scalars(
                select(ProductVariant).where(
                    ProductVariant.id.in_({item.variant_id for item in items})
                )
            ).all()
        }
        if items
        else {}
    )
    products = (
        {
            row.id: row
            for row in db.session.scalars(
                select(Product).where(
                    Product.id.in_({variant.product_id for variant in variants.values()})
                )
            ).all()
        }
        if variants
        else {}
    )
    data = []
    for item in items:
        variant = variants[item.variant_id]
        product_row = products[variant.product_id]
        price = (
            variant.price_override_cents
            if variant.price_override_cents is not None
            else product_row.price_cents
        )
        data.append(
            {
                "variant_id": str(variant.id),
                "product_slug": product_row.slug,
                "product_name": product_row.name,
                "variant_name": variant.name,
                "quantity": item.quantity,
                "unit_price_cents": price,
                "available_quantity": max(0, variant.stock_quantity - variant.reserved_quantity),
            }
        )
    return success(
        {
            "items": data,
            "subtotal_cents": sum(item["unit_price_cents"] * item["quantity"] for item in data),
        }
    )


def get_cart(body: dict) -> Cart | None:
    token = str(body.get("cart_token", ""))
    if not token:
        return None
    return db.session.scalar(
        select(Cart).where(
            Cart.token_hash == sha256(token),
            Cart.status == "active",
            Cart.expires_at > datetime.now(UTC),
        )
    )


@bp.put("/carts/items")
def put_cart_item():
    body = request.get_json(silent=True) or {}
    cart = get_cart(body)
    if not cart:
        return failure("cart_invalid", "Carrinho inexistente ou expirado.", status=404)
    try:
        quantity = int(body.get("quantity", 0))
    except (TypeError, ValueError):
        quantity = 0
    variant_id = parse_uuid(body.get("variant_id"))
    variant = db.session.get(ProductVariant, variant_id) if variant_id else None
    product = db.session.get(Product, variant.product_id) if variant else None
    if not variant or not variant.active or not product or product.status != "published":
        return failure("variant_unavailable", "Variação indisponível.", status=404)
    if quantity < 0 or quantity > 10:
        return failure("quantity_invalid", "Escolha uma quantidade entre 0 e 10.", status=422)
    item = db.session.scalar(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.variant_id == variant.id)
    )
    if quantity == 0 and item:
        db.session.delete(item)
    elif quantity:
        if quantity > variant.stock_quantity - variant.reserved_quantity:
            return failure("out_of_stock", "Quantidade indisponível em estoque.", status=409)
        if item:
            item.quantity = quantity
        else:
            db.session.add(CartItem(cart_id=cart.id, variant_id=variant.id, quantity=quantity))
    db.session.commit()
    return success({"updated": True})


@bp.post("/checkout")
def checkout():
    if rate_limited("checkout", 10, 3600):
        db.session.rollback()
        return failure("rate_limited", "Muitas tentativas. Tente novamente mais tarde.", status=429)
    idempotency = request.headers.get("Idempotency-Key", "").strip()
    if not 8 <= len(idempotency) <= 100:
        return failure(
            "idempotency_required", "Informe uma chave de idempotência válida.", status=400
        )
    key_hash = sha256(idempotency)
    existing = db.session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.scope == "checkout", IdempotencyKey.key_hash == key_hash
        )
    )
    if existing:
        payload = json.loads(existing.response_json or "{}")
        payload["replayed"] = True
        return success(payload, status=existing.response_status or 200)
    body = request.get_json(silent=True) or {}
    cart = get_cart(body)
    if not cart:
        return failure("cart_invalid", "Carrinho inexistente ou expirado.", status=404)
    items = db.session.scalars(select(CartItem).where(CartItem.cart_id == cart.id).limit(100)).all()
    if not items:
        return failure("cart_empty", "O carrinho está vazio.", status=422)
    customer_data = body.get("customer") or {}
    address_data = body.get("address") or {}
    required_customer = ("name", "email", "phone")
    required_address = (
        "recipient_name",
        "postal_code",
        "street",
        "number",
        "neighborhood",
        "city",
        "state",
    )
    fields = {
        f"customer.{key}": ["Campo obrigatório."]
        for key in required_customer
        if not str(customer_data.get(key, "")).strip()
    }
    fields.update(
        {
            f"address.{key}": ["Campo obrigatório."]
            for key in required_address
            if not str(address_data.get(key, "")).strip()
        }
    )
    if body.get("terms_accepted") is not True:
        fields["terms_accepted"] = ["Aceite os termos para criar o pedido."]
    phone = normalize_phone(str(customer_data.get("phone", "")))
    if not phone:
        fields["customer.phone"] = ["WhatsApp inválido."]
    if fields:
        return failure(
            "validation_error", "Revise os campos informados.", status=422, fields=fields
        )
    variant_ids = sorted({item.variant_id for item in items}, key=str)
    variants = {
        row.id: row
        for row in db.session.scalars(
            select(ProductVariant).where(ProductVariant.id.in_(variant_ids)).with_for_update()
        ).all()
    }
    products = {
        row.id: row
        for row in db.session.scalars(
            select(Product).where(Product.id.in_({v.product_id for v in variants.values()}))
        ).all()
    }
    subtotal = 0
    for item in items:
        variant = variants.get(item.variant_id)
        product_row = products.get(variant.product_id) if variant else None
        if (
            not variant
            or not variant.active
            or not product_row
            or product_row.status != "published"
        ):
            db.session.rollback()
            return failure("variant_unavailable", "Um item não está mais disponível.", status=409)
        if item.quantity > variant.stock_quantity - variant.reserved_quantity:
            db.session.rollback()
            return failure(
                "out_of_stock", f"Estoque insuficiente para {product_row.name}.", status=409
            )
        subtotal += (
            variant.price_override_cents
            if variant.price_override_cents is not None
            else product_row.price_cents
        ) * item.quantity
    customer = Customer(
        name=str(customer_data["name"]).strip(),
        email=str(customer_data["email"]).strip().lower(),
        phone_e164=phone,
    )
    db.session.add(customer)
    db.session.flush()
    address = Address(
        customer_id=customer.id,
        recipient_name=str(address_data["recipient_name"]).strip(),
        postal_code=str(address_data["postal_code"]).strip(),
        street=str(address_data["street"]).strip(),
        number=str(address_data["number"]).strip(),
        complement=str(address_data.get("complement", "")).strip() or None,
        neighborhood=str(address_data["neighborhood"]).strip(),
        city=str(address_data["city"]).strip(),
        state=str(address_data["state"]).strip().upper(),
    )
    db.session.add(address)
    db.session.flush()
    access_token = secrets.token_urlsafe(32)
    order = Order(
        public_code=f"PED-{datetime.now(UTC):%y%m}-{secrets.token_hex(3).upper()}",
        access_token_hash=sha256(access_token),
        customer_id=customer.id,
        address_id=address.id,
        subtotal_cents=subtotal,
        shipping_cents=0,
        total_cents=subtotal,
        terms_version=str(body.get("terms_version", "2026-08-draft")),
        terms_accepted_at=datetime.now(UTC),
    )
    db.session.add(order)
    db.session.flush()
    expires_at = datetime.now(UTC) + timedelta(
        minutes=current_app.config["ORDER_RESERVATION_MINUTES"]
    )
    for item in items:
        variant = variants[item.variant_id]
        product_row = products[variant.product_id]
        price = (
            variant.price_override_cents
            if variant.price_override_cents is not None
            else product_row.price_cents
        )
        variant.reserved_quantity += item.quantity
        db.session.add(
            OrderItem(
                order_id=order.id,
                product_id=product_row.id,
                variant_id=variant.id,
                product_name_snapshot=product_row.name,
                sku_snapshot=variant.sku,
                variant_snapshot=variant.name,
                unit_price_cents=price,
                quantity=item.quantity,
            )
        )
        db.session.add(
            InventoryReservation(
                variant_id=variant.id,
                order_id=order.id,
                quantity=item.quantity,
                expires_at=expires_at,
            )
        )
    db.session.add(
        Payment(
            order_id=order.id,
            provider=current_app.config["PAYMENT_PROVIDER"],
            status="pending_manual",
            amount_cents=order.total_cents,
            idempotency_key=idempotency,
        )
    )
    db.session.add(
        OrderStatusHistory(
            order_id=order.id,
            old_status=None,
            new_status="pending_payment",
            reason="Pedido criado; pagamento ainda não confirmado",
            created_at=datetime.now(UTC),
        )
    )
    replay_payload = {
        "order_code": order.public_code,
        "status": order.status,
        "payment_status": order.payment_status,
        "total_cents": order.total_cents,
    }
    db.session.add(
        IdempotencyKey(
            scope="checkout",
            key_hash=key_hash,
            request_hash=sha256(str(cart.id)),
            response_status=201,
            response_json=json.dumps(replay_payload),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            created_at=datetime.now(UTC),
        )
    )
    cart.status = "converted"
    db.session.commit()
    return success(
        {
            "order_code": order.public_code,
            "access_token": access_token,
            "status": order.status,
            "payment_status": order.payment_status,
            "payment_provider": current_app.config["PAYMENT_PROVIDER"],
            "total_cents": order.total_cents,
            "reservation_expires_at": expires_at,
            "message": "Pedido criado. Nenhum pagamento foi aprovado automaticamente.",
        },
        status=201,
    )


@bp.get("/orders/<code>")
def order_status(code: str):
    token = request.args.get("token", "")
    row = db.session.scalar(select(Order).where(Order.public_code == code))
    if not row or not token or row.access_token_hash != sha256(token):
        return failure("not_found", "Pedido não encontrado.", status=404)
    return success(
        {
            "order_code": row.public_code,
            "status": row.status,
            "payment_status": row.payment_status,
            "subtotal_cents": row.subtotal_cents,
            "shipping_cents": row.shipping_cents,
            "total_cents": row.total_cents,
            "created_at": row.created_at,
        }
    )
