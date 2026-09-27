import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "unsafe-development-key"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG=false.")
if not DEBUG and (
    len(SECRET_KEY) < 32
    or SECRET_KEY in {"unsafe-development-key", "CHANGE_ME_TO_A_LONG_RANDOM_VALUE"}
):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a strong, non-default value in production.")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:8765")

LANGUAGE_CODE = os.getenv("DJANGO_LANGUAGE_CODE", "en-gb")
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", os.getenv("TZ", "Europe/London"))
USE_I18N = True
USE_TZ = True

MAKERVAULT_CURRENCY = os.getenv("MAKERVAULT_CURRENCY", "GBP")
MAKERVAULT_MEASUREMENT_SYSTEM = os.getenv("MAKERVAULT_MEASUREMENT_SYSTEM", "metric")
MAKERVAULT_VERSION = "0.4.3"
MAKERVAULT_LICENSE = "AGPL-3.0-or-later"
MAKERVAULT_SOURCE_URL = os.getenv("MAKERVAULT_SOURCE_URL", "https://github.com/gavrd7/MakerVault")
ALLOW_LOCAL_REGISTRATION = env_bool("ALLOW_LOCAL_REGISTRATION", False)
OIDC_ENABLED = env_bool("OIDC_ENABLED", False)
OIDC_AUTO_SIGNUP = env_bool("OIDC_AUTO_SIGNUP", True)
OIDC_ENV_PROVIDER_ID = os.getenv("OIDC_PROVIDER_ID", "oidc")
OIDC_ENV_PROVIDER_NAME = os.getenv("OIDC_PROVIDER_NAME", "OpenID Connect")
OIDC_ENV_SERVER_URL = os.getenv("OIDC_SERVER_URL", "").strip()
OIDC_ENV_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "").strip()
OIDC_ALLOW_INSECURE_ISSUERS = env_bool("OIDC_ALLOW_INSECURE_ISSUERS", False)

# Background catalogue enrichment. Facts/specifications are pulled separately from media licensing.
ENRICH_BOARD_CATALOGUE = env_bool("ENRICH_BOARD_CATALOGUE", True)
BOARD_ENRICHMENT_MAX_PER_RUN = int(os.getenv("BOARD_ENRICHMENT_MAX_PER_RUN", "500"))
BOARD_ENRICHMENT_RETRY_DAYS = int(os.getenv("BOARD_ENRICHMENT_RETRY_DAYS", "14"))

# Automatic starter-catalogue image seeding. Work is queued to Celery so startup is not blocked.
SEED_CATALOGUE_IMAGES = env_bool("SEED_CATALOGUE_IMAGES", True)
CATALOGUE_IMAGE_MAX_PER_RUN = int(os.getenv("CATALOGUE_IMAGE_MAX_PER_RUN", "60"))
CATALOGUE_IMAGE_RETRY_DAYS = int(os.getenv("CATALOGUE_IMAGE_RETRY_DAYS", "7"))
CATALOGUE_IMAGE_PREFER_ESPBOARDS = env_bool("CATALOGUE_IMAGE_PREFER_ESPBOARDS", False)
CATALOGUE_IMAGE_WIKIMEDIA = env_bool("CATALOGUE_IMAGE_WIKIMEDIA", True)
CATALOGUE_IMAGE_OPENVERSE = env_bool("CATALOGUE_IMAGE_OPENVERSE", True)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.humanize",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.openid_connect",
    "allauth.mfa",
    "core",
]

SITE_ID = 1

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "makervault.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

WSGI_APPLICATION = "makervault.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "makervault"),
        "USER": os.getenv("POSTGRES_USER", "makervault"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
        "HOST": os.getenv("DATABASE_HOST", "postgres"),
        "PORT": os.getenv("DATABASE_PORT", "5432"),
        "CONN_MAX_AGE": int(os.getenv("DATABASE_CONN_MAX_AGE", "60")),
        "OPTIONS": {"connect_timeout": 10},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

AUTHENTICATION_BACKENDS = [
    "allauth.account.auth_backends.AuthenticationBackend",
]

ACCOUNT_ADAPTER = "core.adapters.MakerVaultAccountAdapter"
SOCIALACCOUNT_ADAPTER = "core.adapters.MakerVaultSocialAccountAdapter"
ACCOUNT_LOGIN_METHODS = {"username", "email"}
ACCOUNT_SIGNUP_FIELDS = ["username*", "email", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "optional"
ACCOUNT_LOGOUT_ON_GET = False
ACCOUNT_PREVENT_ENUMERATION = True
ALLAUTH_TRUSTED_PROXY_COUNT = int(os.getenv("ALLAUTH_TRUSTED_PROXY_COUNT", "0"))
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_STORE_TOKENS = False
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

MFA_SUPPORTED_TYPES = ["totp", "recovery_codes", "webauthn"]
MFA_PASSKEY_LOGIN_ENABLED = True
MFA_PASSKEY_SIGNUP_ENABLED = False
MFA_RECOVERY_CODES_SHOW_ONCE = True
MFA_TOTP_ISSUER = "MakerVault"

SOCIALACCOUNT_PROVIDERS = {}
if OIDC_ENABLED:
    oidc_server_url = OIDC_ENV_SERVER_URL
    oidc_client_id = OIDC_ENV_CLIENT_ID
    oidc_client_secret = os.getenv("OIDC_CLIENT_SECRET", "").strip()
    if oidc_server_url and oidc_client_id and oidc_client_secret:
        SOCIALACCOUNT_PROVIDERS = {
            "openid_connect": {
                "OAUTH_PKCE_ENABLED": env_bool("OIDC_PKCE", True),
                "APPS": [
                    {
                        "provider_id": OIDC_ENV_PROVIDER_ID,
                        "name": OIDC_ENV_PROVIDER_NAME,
                        "client_id": oidc_client_id,
                        "secret": oidc_client_secret,
                        "settings": {
                            "server_url": oidc_server_url,
                            "fetch_userinfo": env_bool("OIDC_FETCH_USERINFO", True),
                            "oauth_pkce_enabled": env_bool("OIDC_PKCE", True),
                        },
                    }
                ],
            }
        }


EMAIL_HOST = os.getenv("EMAIL_HOST", "").strip()
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
else:
    EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "MakerVault <makervault@localhost>")

STATIC_URL = "/static/"
STATIC_ROOT = Path("/app/staticfiles")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = Path("/app/media")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 900
CELERY_TASK_SOFT_TIME_LIMIT = 840
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_BEAT_SCHEDULE = {
    "catalogue-maintenance-tick": {
        "task": "core.tasks.catalogue_maintenance_tick",
        "schedule": 60.0,
    },
}

DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("DATA_UPLOAD_MAX_MEMORY_SIZE", str(1024 * 1024 * 1024)))
FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("FILE_UPLOAD_MAX_MEMORY_SIZE", str(10 * 1024 * 1024)))

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)
CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = False
if env_bool("TRUST_PROXY_HEADERS", True):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = env_bool("TRUST_X_FORWARDED_HOST", False)

SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
