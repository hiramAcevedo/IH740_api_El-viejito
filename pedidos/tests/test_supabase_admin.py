"""El alta de cuentas cuando Supabase Auth la rechaza o no responde: la API contesta con la razón, nunca con un 500."""
import uuid
from datetime import timedelta
from unittest import mock

import requests
from django.test import TestCase
from django.utils import timezone

from ..models import Invitacion, UsuariosAdmin
from .comun import ConPanel, nueva_cuenta, respuesta_http


class AltaRechazadaTests(ConPanel, TestCase):
    def setUp(self):
        super().setUp()
        self.superadmin = nueva_cuenta(rol="superadmin")
        self.invitacion = Invitacion.objects.create(clave="c" * 40, nombre="Ana Pérez", email="ana@elviejito.mx", rol="admin",
                                                    usada=False, vence=timezone.now() + timedelta(days=5),
                                                    creado=timezone.now())
        self.ruta = f"/api/invitaciones/{'c' * 40}/"
        self.datos = {"nombre": "Ana Pérez", "contrasena": "una-clave-larga-123"}

    def test_correo_con_cuenta_da_409_y_la_liga_sigue_sin_usar(self):
        """Si Supabase dice que el correo ya tiene cuenta, la API responde 409 con la razón y la invitación sigue vigente."""
        repetido = respuesta_http(422, {"code": 422, "error_code": "email_exists",
                                        "msg": "A user with this email address has already been registered"})
        with mock.patch("pedidos.supabase_admin.requests.post", return_value=repetido):
            r = self.llamar("post", self.ruta, self.datos)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"], "Ya existe una cuenta con ese correo.")
        self.invitacion.refresh_from_db()
        self.assertFalse(self.invitacion.usada)
        self.assertFalse(UsuariosAdmin.objects.filter(email="ana@elviejito.mx").exists())

    def test_otro_rechazo_da_400_con_la_razon_de_supabase(self):
        """Un 4xx distinto, como una contraseña que no cumple la política del proyecto, llega como 400 con su mensaje."""
        debil = respuesta_http(422, {"code": 422, "error_code": "weak_password", "msg": "Password should contain a number"})
        with mock.patch("pedidos.supabase_admin.requests.post", return_value=debil):
            r = self.llamar("post", self.ruta, self.datos)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "Password should contain a number")

    def test_supabase_caido_o_sin_red_da_502(self):
        """Un 5xx de Supabase o una falla de red dan 502 con un mensaje para reintentar, no un error del servidor."""
        with mock.patch("pedidos.supabase_admin.requests.post", return_value=respuesta_http(503, {"msg": "upstream"})):
            caido = self.llamar("post", self.ruta, self.datos)
        with mock.patch("pedidos.supabase_admin.requests.post", side_effect=requests.ConnectionError("sin red")):
            sin_red = self.llamar("post", self.ruta, self.datos)
        self.assertEqual((caido.status_code, sin_red.status_code), (502, 502))
        self.invitacion.refresh_from_db()
        self.assertFalse(self.invitacion.usada)
