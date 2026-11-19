"""Ajustes de la API de Tequila El Viejito.

Todo lo sensible sale de las variables de entorno: en local, del archivo .env (ignorado por git);
en Vercel, de las variables de cada entorno.
"""
import os
from decimal import Decimal
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
# La API no usa sesiones de Django (el panel manda el token de Supabase), pero los orígenes de confianza se declaran igual
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_ORIGENES", "").split(",") if o]
# En Vercel la petición llega por su proxy con HTTPS
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Una API sin panel de Django: sin admin, sin usuarios ni sesiones propios (el panel usa Supabase Auth)
INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "pedidos",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# La base de Supabase, la misma del sitio, por el Session pooler (IPv4); la cadena viene de DATABASE_URL
# Por omisión, una conexión por petición: el servidor de desarrollo abre un hilo por petición y, con conexiones
# persistentes, agota el pool del pooler de Supabase en modo sesión. Con un servidor de hilos fijos (gunicorn),
# DB_CONN_MAX_AGE=60 reusa la conexión de cada hilo y se revisa antes de usarla.
# En Vercel la API entra por el pooler en modo transacción (puerto 6543): cada consulta puede caer en otra conexión del
# servidor, así que no se usan sentencias preparadas (prepare_threshold en None) ni cursores del lado del servidor. En el
# modo sesión (5432) las dos cosas también funcionan. Sin DATABASE_URL (por ejemplo, al descubrir el proyecto en el build)
# la API arranca con la base de relleno de Django, que falla con un error claro en cuanto alguien la usa.
if os.environ.get("DATABASE_URL"):
    DATABASES = {"default": dj_database_url.parse(os.environ["DATABASE_URL"], conn_max_age=int(os.environ.get("DB_CONN_MAX_AGE", "0")),
                                                  conn_health_checks=True, ssl_require=True)}
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
    DATABASES["default"].setdefault("OPTIONS", {})["prepare_threshold"] = None
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.dummy"}}

LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mexico_City"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    # fuera de DEBUG la API responde sólo JSON: sin las páginas HTML de DRF, que además piden archivos estáticos
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
}

CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ORIGENES", "http://localhost:5173").split(",")
# las vistas previas de Vercel cambian de dirección por rama: se aceptan por expresión regular (separadas por comas)
CORS_ALLOWED_ORIGIN_REGEXES = [r for r in os.environ.get("CORS_ORIGENES_REGEX", "").split(",") if r]

# Pasarela de pago (Stripe en modo de prueba). Desde el sprint 4 el comprador regresa al sitio, no a la API:
# a /pago/confirmado si pagó y a /pago/error si salió sin pagar; cada pantalla le pregunta el estado a la API.
STRIPE_SECRET_KEY = os.environ["STRIPE_SECRET_KEY"]
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
SITIO_URL = os.environ.get("SITIO_URL", "http://localhost:5173").rstrip("/")

# Supabase Auth, para validar la sesión del panel en las operaciones de administración
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
# La llave de servicio: sólo aquí, nunca en el sitio. Crea y borra cuentas del panel.
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# Correos del pedido con Resend. Sin RESEND_API_KEY los avisos se quedan en la cola (notificaciones_pedido) y el
# comando enviar_correos los manda después.
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
CORREO_REMITENTE = os.environ.get("CORREO_REMITENTE", "Tequila El Viejito <pedidos@tequilaelviejito.shop>")

# Reglas del importe: el IVA se suma al subtotal, como en el checkout actual; el envío sigue sin costo
IVA = Decimal("0.16")
COSTO_ENVIO = Decimal("0.00")
