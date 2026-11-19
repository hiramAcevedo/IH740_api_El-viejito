"""Las cuentas del panel en manos del superadministrador: el alta directa en Supabase Auth, apagar, encender y borrar.
Supabase Auth va simulado."""
import uuid
from unittest import mock

import requests
from django.conf import settings
from django.test import TestCase, override_settings

from pedidos.models import UsuariosAdmin

from .comun import ConPanel, nueva_cuenta, respuesta_http

ALTA = {"nombre": "Ana Pérez", "email": "ana@elviejito.mx", "contrasena": "una-clave-larga-123"}


class CuentasDelPanelTests(ConPanel, TestCase):
    def setUp(self):
        super().setUp()
        self.superadmin = nueva_cuenta(rol="superadmin", nombre="Dueño")
        self.sesion = self.sesion_de(self.superadmin)
        self.admin = nueva_cuenta(rol="admin", nombre="Ana Admin")

    def ruta(self, cuenta_id):
        return f"/api/admin/usuarios/{cuenta_id}/"

    def test_alta_directa_crea_la_cuenta_confirmada_en_auth_y_activa_en_el_panel(self):
        """El alta directa crea la cuenta ya confirmada en Supabase Auth con la llave de servicio y la deja activa."""
        nuevo_id = str(uuid.uuid4())
        with mock.patch("pedidos.supabase_admin.requests.post", return_value=respuesta_http(200, {"id": nuevo_id})) as alta:
            r = self.llamar("post", "/api/admin/usuarios/", ALTA, headers=self.sesion)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json(), {"id": nuevo_id, "nombre": "Ana Pérez", "email": "ana@elviejito.mx", "rol": "admin",
                                    "estado": "activo"})
        self.assertEqual(alta.call_args.args[0], f"{settings.SUPABASE_URL}/auth/v1/admin/users")
        self.assertEqual(alta.call_args.kwargs["json"], {"email": "ana@elviejito.mx", "password": "una-clave-larga-123",
                                                         "email_confirm": True, "user_metadata": {"nombre": "Ana Pérez"}})
        self.assertEqual(alta.call_args.kwargs["headers"]["Authorization"], f"Bearer {settings.SUPABASE_SERVICE_KEY}")
        cuenta = UsuariosAdmin.objects.get(id=nuevo_id)
        self.assertEqual((cuenta.rol, cuenta.activo), ("admin", True))

    def test_rechazo_sin_cuerpo_json_da_400_con_la_razon_por_omision(self):
        """Si Supabase rechaza el alta sin un cuerpo JSON, la API responde 400 con una razón propia, no un 500."""
        rechazo = requests.Response()
        rechazo.status_code, rechazo._content = 400, b"Bad Request"
        with mock.patch("pedidos.supabase_admin.requests.post", return_value=rechazo):
            r = self.llamar("post", "/api/admin/usuarios/", ALTA, headers=self.sesion)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "Supabase no creó la cuenta.")
        self.assertFalse(UsuariosAdmin.objects.filter(email="ana@elviejito.mx").exists())

    def test_apagar_y_encender_una_cuenta(self):
        """Apagar deja la cuenta fuera del panel sin borrarla; encenderla la regresa."""
        sesion_admin = self.sesion_de(self.admin)
        apagada = self.llamar("patch", self.ruta(self.admin.id), {"estado": "apagado"}, headers=self.sesion)
        self.assertEqual((apagada.status_code, apagada.json()["estado"]), (200, "apagado"))
        self.assertEqual(self.client.get("/api/admin/resumen/", headers=sesion_admin).status_code, 401)

        encendida = self.llamar("patch", self.ruta(self.admin.id), {"estado": "activo"}, headers=self.sesion)
        self.assertEqual((encendida.status_code, encendida.json()["estado"]), (200, "activo"))
        self.assertEqual(self.client.get("/api/admin/resumen/", headers=sesion_admin).status_code, 200)

    def test_un_cambio_sin_estado_no_apaga_la_cuenta(self):
        r = self.llamar("patch", self.ruta(self.admin.id), {"rol": "admin"}, headers=self.sesion)
        self.assertEqual((r.status_code, r.json()["estado"]), (200, "activo"))
        self.assertTrue(UsuariosAdmin.objects.get(id=self.admin.id).activo)

    def test_borrar_quita_la_cuenta_del_panel_y_de_supabase_auth(self):
        with mock.patch("pedidos.supabase_admin.requests.delete", return_value=respuesta_http(200, {})) as baja:
            r = self.llamar("delete", self.ruta(self.admin.id), headers=self.sesion)
        self.assertEqual(r.status_code, 204)
        baja.assert_called_once()
        self.assertEqual(baja.call_args.args[0], f"{settings.SUPABASE_URL}/auth/v1/admin/users/{self.admin.id}")
        self.assertFalse(UsuariosAdmin.objects.filter(id=self.admin.id).exists())

    @override_settings(SUPABASE_SERVICE_KEY="")
    def test_sin_llave_de_servicio_la_cuenta_sale_del_panel_y_auth_no_se_toca(self):
        """Sin la llave de servicio, borrar quita la cuenta del panel; la de Auth queda, pero ya no entra."""
        with mock.patch("pedidos.supabase_admin.requests.delete") as baja:
            r = self.llamar("delete", self.ruta(self.admin.id), headers=self.sesion)
        self.assertEqual(r.status_code, 204)
        baja.assert_not_called()
        self.assertFalse(UsuariosAdmin.objects.filter(id=self.admin.id).exists())
        self.assertEqual(self.client.get("/api/admin/resumen/", headers=self.sesion_de(self.admin)).status_code, 401)

    def test_cuenta_inexistente_da_404_y_la_del_superadmin_no_se_apaga_ni_se_borra(self):
        with mock.patch("pedidos.supabase_admin.requests.delete") as baja:
            no_existe = self.llamar("patch", self.ruta(uuid.uuid4()), {"estado": "apagado"}, headers=self.sesion)
            borrar_propia = self.llamar("delete", self.ruta(self.superadmin.id), headers=self.sesion)
            apagar_propia = self.llamar("patch", self.ruta(self.superadmin.id), {"estado": "apagado"}, headers=self.sesion)
        self.assertEqual(no_existe.status_code, 404)
        self.assertEqual((borrar_propia.status_code, apagar_propia.status_code), (403, 403))
        baja.assert_not_called()
        self.assertTrue(UsuariosAdmin.objects.filter(id=self.superadmin.id, activo=True).exists())
