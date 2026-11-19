"""El panel: /api/admin/... con la sesión de Supabase Auth (simulada) y los textos legales."""
import uuid
from datetime import date
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.test import TestCase

from pedidos.models import Envio, Invitacion, Notificacion, Pago, PagoEvento, TextoLegal, UsuariosAdmin

from .comun import ConPanel, nueva_cuenta, nuevo_pedido, nuevo_producto

GUIA = {"paqueteria": "Estafeta", "guia": "EST123456789MX", "fecha_estimada": "2026-11-20"}


class SesionDelPanelTests(ConPanel, TestCase):
    RUTAS = [("get", "/api/admin/resumen/"), ("get", "/api/admin/pedidos/"), ("get", "/api/admin/envios/"),
             ("get", "/api/admin/pagos/"), ("get", "/api/admin/usuarios/"), ("post", "/api/admin/invitaciones/")]

    def test_sin_token_da_401(self):
        """Sin la cabecera Authorization: Bearer, todas las rutas del panel responden 401 sin preguntar a Supabase."""
        for metodo, ruta in self.RUTAS:
            for caso, cabeceras in [("sin cabecera", {}), ("cabecera sin Bearer", {"Authorization": "Token abc"})]:
                with self.subTest(ruta=ruta, caso=caso):
                    r = self.llamar(metodo, ruta, headers=cabeceras)
                    self.assertEqual(r.status_code, 401)
                    self.assertEqual(r.headers["WWW-Authenticate"], 'Bearer realm="panel"')
        self.supabase_auth.assert_not_called()

    def test_token_rechazado_por_supabase_da_401(self):
        """Un token que Supabase Auth rechaza da 401; la API lo consulta en /auth/v1/user con la llave publicable."""
        r = self.client.get("/api/admin/resumen/", headers={"Authorization": "Bearer token-vencido"})

        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"detail": "La sesión no es válida o ya venció."})
        self.supabase_auth.assert_called_once_with(
            f"{settings.SUPABASE_URL}/auth/v1/user", timeout=5,
            headers={"apikey": settings.SUPABASE_PUBLISHABLE_KEY, "Authorization": "Bearer token-vencido"})

    def test_cuenta_apagada_o_fuera_del_panel_da_401(self):
        """Token válido de una cuenta apagada o de alguien que no está en usuarios_admin: 401."""
        apagada = nueva_cuenta(activo=False)
        comprador = SimpleNamespace(id=uuid.uuid4(), email="comprador@ejemplo.com")
        for caso, cuenta in [("cuenta apagada", apagada), ("cuenta fuera de usuarios_admin", comprador)]:
            with self.subTest(caso):
                r = self.client.get("/api/admin/resumen/", headers=self.sesion_de(cuenta))
                self.assertEqual(r.status_code, 401)
                self.assertEqual(r.json(), {"detail": "La cuenta no está activa en el panel."})

    def test_usuarios_e_invitaciones_solo_para_el_superadmin(self):
        """Una cuenta admin recibe 403 en usuarios e invitaciones; el superadmin sí las usa."""
        admin = nueva_cuenta(rol="admin")
        superadmin = nueva_cuenta(rol="superadmin", nombre="Dueño")
        otra = nueva_cuenta(rol="admin", nombre="Otra")
        sesion_admin = self.sesion_de(admin)
        intentos = [("get", "/api/admin/usuarios/", None),
                    ("post", "/api/admin/usuarios/", {"nombre": "X", "email": "x@elviejito.mx", "contrasena": "una-clave-larga"}),
                    ("patch", f"/api/admin/usuarios/{otra.id}/", {"estado": "apagado"}),
                    ("delete", f"/api/admin/usuarios/{otra.id}/", None),
                    ("post", "/api/admin/invitaciones/", {"nombre": "Y", "email": "y@elviejito.mx"})]

        with mock.patch("pedidos.supabase_admin.requests.post") as alta, \
                mock.patch("pedidos.supabase_admin.requests.delete") as baja:
            for metodo, ruta, datos in intentos:
                with self.subTest(f"admin: {metodo.upper()} {ruta}"):
                    r = self.llamar(metodo, ruta, datos, headers=sesion_admin)
                    self.assertEqual(r.status_code, 403)
                    self.assertEqual(r.json(), {"detail": "Sólo el superadministrador administra las cuentas del panel."})
        alta.assert_not_called()
        baja.assert_not_called()
        self.assertTrue(UsuariosAdmin.objects.filter(id=otra.id, activo=True).exists())
        self.assertFalse(Invitacion.objects.exists())

        r = self.client.get("/api/admin/usuarios/", headers=self.sesion_de(superadmin))
        self.assertEqual(r.status_code, 200)
        self.assertCountEqual([u["email"] for u in r.json()], [admin.email, superadmin.email, otra.email])
        self.assertEqual(self.client.get("/api/admin/resumen/", headers=sesion_admin).status_code, 200)


class PanelTests(ConPanel, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = nueva_cuenta(rol="admin")
        self.sesion = self.sesion_de(self.admin)
        self.blanco = nuevo_producto("Tequila Blanco 750 ml", "349.99")

    def test_resumen_cuenta_pedidos_por_cobrar_envios_y_usuarios(self):
        """El dashboard cuenta pedidos, cobros pendientes sin cancelados, envíos pagados sin guía y cuentas del panel."""
        b = self.blanco
        nuevo_pedido([(b, 1)])                                                   # por cobrar
        nuevo_pedido([(b, 1)], metodo_entrega="recoger")                         # por cobrar
        nuevo_pedido([(b, 1)], estado="cancelado")                               # cancelado: no se cobra
        nuevo_pedido([(b, 1)], estado_pago="rechazado")                          # rechazado: ni cobro ni envío
        nuevo_pedido([(b, 1)], estado_pago="pagado")                             # envío por capturar
        nuevo_pedido([(b, 1)], estado_pago="pagado", guia="")                    # guía vacía: sigue por capturar
        nuevo_pedido([(b, 1)], estado="enviado", estado_pago="pagado", guia="EST1")  # ya tiene guía
        nuevo_pedido([(b, 1)], estado="cancelado", estado_pago="pagado")         # cancelado: no se envía
        nuevo_pedido([(b, 1)], metodo_entrega="recoger", estado_pago="pagado")   # sin envío
        nueva_cuenta(rol="superadmin")
        nueva_cuenta(activo=False)

        r = self.client.get("/api/admin/resumen/", headers=self.sesion)

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"pedidos": 9, "por_cobrar": 2, "envios_por_capturar": 2, "usuarios": 3})

    def test_cambio_de_estado_escribe_historial_y_no_toca_el_pago(self):
        """El PATCH cambia sólo el estado logístico y deja un paso en el historial; no repite el paso ni acepta estados ajenos."""
        pedido = nuevo_pedido([(self.blanco, 1)], estado_pago="pagado")
        ruta = f"/api/admin/pedidos/{pedido.id}/"

        r = self.llamar("patch", ruta, {"estado": "confirmado", "estado_pago": "reembolsado"}, headers=self.sesion)

        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["estado"], r.json()["estado_pago"]), ("confirmado", "pagado"))
        pedido.refresh_from_db()
        self.assertEqual((pedido.estado, pedido.estado_pago), ("confirmado", "pagado"))
        self.assertEqual(list(pedido.historial.values_list("estado", flat=True)), ["confirmado"])
        with self.subTest("el mismo estado otra vez"):
            self.assertEqual(self.llamar("patch", ruta, {"estado": "confirmado"}, headers=self.sesion).status_code, 200)
            self.assertEqual(pedido.historial.count(), 1)
        with self.subTest("estado fuera de la lista"):
            self.assertEqual(self.llamar("patch", ruta, {"estado": "pagado"}, headers=self.sesion).status_code, 400)
        with self.subTest("pedido inexistente"):
            r = self.llamar("patch", f"/api/admin/pedidos/{uuid.uuid4()}/", {"estado": "enviado"}, headers=self.sesion)
            self.assertEqual(r.status_code, 404)
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, "confirmado")

    def test_guia_sin_pago_confirmado_da_409(self):
        """La guía de un pedido sin pago confirmado da 409 y no cambia nada; un pedido para recoger no tiene envío (404)."""
        pedido = nuevo_pedido([(self.blanco, 1)])
        recoger = nuevo_pedido([(self.blanco, 1)], metodo_entrega="recoger", estado_pago="pagado")

        r = self.llamar("post", f"/api/admin/envios/{pedido.id}/guia/", GUIA, headers=self.sesion)

        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json(), {"detail": "La guía se captura cuando el pago esté confirmado."})
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, "pendiente")
        self.assertIsNone(Envio.objects.get(pedido=pedido).guia)
        self.assertFalse(pedido.historial.exists())
        self.assertFalse(Notificacion.objects.exists())
        self.assertEqual(self.llamar("post", f"/api/admin/envios/{recoger.id}/guia/", GUIA, headers=self.sesion).status_code,
                         404)

    def test_guia_con_pago_confirmado_pasa_a_enviado_y_encola_aviso(self):
        """Con el pago confirmado, la guía se guarda, el pedido pasa a enviado, el aviso entra a la cola y el seguimiento la muestra."""
        pedido = nuevo_pedido([(self.blanco, 1)], estado_pago="pagado", correo="maria@ejemplo.com")
        ruta = f"/api/admin/envios/{pedido.id}/guia/"
        self.assertEqual(self.llamar("post", ruta, {"paqueteria": "Estafeta"}, headers=self.sesion).status_code, 400)

        r = self.llamar("post", ruta, GUIA, headers=self.sesion)

        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["guia"], r.json()["estado"], r.json()["aviso"]), ("EST123456789MX", "enviado", "en_cola"))
        envio = Envio.objects.get(pedido=pedido)
        self.assertEqual((envio.paqueteria, envio.guia, envio.fecha_estimada), ("Estafeta", "EST123456789MX", date(2026, 11, 20)))
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, "enviado")
        self.assertEqual(list(pedido.historial.values_list("estado", flat=True)), ["enviado"])
        aviso = Notificacion.objects.get()
        self.assertEqual((aviso.pedido_id, aviso.tipo, aviso.estado, aviso.destinatario),
                         (pedido.id, "envio", "en_cola", "maria@ejemplo.com"))
        seguimiento = self.client.post("/api/pedidos/seguimiento/", {"correo": "maria@ejemplo.com", "folio": pedido.folio},
                                       content_type="application/json").json()
        self.assertEqual(seguimiento["envio_info"], GUIA)

    def test_listados_de_pedidos_envios_pagos_y_avisos(self):
        """Los listados del panel devuelven pedidos, envíos, intentos de cobro y los avisos de cada intento."""
        con_envio = nuevo_pedido([(self.blanco, 2)], estado_pago="pagado")
        recoger = nuevo_pedido([(self.blanco, 1)], metodo_entrega="recoger")
        pago = Pago.objects.create(pedido=con_envio, referencia="cs_test_lista1", importe=con_envio.total, estado="pagado")
        PagoEvento.objects.create(pago=pago, clave="evt_test_lista1", tipo="checkout.session.completed", datos={})

        pedidos = self.client.get("/api/admin/pedidos/", headers=self.sesion).json()
        envios = self.client.get("/api/admin/envios/", headers=self.sesion).json()
        pagos = self.client.get("/api/admin/pagos/", headers=self.sesion).json()
        eventos = self.client.get(f"/api/admin/pagos/{pago.id}/eventos/", headers=self.sesion).json()

        self.assertCountEqual([(p["folio"], p["estado_pago"], p["total"]) for p in pedidos],
                              [(con_envio.folio, "pagado", "811.98"), (recoger.folio, "pendiente", "405.99")])
        self.assertEqual([(e["folio"], e["direccion"]["codigo_postal"], e["guia"]) for e in envios],
                         [(con_envio.folio, "47730", None)])
        self.assertEqual([(p["folio"], p["referencia"], p["importe"], p["estado"]) for p in pagos],
                         [(con_envio.folio, "cs_test_lista1", "811.98", "pagado")])
        self.assertEqual([(e["clave"], e["tipo"], e["repeticiones"]) for e in eventos],
                         [("evt_test_lista1", "checkout.session.completed", 0)])
        self.assertEqual(self.client.get(f"/api/admin/pagos/{uuid.uuid4()}/eventos/", headers=self.sesion).status_code, 404)

    def test_texto_legal_publico_y_edicion_desde_el_panel(self):
        """El texto legal se lee sin sesión; editarlo pide la sesión del panel y el cambio se ve en la ruta pública."""
        TextoLegal.objects.create(clave="privacidad", titulo="Aviso de privacidad", contenido="Texto original.")
        nuevo = {"titulo": "Aviso de privacidad", "contenido": "Texto revisado."}

        self.assertEqual(self.client.get("/api/legal/privacidad/").json()["contenido"], "Texto original.")
        self.assertEqual(self.client.get("/api/legal/no-existe/").status_code, 404)
        self.assertEqual(self.llamar("put", "/api/admin/legal/privacidad/", nuevo).status_code, 401)
        self.assertEqual(self.llamar("put", "/api/admin/legal/privacidad/", nuevo, headers=self.sesion).status_code, 200)
        self.assertEqual(self.llamar("put", "/api/admin/legal/no-existe/", nuevo, headers=self.sesion).status_code, 404)
        self.assertEqual(self.client.get("/api/legal/privacidad/").json()["contenido"], "Texto revisado.")
