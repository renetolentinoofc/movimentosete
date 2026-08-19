from datetime import UTC, datetime, timedelta
from uuid import UUID

from werkzeug.security import generate_password_hash
from sqlalchemy import select

from movimento7.extensions import db
from movimento7.models import (
    Address,
    AdminUser,
    Customer,
    CommunicationLog,
    Order,
    OrderItem,
    Payment,
    Permission,
    Product,
    ProductMedia,
    ProductVariant,
    Role,
    InventoryReservation,
)
from movimento7.services.inventory import expire_inventory_reservations


def create_admin(app):
    with app.app_context():
        permissions = [
            Permission(slug=slug, description=slug)
            for slug in ("store.manage", "orders.manage", "payments.manage")
        ]
        role = Role(slug="loja", name="Loja", permissions=permissions)
        admin = AdminUser(
            email="store-admin@example.test",
            name="Operador da Loja",
            password_hash=generate_password_hash("senha-segura-teste"),
            roles=[role],
        )
        db.session.add_all([admin, *permissions])
        db.session.commit()


def login(client):
    response = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "store-admin@example.test", "password": "senha-segura-teste"},
    )
    assert response.status_code == 200
    return response.json["data"]["csrf_token"]


def test_product_lifecycle_and_order_operation(app, client):
    create_admin(app)
    csrf = login(client)
    created = client.post(
        "/api/v1/admin/products",
        json={"name": "Camiseta Teste", "slug": "camiseta-teste", "price_cents": 12000},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    product_id = created.json["data"]["id"]
    variant = client.post(
        f"/api/v1/admin/products/{product_id}/variants",
        json={"sku": "TESTE-P", "name": "Tamanho P", "stock_quantity": 2},
        headers={"X-CSRF-Token": csrf},
    )
    assert variant.status_code == 201
    with app.app_context():
        product = db.session.get(Product, UUID(product_id))
        variant_row = db.session.scalar(
            select(ProductVariant).where(ProductVariant.sku == "TESTE-P")
        )
        db.session.add(
            ProductMedia(
                product_id=product.id,
                provider="local",
                storage_key="products/teste.webp",
                alt_text="Camiseta de teste",
            )
        )
        db.session.commit()
        product_uuid = product.id
        product_name = product.name
        variant_uuid = variant_row.id
        variant_sku = variant_row.sku
        variant_name = variant_row.name
    published = client.patch(
        f"/api/v1/admin/products/{product_id}/status",
        json={"status": "published"},
        headers={"X-CSRF-Token": csrf},
    )
    assert published.status_code == 200
    adjusted = client.patch(
        f"/api/v1/admin/products/{product_id}/variants/{variant_uuid}",
        json={"stock_quantity": 3},
        headers={"X-CSRF-Token": csrf},
    )
    assert adjusted.status_code == 200
    movements = client.get("/api/v1/admin/inventory/movements")
    assert movements.status_code == 200
    assert movements.json["data"][0]["quantity_delta"] == 1

    with app.app_context():
        customer = Customer(
            name="Cliente", email="cliente@example.test", phone_e164="5511999999999"
        )
        db.session.add(customer)
        db.session.flush()
        address = Address(
            customer_id=customer.id,
            recipient_name="Cliente",
            postal_code="01001000",
            street="Rua Teste",
            number="10",
            neighborhood="Centro",
            city="São Paulo",
            state="SP",
        )
        db.session.add(address)
        db.session.flush()
        order = Order(
            public_code="PED-TESTE-001",
            access_token_hash="a" * 64,
            customer_id=customer.id,
            address_id=address.id,
            subtotal_cents=12000,
            total_cents=12000,
            terms_version="test",
            terms_accepted_at=datetime.now(UTC),
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(
            OrderItem(
                order_id=order.id,
                product_id=product_uuid,
                variant_id=variant_uuid,
                product_name_snapshot=product_name,
                sku_snapshot=variant_sku,
                variant_snapshot=variant_name,
                unit_price_cents=12000,
                quantity=1,
            )
        )
        db.session.add(
            InventoryReservation(
                variant_id=variant_uuid,
                order_id=order.id,
                quantity=1,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        variant_for_order = db.session.get(ProductVariant, variant_uuid)
        variant_for_order.reserved_quantity = 1
        db.session.add(
            Payment(
                order_id=order.id,
                provider="manual",
                status="pending_manual",
                amount_cents=12000,
                idempotency_key="order-test-payment",
            )
        )
        db.session.commit()
        order_id = str(order.id)
    listing = client.get("/api/v1/admin/orders")
    assert listing.status_code == 200
    paid = client.patch(
        f"/api/v1/admin/orders/{order_id}/payment",
        json={"status": "paid"},
        headers={"X-CSRF-Token": csrf},
    )
    assert paid.status_code == 200
    assert paid.json["data"]["status"] == "processing"
    with app.app_context():
        variant_row = db.session.scalar(
            select(ProductVariant).where(ProductVariant.sku == "TESTE-P")
        )
        assert variant_row.stock_quantity == 2
        assert variant_row.reserved_quantity == 0
    shipped = client.patch(
        f"/api/v1/admin/orders/{order_id}/status",
        json={"status": "shipped"},
        headers={"X-CSRF-Token": csrf},
    )
    assert shipped.status_code == 200
    delivered = client.patch(
        f"/api/v1/admin/orders/{order_id}/status",
        json={"status": "delivered"},
        headers={"X-CSRF-Token": csrf},
    )
    assert delivered.status_code == 200


def test_expire_inventory_reservations_releases_stock(app):
    with app.app_context():
        app.config.update(
            EMAIL_DELIVERY_MODE="log",
            EMAIL_FROM_ADDRESS="movimento7@example.test",
        )
        product = Product(
            name="Produto Expirável",
            slug="produto-expiravel",
            description="Teste",
            price_cents=1000,
        )
        variant = ProductVariant(
            sku="EXP-P", name="P", stock_quantity=3, reserved_quantity=2
        )
        customer = Customer(
            name="Cliente", email="expire@example.test", phone_e164="5511999999999"
        )
        db.session.add_all([product, customer])
        db.session.flush()
        variant.product_id = product.id
        db.session.add(variant)
        db.session.flush()
        address = Address(
            customer_id=customer.id,
            recipient_name="Cliente",
            postal_code="01001000",
            street="Rua Teste",
            number="10",
            neighborhood="Centro",
            city="São Paulo",
            state="SP",
        )
        db.session.add(address)
        db.session.flush()
        order = Order(
            public_code="PED-EXP-001",
            access_token_hash="b" * 64,
            customer_id=customer.id,
            address_id=address.id,
            subtotal_cents=1000,
            total_cents=1000,
            terms_version="test",
            terms_accepted_at=datetime.now(UTC),
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(
            InventoryReservation(
                variant_id=variant.id,
                order_id=order.id,
                quantity=2,
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        db.session.commit()
        summary = expire_inventory_reservations()
        db.session.refresh(order)
        db.session.refresh(variant)
        assert summary == {
            "reservations_found": 1,
            "released_units": 2,
            "orders_expired": 1,
        }
        assert order.status == "expired"
        assert order.payment_status == "expired"
        assert variant.reserved_quantity == 0
        communication = db.session.scalar(select(CommunicationLog))
        assert communication.template_key == "order_status_expired"
        assert communication.status == "logged"
