from datetime import UTC, datetime, timedelta

from movimento7.extensions import db
from movimento7.models import Artwork, AuctionLot, Product, ProductVariant


def test_unpublished_products_are_not_public(app, client):
    with app.app_context():
        db.session.add(
            Product(
                name="Rascunho", slug="rascunho", description="x", price_cents=10000
            )
        )
        db.session.commit()
    response = client.get("/api/v1/products")
    assert response.status_code == 200
    assert response.json["data"] == []


def test_internal_only_product_is_not_public_or_purchasable(app, client):
    with app.app_context():
        product = Product(
            name="Camiseta Movimento 7",
            slug="camiseta-movimento7",
            description="Uso interno",
            price_cents=10000,
            status="published",
        )
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(
            product_id=product.id, sku="M7-INTERNO", name="M", stock_quantity=10
        )
        db.session.add(variant)
        db.session.commit()
        variant_id = str(variant.id)

    assert client.get("/api/v1/products").json["data"] == []
    assert client.get("/api/v1/products/camiseta-movimento7").status_code == 404
    cart = client.post("/api/v1/carts").json["data"]
    response = client.put(
        "/api/v1/carts/items",
        json={
            "cart_token": cart["cart_token"],
            "variant_id": variant_id,
            "quantity": 1,
        },
    )
    assert response.status_code == 404
    assert response.json["error"]["code"] == "variant_unavailable"


def test_cart_rejects_out_of_stock(app, client):
    with app.app_context():
        product = Product(
            name="Produto teste",
            slug="produto-teste",
            description="x",
            price_cents=10000,
            status="published",
        )
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(
            product_id=product.id, sku="TESTE-1", name="M", stock_quantity=0
        )
        db.session.add(variant)
        db.session.commit()
        variant_id = str(variant.id)
    cart = client.post("/api/v1/carts").json["data"]
    response = client.put(
        "/api/v1/carts/items",
        json={
            "cart_token": cart["cart_token"],
            "variant_id": variant_id,
            "quantity": 1,
        },
    )
    assert response.status_code == 409
    assert response.json["error"]["code"] == "out_of_stock"


def test_shipping_quote_uses_configured_flat_rate_and_free_threshold(app, client):
    app.config.update(
        SHIPPING_FLAT_RATE_CENTS=1500,
        SHIPPING_FREE_THRESHOLD_CENTS=10000,
        SHIPPING_LABEL="Entrega padrão",
        SHIPPING_METHOD="manual",
        SHIPPING_ESTIMATED_DAYS=5,
    )
    with app.app_context():
        product = Product(
            name="Produto com frete",
            slug="produto-com-frete",
            description="x",
            price_cents=8000,
            status="published",
        )
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(
            product_id=product.id, sku="FRETE-1", name="Único", stock_quantity=3
        )
        db.session.add(variant)
        db.session.commit()
        variant_id = str(variant.id)
    cart = client.post("/api/v1/carts").json["data"]
    client.put(
        "/api/v1/carts/items",
        json={
            "cart_token": cart["cart_token"],
            "variant_id": variant_id,
            "quantity": 1,
        },
    )
    quoted = client.post(
        "/api/v1/shipping/quote",
        json={
            "cart_token": cart["cart_token"],
            "address": {"postal_code": "01001000", "state": "SP"},
        },
    )
    assert quoted.status_code == 200
    assert quoted.json["data"]["shipping_cents"] == 1500
    assert quoted.json["data"]["estimated_days"] == 5
    app.config["SHIPPING_FREE_THRESHOLD_CENTS"] = 8000
    free = client.post(
        "/api/v1/shipping/quote",
        json={
            "cart_token": cart["cart_token"],
            "address": {"postal_code": "01001000", "state": "SP"},
        },
    )
    assert free.json["data"]["free_shipping"] is True
    assert free.json["data"]["shipping_cents"] == 0


def test_bidding_feature_flag_is_off(app, client):
    with app.app_context():
        artwork = Artwork(
            title="Obra", slug="obra", artist_name="Artista", status="published"
        )
        db.session.add(artwork)
        db.session.flush()
        lot = AuctionLot(
            artwork_id=artwork.id,
            slug="lote-obra",
            title="Lote obra",
            starting_bid_cents=10000,
            minimum_increment_cents=1000,
            opens_at=datetime.now(UTC) - timedelta(hours=1),
            closes_at=datetime.now(UTC) + timedelta(hours=1),
            status="open",
        )
        db.session.add(lot)
        db.session.commit()
        lot_id = str(lot.id)
    response = client.post(
        f"/api/v1/auction-lots/{lot_id}/bids",
        headers={"Idempotency-Key": "bid-test-0001"},
        json={"amount_cents": 11000},
    )
    assert response.status_code == 409
    assert response.json["error"]["code"] == "bidding_disabled"


def test_bidding_requires_payment_guarantee_before_activation(app, client):
    app.config.update(AUCTION_BIDDING_ENABLED=True, AUCTION_PAYMENT_GUARANTEE_ENABLED=False)
    response = client.post(
        "/api/v1/auction-lots/00000000-0000-0000-0000-000000000000/bids",
        headers={"Idempotency-Key": "bid-test-0002"},
        json={"amount_cents": 11000},
    )
    assert response.status_code == 503
    assert response.json["error"]["code"] == "bidding_payment_not_ready"
