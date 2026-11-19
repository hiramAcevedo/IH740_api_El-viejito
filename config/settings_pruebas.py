"""Ajustes para las pruebas: SQLite en memoria, sin la base de Supabase, sin Stripe y sin Supabase Auth reales.

    uv run python manage.py test --settings=config.settings_pruebas

Los ajustes base piden variables de entorno al importarse. Aquí se ponen valores de relleno antes de importarlos;
como python-dotenv no pisa una variable que ya existe, las llaves de .env no llegan a las pruebas. Después se fijan
los valores de prueba, para que no dependan de lo que haya en la terminal.
"""
import os

for _nombre, _valor in {
    "DJANGO_SECRET_KEY": "clave-de-pruebas-sin-valor",
    "DATABASE_URL": "sqlite://:memory:",
    "STRIPE_SECRET_KEY": "sk_test_pruebas_sin_red",
    "STRIPE_WEBHOOK_SECRET": "whsec_pruebas_sin_red",
    "SUPABASE_URL": "https://supabase.pruebas.invalid",
    "SUPABASE_PUBLISHABLE_KEY": "llave-publica-de-pruebas",
    "SUPABASE_SERVICE_KEY": "llave-de-servicio-de-pruebas",
    "SITIO_URL": "https://sitio.pruebas.invalid",
}.items():
    os.environ.setdefault(_nombre, _valor)

from .settings import *  # noqa: E402,F401,F403

# La base de prueba vive en memoria; nunca se abre la conexión a Supabase
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

# Las migraciones llevan SQL de Postgres (RLS, CHECK): las tablas se crean directo de los modelos
MIGRATION_MODULES = {"pedidos": None}

# Vuelve administradas las tablas de inspectdb, traduce el cast de Postgres y corta cualquier salida a la red
TEST_RUNNER = "config.corredor_pruebas.CorredorPruebas"

# Valores fijos de prueba: ninguno sirve fuera de aquí
SECRET_KEY = "clave-de-pruebas-sin-valor"
STRIPE_SECRET_KEY = "sk_test_pruebas_sin_red"
STRIPE_WEBHOOK_SECRET = "whsec_pruebas_sin_red"
SUPABASE_URL = "https://supabase.pruebas.invalid"
SUPABASE_PUBLISHABLE_KEY = "llave-publica-de-pruebas"
SUPABASE_SERVICE_KEY = "llave-de-servicio-de-pruebas"
SITIO_URL = "https://sitio.pruebas.invalid"
DEBUG = False
# Sin llave de Resend: ningún correo sale de las pruebas; las que prueban el envío la ponen con override_settings
RESEND_API_KEY = ""
CORREO_REMITENTE = "Tequila El Viejito <pedidos@tequilaelviejito.shop>"
