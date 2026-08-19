from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db
from .base import TimestampMixin, UUIDPrimaryKeyMixin


class Collection(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "collections"
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Product(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price_cents >= 0", name="ck_products_price_nonnegative"),
        Index("ix_products_status_order", "status", "display_order"),
    )
    collection_id: Mapped[UUID | None] = mapped_column(ForeignKey("collections.id"), index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    composition: Mapped[str | None] = mapped_column(String(500))
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ProductVariant(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "product_variants"
    __table_args__ = (
        CheckConstraint("stock_quantity >= 0", name="ck_variants_stock_nonnegative"),
        CheckConstraint("reserved_quantity >= 0", name="ck_variants_reserved_nonnegative"),
        CheckConstraint(
            "reserved_quantity <= stock_quantity", name="ck_variants_reserved_within_stock"
        ),
    )
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    size: Mapped[str | None] = mapped_column(String(40))
    color: Mapped[str | None] = mapped_column(String(60))
    price_override_cents: Mapped[int | None] = mapped_column(Integer)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ProductMedia(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "product_media"
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    alt_text: Mapped[str] = mapped_column(String(180), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Cart(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "carts"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active", index=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class CartItem(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "cart_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_cart_items_quantity_positive"),
        Index("ix_cart_item_unique_active", "cart_id", "variant_id"),
    )
    cart_id: Mapped[UUID] = mapped_column(ForeignKey("carts.id"), nullable=False)
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("product_variants.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "customers"
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    email: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False)


class Address(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "addresses"
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    recipient_name: Mapped[str] = mapped_column(String(140), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(12), nullable=False)
    street: Mapped[str] = mapped_column(String(180), nullable=False)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    complement: Mapped[str | None] = mapped_column(String(120))
    neighborhood: Mapped[str] = mapped_column(String(100), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)


class Order(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("subtotal_cents >= 0", name="ck_orders_subtotal_nonnegative"),
        CheckConstraint("shipping_cents >= 0", name="ck_orders_shipping_nonnegative"),
        CheckConstraint("total_cents >= 0", name="ck_orders_total_nonnegative"),
        Index("ix_orders_status_created", "status", "created_at"),
    )
    public_code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    access_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    address_id: Mapped[UUID | None] = mapped_column(ForeignKey("addresses.id"))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending_payment")
    payment_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    fulfillment_method: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    subtotal_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    shipping_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    terms_version: Mapped[str] = mapped_column(String(30), nullable=False)
    terms_accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OrderItem(UUIDPrimaryKeyMixin, db.Model):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        CheckConstraint("unit_price_cents >= 0", name="ck_order_items_price_nonnegative"),
    )
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id"))
    variant_id: Mapped[UUID | None] = mapped_column(ForeignKey("product_variants.id"))
    product_name_snapshot: Mapped[str] = mapped_column(String(180), nullable=False)
    sku_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    variant_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)


class InventoryReservation(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "inventory_reservations"
    __table_args__ = (Index("ix_inventory_reservation_expiry", "status", "expires_at"),)
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("product_variants.id"), nullable=False)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InventoryMovement(UUIDPrimaryKeyMixin, db.Model):
    __tablename__ = "inventory_movements"
    variant_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_variants.id"), nullable=False, index=True
    )
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id"), index=True)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("admin_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "payments"
    __table_args__ = (Index("ix_payments_provider_reference", "provider", "provider_reference"),)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(80))


class Fulfillment(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "fulfillments"
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    carrier: Mapped[str | None] = mapped_column(String(100))
    tracking_code: Mapped[str | None] = mapped_column(String(100))
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderStatusHistory(UUIDPrimaryKeyMixin, db.Model):
    __tablename__ = "order_status_history"
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    old_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("admin_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
