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
DATABASES = {"default": dj_database_url.parse(os.environ["DATABASE_URL"], conn_max_age=0, ssl_require=True)}

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
}

CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ORIGENES", "http://localhost:5173").split(",")

# Pasarela de pago (Stripe en modo de prueba) y la página a la que regresa el comprador
STRIPE_SECRET_KEY = os.environ["STRIPE_SECRET_KEY"]
REGRESO_URL = os.environ.get("REGRESO_URL", "http://127.0.0.1:8000/api/pagos/regreso/")

# Supabase Auth, para validar la sesión del panel en las operaciones de administración
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")

# Reglas del importe: el IVA se suma al subtotal, como en el checkout actual; el envío sigue sin costo
IVA = Decimal("0.16")
COSTO_ENVIO = Decimal("0.00")
