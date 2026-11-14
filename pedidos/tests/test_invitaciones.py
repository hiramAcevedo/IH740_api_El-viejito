"""Las invitaciones al panel: POST /api/admin/invitaciones/ (superadmin) y GET, POST /api/invitaciones/<clave>/
(pública). El alta en Supabase Auth con la llave de servicio va simulada."""
import uuid
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

from pedidos.models import Invitacion, UsuariosAdmin

from .comun import ConPanel, nueva_cuenta, respuesta_http

VIGENTE = "/api/invitaciones/clave-vigente-de-prueba/"


class InvitacionesTests(ConPanel, TestCase):
    def setUp(self):
        super().setUp()
        self.superadmin = nueva_cuenta(rol="superadmin", nombre="Dueño")
        self.invitacion = Invitacion.objects.create(clave="clave-vigente-de-prueba", nombre="Ana Pérez",
                                                    email="ana@elviejito.mx", vence=timezone.now() + timedelta(days=5))

    def test_superadmin_genera_liga_que_vence_en_cinco_dias(self):
        """El superadmin genera una liga de un solo uso que vence en cinco días y aparece como invitada en la lista."""
        antes = timezone.now()

        r = self.llamar("post", "/api/admin/invitaciones/", {"nombre": "Luis Gómez", "email": "luis@elviejito.mx"},
                        headers=self.sesion_de(self.superadmin))

        self.assertEqual(r.status_code, 201)
        clave = r.json()["liga"].removeprefix("/admin/registro?invitacion=")
        inv = Invitacion.objects.get(clave=clave)
        self.assertGreaterEqual(len(clave), 32)
        self.assertEqual((inv.nombre, inv.email, inv.rol, inv.usada), ("Luis Gómez", "luis@elviejito.mx", "admin", False))
        self.assertTrue(timedelta(days=5) <= inv.vence - antes < timedelta(days=5, minutes=1))
        lista = self.client.get("/api/admin/usuarios/", headers=self.sesion_de(self.superadmin)).json()
        self.assertIn(("luis@elviejito.mx", "invitado"), [(u["email"], u["estado"]) for u in lista])

    def test_invitacion_vigente_devuelve_nombre_y_correo(self):
        """La liga vigente devuelve el nombre, el correo y el rol de la invitación."""
        r = self.client.get(VIGENTE)

        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["nombre"], r.json()["email"], r.json()["rol"]), ("Ana Pérez", "ana@elviejito.mx", "admin"))

    def test_invitacion_usada_vencida_o_inexistente_da_410(self):
        """Una liga usada, vencida o que no existe da 410 al leerla y al aceptarla, sin llamar a Supabase."""
        Invitacion.objects.create(clave="clave-usada", nombre="Usada", email="usada@elviejito.mx", usada=True,
                                  vence=timezone.now() + timedelta(days=3))
        Invitacion.objects.create(clave="clave-vencida", nombre="Vencida", email="vencida@elviejito.mx",
                                  vence=timezone.now() - timedelta(minutes=1))

        with mock.patch("pedidos.supabase_admin.requests.post") as alta:
            for clave in ("clave-usada", "clave-vencida", "clave-que-no-existe"):
                with self.subTest(clave):
                    self.assertEqual(self.client.get(f"/api/invitaciones/{clave}/").status_code, 410)
                    r = self.llamar("post", f"/api/invitaciones/{clave}/", {"nombre": "Ana", "contrasena": "una-clave-larga-123"})
                    self.assertEqual(r.status_code, 410)
        alta.assert_not_called()
        self.assertEqual(UsuariosAdmin.objects.count(), 1)

    def test_aceptar_crea_la_cuenta_en_supabase_y_marca_la_liga_usada(self):
        """Aceptar crea la cuenta en Supabase con el correo de la invitación, la da de alta activa y la liga ya no sirve."""
        nuevo_id = uuid.uuid4()
        creada = respuesta_http(200, {"id": str(nuevo_id), "email": "ana@elviejito.mx"})

        with mock.patch("pedidos.supabase_admin.requests.post", return_value=creada) as alta:
            corta = self.llamar("post", VIGENTE, {"nombre": "Ana Pérez", "contrasena": "corta"})
            r = self.llamar("post", VIGENTE, {"nombre": "Ana Pérez", "contrasena": "una-clave-larga-123",
                                              "email": "intruso@ejemplo.com"})

        self.assertEqual(corta.status_code, 400)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json(), {"ok": True})
        alta.assert_called_once_with(
            f"{settings.SUPABASE_URL}/auth/v1/admin/users", timeout=10,
            headers={"apikey": settings.SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"},
            json={"email": "ana@elviejito.mx", "password": "una-clave-larga-123", "email_confirm": True,
                  "user_metadata": {"nombre": "Ana Pérez"}})
        cuenta = UsuariosAdmin.objects.get(id=nuevo_id)
        self.assertEqual((cuenta.nombre, cuenta.email, cuenta.rol, cuenta.activo), ("Ana Pérez", "ana@elviejito.mx", "admin", True))
        self.invitacion.refresh_from_db()
        self.assertTrue(self.invitacion.usada)
        self.assertEqual(self.client.get(VIGENTE).status_code, 410)

    @override_settings(SUPABASE_SERVICE_KEY="")
    def test_aceptar_sin_llave_de_servicio_da_503(self):
        """Sin la llave de servicio, aceptar responde 503 con la razón; la liga sigue sin usar y no se crea cuenta."""
        with mock.patch("pedidos.supabase_admin.requests.post") as alta:
            r = self.llamar("post", VIGENTE, {"nombre": "Ana Pérez", "contrasena": "una-clave-larga-123"})

        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"detail": "Falta la llave de servicio de Supabase en la API: no se pueden crear cuentas."})
        alta.assert_not_called()
        self.invitacion.refresh_from_db()
        self.assertFalse(self.invitacion.usada)
        self.assertEqual(UsuariosAdmin.objects.count(), 1)
