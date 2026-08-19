import json
import os
from datetime import UTC, datetime

from sqlalchemy import select
from werkzeug.security import generate_password_hash

from .extensions import db
from .models import (
    AdminUser,
    Collection,
    ContentEntry,
    ContentVersion,
    ParticipationCategory,
    Partner,
    Permission,
    Product,
    ProductVariant,
    Role,
)

PERMISSIONS = {
    "dashboard.read": "Consultar indicadores operacionais",
    "registrations.read": "Consultar inscrições",
    "registrations.manage": "Alterar inscrições e notas",
    "profiles.manage": "Publicar perfis",
    "events.manage": "Administrar edições",
    "store.manage": "Administrar catálogo e estoque",
    "orders.manage": "Operar pedidos",
    "payments.manage": "Confirmar pagamentos e estornos",
    "auction.manage": "Administrar obras, lotes e lances",
    "gallery.manage": "Administrar galeria",
    "partners.manage": "Administrar parceiros",
    "content.manage": "Administrar conteúdo",
    "communications.manage": "Administrar comunicações",
    "contacts.read": "Consultar mensagens de contato",
    "contacts.manage": "Operar mensagens, responsáveis, notas e respostas",
    "users.manage": "Administrar usuários e papéis",
    "privacy.manage": "Atender solicitações LGPD e exportações",
    "audit.read": "Consultar auditoria",
    "system.read": "Consultar sistema e prontidão",
}

ROLE_PERMISSIONS = {
    "administrador": set(PERMISSIONS),
    "editor": {
        "dashboard.read",
        "profiles.manage",
        "gallery.manage",
        "partners.manage",
        "content.manage",
    },
    "atendimento": {
        "dashboard.read",
        "registrations.read",
        "registrations.manage",
        "communications.manage",
        "contacts.read",
        "contacts.manage",
    },
    "producao": {"dashboard.read", "events.manage", "registrations.read", "profiles.manage"},
    "financeiro": {"dashboard.read", "payments.manage", "orders.manage", "audit.read"},
    "loja": {"dashboard.read", "store.manage", "orders.manage"},
    "leilao": {"dashboard.read", "auction.manage"},
    "auditor": {"dashboard.read", "audit.read", "system.read"},
}

CATEGORIES = [
    ("barbeiro", "Barbeiro"),
    ("mc", "MC"),
    ("artista", "Artista"),
    ("trancista", "Trancista"),
    ("skatista", "Skatista"),
    ("grafiteiro", "Grafiteiro"),
    ("marca-moda", "Marca / Moda"),
    ("empreendedor", "Empreendedor"),
    ("dj", "DJ"),
    ("gastronomia", "Gastronomia"),
    ("projeto-social", "Projeto social"),
]

PARTNERS = [
    ("DF Refrigeração", "df-refrigeracao", "/brand/partners/df-refrigeracao.webp"),
    ("Baianão Carnes", "baianao-carnes", "/brand/partners/baianao-carnes.webp"),
    ("Açaí do Boy", "acai-do-boy", "/brand/partners/acai-do-boy.webp"),
    ("Garagem dos Antigos", "garagem-dos-antigos", "/brand/partners/garagem-dos-antigos.webp"),
]


def seed_all() -> None:
    permissions: dict[str, Permission] = {}
    for slug, description in PERMISSIONS.items():
        item = db.session.scalar(select(Permission).where(Permission.slug == slug))
        if not item:
            item = Permission(slug=slug, description=description)
            db.session.add(item)
        permissions[slug] = item
    db.session.flush()

    for slug, granted in ROLE_PERMISSIONS.items():
        role = db.session.scalar(select(Role).where(Role.slug == slug))
        if not role:
            role = Role(slug=slug, name=slug.replace("producao", "produção").title())
            db.session.add(role)
        role.permissions = [permissions[item] for item in sorted(granted)]

    for order, (slug, name) in enumerate(CATEGORIES):
        category = db.session.scalar(
            select(ParticipationCategory).where(ParticipationCategory.slug == slug)
        )
        if not category:
            db.session.add(
                ParticipationCategory(
                    slug=slug,
                    name=name,
                    display_order=order,
                    active=True,
                    accepts_file=True,
                    accepts_link=True,
                    extra_fields_json="[]",
                )
            )

    for order, (name, slug, logo_path) in enumerate(PARTNERS):
        if not db.session.scalar(select(Partner).where(Partner.slug == slug)):
            db.session.add(
                Partner(
                    name=name,
                    slug=slug,
                    logo_path=logo_path,
                    logo_alt=f"Logo {name}",
                    category="parceiro",
                    display_order=order,
                    active=True,
                )
            )

    collection = db.session.scalar(
        select(Collection).where(Collection.slug == "edicao-especial-movimento-7")
    )
    if not collection:
        collection = Collection(
            name="Edição especial Movimento 7",
            slug="edicao-especial-movimento-7",
            description="COLEÇÃO LIMITADA - 50 peças - 4 artes - Edição especial Movimento 7",
            status="draft",
        )
        db.session.add(collection)
        db.session.flush()
    for slug, name, sku_prefix in (
        ("camisa-oversize", "Camisa Oversize", "M7-CAM"),
        ("cropped-oversize", "Cropped Oversize", "M7-CRO"),
        ("regata-oversize", "Regata Oversize", "M7-REG"),
    ):
        product = db.session.scalar(select(Product).where(Product.slug == slug))
        if not product:
            product = Product(
                collection_id=collection.id,
                name=name,
                slug=slug,
                description=(
                    "Peça da coleção limitada Movimento 7. Imagens e composição aguardam cadastro."
                ),
                price_cents=10000,
                status="draft",
            )
            db.session.add(product)
            db.session.flush()
        for size in ("P", "M", "G", "GG"):
            sku = f"{sku_prefix}-{size}"
            if not db.session.scalar(select(ProductVariant).where(ProductVariant.sku == sku)):
                db.session.add(ProductVariant(product_id=product.id, sku=sku, name=size, size=size))

    hero = db.session.scalar(select(ContentEntry).where(ContentEntry.key == "home.hero"))
    if not hero:
        hero = ContentEntry(key="home.hero", title="Hero da página inicial", content_type="json")
        db.session.add(hero)
        db.session.flush()
        version = ContentVersion(
            entry_id=hero.id,
            version=1,
            value_json=json.dumps(
                {
                    "title": "Cultura, Arte & Beleza",
                    "description": (
                        "O Movimento 7 conecta talentos, oportunidades "
                        "e novas experiências na cidade."
                    ),
                    "primaryCta": "QUERO PARTICIPAR",
                    "secondaryCta": "CONHEÇA A COLEÇÃO",
                },
                ensure_ascii=False,
            ),
            status="published",
            published_at=datetime.now(UTC),
        )
        db.session.add(version)
        db.session.flush()
        hero.current_version_id = version.id

    admin = db.session.scalar(select(AdminUser).limit(1))
    if not admin:
        email = os.getenv("INITIAL_ADMIN_EMAIL", "admin@movimento7.com").strip().lower()
        name = os.getenv("INITIAL_ADMIN_NAME", "Administrador Movimento 7").strip()
        password = os.getenv("INITIAL_ADMIN_PASSWORD", "")
        if len(password) < 12:
            raise RuntimeError(
                "INITIAL_ADMIN_PASSWORD com 12+ caracteres é obrigatória no primeiro seed"
            )
        admin_role = db.session.scalar(select(Role).where(Role.slug == "administrador"))
        admin = AdminUser(
            email=email,
            name=name,
            password_hash=generate_password_hash(password),
            active=True,
            must_change_password=True,
        )
        admin.roles = [admin_role] if admin_role else []
        db.session.add(admin)

    db.session.commit()
