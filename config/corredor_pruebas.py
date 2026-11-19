"""El corredor de las pruebas (TEST_RUNNER de config/settings_pruebas.py).

- productos, pedidos y usuarios_admin salieron de inspectdb y son managed = False: mientras corren las pruebas se
  vuelven administradas para que Django cree sus tablas en la base de prueba, y al final regresan como estaban.
- La búsqueda por folio usa id::text, un cast que sólo entiende Postgres. En SQLite se traduce a CAST(id AS TEXT)
  antes de ejecutar cada consulta; el código de la app no cambia.
- Ninguna prueba sale a la red: Stripe y Supabase se simulan con unittest.mock y, si alguna llamada quedara sin
  simular, el corredor la corta con SalidaALaRed en lugar de dejarla llegar al servicio real.
"""
import re
import socket
from unittest import mock

from django.apps import apps
from django.db import connections
from django.test.runner import DiscoverRunner

CAST_DE_POSTGRES = re.compile(r"\b(\w+)::text\b")


def cast_para_sqlite(execute, sql, params, many, context):
    if "::text" in sql:
        sql = CAST_DE_POSTGRES.sub(r"CAST(\1 AS TEXT)", sql)
    return execute(sql, params, many, context)


class SalidaALaRed(RuntimeError):
    """Una prueba intentó abrir una conexión: falta simular la llamada a Stripe o a Supabase."""


def sin_red(*args, **kwargs):
    raise SalidaALaRed("Las pruebas no salen a la red: simula esta llamada con unittest.mock.")


class CorredorPruebas(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        self.no_administrados = [modelo for modelo in apps.get_models() if not modelo._meta.managed]
        for modelo in self.no_administrados:
            modelo._meta.managed = True
        self.cortes_de_red = [
            mock.patch.object(socket, "getaddrinfo", sin_red),
            mock.patch.object(socket, "create_connection", sin_red),
            mock.patch.object(socket.socket, "connect", sin_red),
            mock.patch.object(socket.socket, "connect_ex", sin_red),
        ]
        for corte in self.cortes_de_red:
            corte.start()
        super().setup_test_environment(**kwargs)

    def teardown_test_environment(self, **kwargs):
        super().teardown_test_environment(**kwargs)
        for corte in reversed(self.cortes_de_red):
            corte.stop()
        for modelo in self.no_administrados:
            modelo._meta.managed = False

    def run_suite(self, suite, **kwargs):
        with connections["default"].execute_wrapper(cast_para_sqlite):
            return super().run_suite(suite, **kwargs)
