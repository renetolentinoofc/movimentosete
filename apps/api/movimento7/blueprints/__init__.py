from .admin import bp as admin_bp
from .admin_ops import bp as admin_ops_bp
from .auctions import bp as auctions_bp
from .auth import bp as auth_bp
from .health import bp as health_bp
from .public import bp as public_bp
from .store import bp as store_bp

ALL_BLUEPRINTS = (health_bp, auth_bp, public_bp, store_bp, auctions_bp, admin_bp, admin_ops_bp)
