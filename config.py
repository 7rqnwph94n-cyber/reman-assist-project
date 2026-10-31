import os
import secrets
from pathlib import Path
from urllib.parse import urlparse
from constants import MAX_CONTENT_LENGTH_MB, MB


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "app.db"
DEFAULT_UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or str(BASE_DIR / "uploads")


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).lower() in {"1", "true", "yes", "on"}


def _max_content_length():
    """Get max content length from environment or use constant."""
    try:
        mb = int(os.environ.get("MAX_CONTENT_LENGTH_MB", str(MAX_CONTENT_LENGTH_MB)))
        return mb * MB
    except ValueError:
        return MAX_CONTENT_LENGTH_MB * MB


def _is_strict_runtime_mode(name: str | None = None) -> bool:
    cfg_name = (name or os.environ.get("FLASK_CONFIG") or "").lower()
    app_env = (os.environ.get("APP_ENV") or "").lower()
    return cfg_name == "production" or app_env in {"pilot", "prod", "production"}


def _validate_strict_database_url(db_url: str) -> None:
    parsed = urlparse(db_url)
    if parsed.scheme != "sqlite":
        return
    if not db_url.startswith("sqlite:////"):
        raise RuntimeError(
            "In pilot/production, SQLite DATABASE_URL must use an absolute path "
            "(sqlite:////abs/path/to/app.db)."
        )
    db_path = parsed.path or ""
    if not db_path or db_path == ":memory:":
        raise RuntimeError("In pilot/production, SQLite in-memory databases are not allowed.")


class Config:
    # Prefer env-provided secret; fall back to a per-process random token (dev only).
    # Production MUST set SECRET_KEY environment variable — enforced in get_config().
    _secret_from_env = os.environ.get("SECRET_KEY") or os.environ.get("FLASK_SECRET_KEY")
    if not _secret_from_env:
        if _is_strict_runtime_mode():
            raise RuntimeError(
                "SECRET_KEY environment variable is REQUIRED in production/pilot. "
                "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
            )
        # Dev-only: generate an ephemeral key and warn loudly
        _secret_from_env = secrets.token_hex(32)
        import sys
        print("WARNING: Using auto-generated SECRET_KEY (sessions lost on restart). "
              "Set SECRET_KEY env var for production!", file=sys.stderr)
    SECRET_KEY = _secret_from_env
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}"
    )
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
    }
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = DEFAULT_UPLOAD_FOLDER
    MAX_CONTENT_LENGTH = _max_content_length()  # default 500MB unless overridden
    JSON_SORT_KEYS = False
    ENFORCE_CSRF = os.environ.get("ENFORCE_CSRF", "true").lower() != "false"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = _bool_env("SESSION_COOKIE_SECURE", default=True)
    ENABLE_DEV_TOOLS = _bool_env("ENABLE_DEV_TOOLS", default=False)
    REPORT_EMBED_IMAGES = _bool_env("REPORT_EMBED_IMAGES", default=True)
    REPORT_MAX_IMAGE_EMBEDS = int(os.environ.get("REPORT_MAX_IMAGE_EMBEDS", "6"))
    REPORT_MAX_IMAGE_EMBED_MB = int(os.environ.get("REPORT_MAX_IMAGE_EMBED_MB", "5"))
    ENABLE_TEST_SELECTORS = _bool_env("ENABLE_TEST_SELECTORS", default=False)
    ENABLE_TEMPLATE_COSTING = _bool_env("ENABLE_TEMPLATE_COSTING", default=False)
    ENABLE_TEMPLATE_WIZARD = _bool_env("ENABLE_TEMPLATE_WIZARD", default=True)
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    LOG_FORMAT = os.environ.get("LOG_FORMAT", "text")
    LOG_FILE = os.environ.get("LOG_FILE")
    # CSRF tokens never expire to avoid timeouts on long surveys
    WTF_CSRF_TIME_LIMIT = None
    # Login throttling (Redis when configured, otherwise in-memory)
    LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "6"))
    LOGIN_WINDOW_SECONDS = int(os.environ.get("LOGIN_WINDOW_SECONDS", "900"))
    LOGIN_LOCKOUT_SECONDS = int(os.environ.get("LOGIN_LOCKOUT_SECONDS", "900"))
    LOGIN_IP_MAX_ATTEMPTS = int(os.environ.get("LOGIN_IP_MAX_ATTEMPTS", "20"))
    REDIS_URL = os.environ.get("REDIS_URL")
    SKIP_SCHEMA_CHECK = _bool_env("SKIP_SCHEMA_CHECK", default=False)
    RUN_STARTUP_CHECKS = _bool_env("RUN_STARTUP_CHECKS", default=True)
    CHECK_SCHEMA_ON_STARTUP = _bool_env("CHECK_SCHEMA_ON_STARTUP", default=True)
    CHECK_MIGRATIONS_ON_STARTUP = _bool_env("CHECK_MIGRATIONS_ON_STARTUP", default=True)
    CHECK_REDIS_ON_STARTUP = _bool_env("CHECK_REDIS_ON_STARTUP", default=True)
    ENABLE_LEGACY_EXPORT = _bool_env("ENABLE_LEGACY_EXPORT", default=False)
    PASSWORD_MIN_LENGTH = int(os.environ.get("PASSWORD_MIN_LENGTH", "10"))
    PASSWORD_REQUIRE_UPPER = _bool_env("PASSWORD_REQUIRE_UPPER", default=True)
    PASSWORD_REQUIRE_LOWER = _bool_env("PASSWORD_REQUIRE_LOWER", default=True)
    PASSWORD_REQUIRE_DIGIT = _bool_env("PASSWORD_REQUIRE_DIGIT", default=True)
    PASSWORD_REQUIRE_SPECIAL = _bool_env("PASSWORD_REQUIRE_SPECIAL", default=True)
    REGION = os.environ.get("REGION", "UK")
    LOCALE = os.environ.get("LOCALE", "en_GB")
    CURRENCY = os.environ.get("CURRENCY", "GBP")

    # QuickBooks Integration
    QUICKBOOKS_CLIENT_ID = os.environ.get("QUICKBOOKS_CLIENT_ID")
    QUICKBOOKS_CLIENT_SECRET = os.environ.get("QUICKBOOKS_CLIENT_SECRET")
    QUICKBOOKS_REDIRECT_URI = os.environ.get("QUICKBOOKS_REDIRECT_URI")
    QUICKBOOKS_ENVIRONMENT = os.environ.get("QUICKBOOKS_ENVIRONMENT", "sandbox")
    QB_ENCRYPTION_KEY = os.environ.get("QB_ENCRYPTION_KEY")
    ENABLE_QUICKBOOKS = _bool_env("ENABLE_QUICKBOOKS", default=False)
    ENABLE_EPICOR = _bool_env("ENABLE_EPICOR", default=True)


class DevelopmentConfig(Config):
    DEBUG = True
    ENABLE_TEST_SELECTORS = True
    SESSION_COOKIE_SECURE = False
    REQUIRE_REDIS = False
    RUN_STARTUP_CHECKS = False


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///:memory:")
    WTF_CSRF_ENABLED = False
    ENFORCE_CSRF = False
    ENABLE_TEST_SELECTORS = True
    SESSION_COOKIE_SECURE = False
    REQUIRE_REDIS = False
    RUN_STARTUP_CHECKS = False


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    ENABLE_TEST_SELECTORS = False
    REQUIRE_REDIS = True


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name: str | None = None):
    """
    Pick a config class from FLASK_CONFIG env var (development/testing/production),
    defaulting to development unless explicitly overridden.
    Guard against accidental production deployments without explicit config.
    """
    default_name = "development"
    cfg_name = (name or os.environ.get("FLASK_CONFIG") or default_name).lower()
    flask_env = (os.environ.get("FLASK_ENV") or "").lower()
    if flask_env == "production" and cfg_name != "production":
        raise RuntimeError(
            "FLASK_ENV=production requires FLASK_CONFIG=production to avoid unsafe defaults."
        )
    if _is_strict_runtime_mode(cfg_name):
        if not (os.environ.get("SECRET_KEY") or os.environ.get("FLASK_SECRET_KEY")):
            raise RuntimeError(
                "SECRET_KEY environment variable is REQUIRED when FLASK_CONFIG=production. "
                "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
            )
        if not os.environ.get("DATABASE_URL"):
            raise RuntimeError(
                "DATABASE_URL is required in pilot/production. "
                "Refusing to start with fallback database settings."
            )
        _validate_strict_database_url(os.environ["DATABASE_URL"])
        if not os.environ.get("UPLOAD_FOLDER"):
            raise RuntimeError("UPLOAD_FOLDER is required when FLASK_CONFIG=production.")
        # If QuickBooks is enabled, encryption key is mandatory
        if _bool_env("ENABLE_QUICKBOOKS") and not os.environ.get("QB_ENCRYPTION_KEY"):
            raise RuntimeError(
                "QB_ENCRYPTION_KEY is required when ENABLE_QUICKBOOKS=1 in production. "
                "Generate one with: python -c 'from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())'"
            )
    return config_by_name.get(cfg_name, DevelopmentConfig)
