import os

os.environ.setdefault("DJANGO_SECRET_KEY", "django-insecure-test-key-local-12345")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy_para_pruebas_unitarias")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_dummy_para_pruebas_unitarias")
os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "dummy_anon_key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy_service_role_key")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")

from .settings import *  # noqa

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Saltamos migraciones con SQL exclusivo de PostgreSQL (ENABLE ROW LEVEL SECURITY)
MIGRATION_MODULES = {
    "pedidos": None,
}

# Activamos managed = True temporalmente en memoria para tablas heredadas de Supabase (productos, pedidos, usuarios_admin)
from django.test.runner import DiscoverRunner

class ManagedModelsTestRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        from django.apps import apps
        for model in apps.get_models():
            if not model._meta.managed:
                model._meta.managed = True
        return super().setup_databases(**kwargs)

TEST_RUNNER = "config.settings_test.ManagedModelsTestRunner"
