import os
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent

def _positive_int_env(name, default, maximum):
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if not 0 < value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-development-key-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
INSTALLED_APPS = ["django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles", "channels", "market"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "whitenoise.middleware.WhiteNoiseMiddleware", "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware", "market.middleware.AdminSessionMiddleware", "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware", "market.middleware.SecurityHeadersMiddleware"]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND":"django.template.backends.django.DjangoTemplates", "DIRS":[BASE_DIR / "templates"], "APP_DIRS":True, "OPTIONS":{"context_processors":["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
database_url=os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL must be configured; SQLite requires an explicit sqlite URL.")
if not DEBUG and SECRET_KEY in {"", "unsafe-development-key-change-me", "replace-this-before-production", "changeme"}:
    raise RuntimeError("DJANGO_SECRET_KEY must be configured when DEBUG=false.")
if not DEBUG and (not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS or set(ALLOWED_HOSTS) <= {"localhost","127.0.0.1"}):
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must be configured when DEBUG=false.")
TRUSTED_PROXY = os.getenv("DJANGO_TRUSTED_PROXY", "false").lower() == "true"
if not DEBUG and not TRUSTED_PROXY:
    raise RuntimeError("DJANGO_TRUSTED_PROXY=true is required for HTTPS proxy deployments when DEBUG=false.")
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]
def _is_explicit_https_origin(origin):
    parsed = urlparse(origin)
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and not parsed.username
        and not parsed.password
        and parsed.path in {"", "/"}
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )
if not DEBUG and (not CSRF_TRUSTED_ORIGINS or any(not _is_explicit_https_origin(origin) for origin in CSRF_TRUSTED_ORIGINS)):
    raise RuntimeError("DJANGO_CSRF_TRUSTED_ORIGINS must contain explicit HTTPS origins when DEBUG=false.")
if database_url.startswith("postgres"):
    parsed=urlparse(database_url)
    if not DEBUG and parsed.password in {None,"tiny","password","changeme"}: raise RuntimeError("A non-development database password is required when DEBUG=false.")
    DATABASES={"default":{"ENGINE":"django.db.backends.postgresql","NAME":parsed.path.lstrip("/"),"USER":parsed.username,"PASSWORD":parsed.password,"HOST":parsed.hostname,"PORT":parsed.port or 5432,"CONN_MAX_AGE":60}}
elif database_url.startswith("sqlite"):
    if not DEBUG:
        raise RuntimeError("SQLite is permitted only with DJANGO_DEBUG=true for local development.")
    DATABASES={"default":{"ENGINE":"django.db.backends.sqlite3","NAME":BASE_DIR / "db.sqlite3"}}
else:
    raise RuntimeError("DATABASE_URL must use a supported PostgreSQL URL (or explicit development SQLite URL).")
if database_url.startswith("postgres"):
    redis_url=os.getenv("REDIS_URL")
    if not redis_url: raise RuntimeError("REDIS_URL must be configured with PostgreSQL runtime.")
    CACHES={"default":{"BACKEND":"django.core.cache.backends.redis.RedisCache","LOCATION":redis_url}}
    CHANNEL_LAYERS={"default":{"BACKEND":"channels_redis.core.RedisChannelLayer","CONFIG":{"hosts":[redis_url]}}}
else:
    CACHES={"default":{"BACKEND":"django.core.cache.backends.locmem.LocMemCache","LOCATION":"tiny-market-tests"}}
    CHANNEL_LAYERS={"default":{"BACKEND":"channels.layers.InMemoryChannelLayer"}}
AUTH_USER_MODEL = "market.User"
AUTH_PASSWORD_VALIDATORS = [{"NAME":"django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS":{"min_length":10}}]
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = USE_TZ = True
STATIC_URL, STATIC_ROOT = "/static/", BASE_DIR / "staticfiles"
MEDIA_URL, MEDIA_ROOT = "/media/", BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "product_list"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
SECURE_SSL_REDIRECT = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if TRUSTED_PROXY else None
SECURE_HSTS_SECONDS = 31_536_000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_REDIRECT_EXEMPT = ["healthz/"]
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
WELCOME_BONUS_ENABLED = os.getenv("WELCOME_BONUS_ENABLED", "false").lower() == "true"
WELCOME_BONUS_AMOUNT = _positive_int_env("WELCOME_BONUS_AMOUNT", 10000, 1_000_000_000)
TRANSFER_MAX_AMOUNT = _positive_int_env("TRANSFER_MAX_AMOUNT", 10000, 1_000_000_000)
TRANSFER_DAILY_LIMIT = _positive_int_env("TRANSFER_DAILY_LIMIT", 50000, 1_000_000_000)
TRANSFER_RATE_LIMIT_PER_MINUTE = _positive_int_env("TRANSFER_RATE_LIMIT_PER_MINUTE", 5, 10_000)
ADMIN_GRANT_MAX_AMOUNT = _positive_int_env("ADMIN_GRANT_MAX_AMOUNT", 100000, 1_000_000_000)
ADMIN_GRANT_DAILY_LIMIT = _positive_int_env("ADMIN_GRANT_DAILY_LIMIT", 500000, 1_000_000_000)
ADMIN_GRANT_RATE_LIMIT_PER_MINUTE = _positive_int_env("ADMIN_GRANT_RATE_LIMIT_PER_MINUTE", 5, 10_000)
CHAT_RATE_LIMIT_PER_MINUTE = _positive_int_env("CHAT_RATE_LIMIT_PER_MINUTE", 30, 10_000)
RATE_LIMIT_TTL_SECONDS = _positive_int_env("RATE_LIMIT_TTL_SECONDS", 70, 300)
ADMIN_LOGIN_RATE_LIMIT_PER_MINUTE = _positive_int_env("ADMIN_LOGIN_RATE_LIMIT_PER_MINUTE", 5, 100)
ADMIN_LOGIN_RATE_LIMIT_TTL_SECONDS = _positive_int_env("ADMIN_LOGIN_RATE_LIMIT_TTL_SECONDS", 60, 300)
SIGNUP_RATE_LIMIT = _positive_int_env("SIGNUP_RATE_LIMIT", 5, 100)
SIGNUP_RATE_LIMIT_WINDOW_SECONDS = _positive_int_env("SIGNUP_RATE_LIMIT_WINDOW_SECONDS", 600, 86_400)
LOGIN_FAILURE_RATE_LIMIT = _positive_int_env("LOGIN_FAILURE_RATE_LIMIT", 5, 100)
LOGIN_FAILURE_IP_RATE_LIMIT = _positive_int_env("LOGIN_FAILURE_IP_RATE_LIMIT", 20, 500)
LOGIN_FAILURE_RATE_LIMIT_WINDOW_SECONDS = _positive_int_env("LOGIN_FAILURE_RATE_LIMIT_WINDOW_SECONDS", 300, 86_400)
ADMIN_SESSION_IDLE_SECONDS = _positive_int_env("ADMIN_SESSION_IDLE_SECONDS", 900, 86_400)
ADMIN_SESSION_ABSOLUTE_SECONDS = _positive_int_env("ADMIN_SESSION_ABSOLUTE_SECONDS", 28_800, 172_800)
ADMIN_REAUTH_SECONDS = _positive_int_env("ADMIN_REAUTH_SECONDS", 300, 3_600)
