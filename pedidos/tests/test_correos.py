"""Los correos del pedido con Resend: lo que lleva cada uno, cómo queda el aviso en la cola y que el envío nunca rompa
al webhook ni al panel. La petición a Resend siempre está simulada."""
import json
from datetime import date, datetime, timedelta
from io import StringIO
from unittest import mock
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from pedidos import correos
from pedidos.models import Envio, Notificacion, Pago, TextoLegal

from .comun import (SECRETO_WEBHOOK, ConPanel, evento_stripe, firma_de_seguimiento, firmar, nueva_cuenta, nuevo_pedido,
                    nuevo_producto, respuesta_http)

LLAVE = "re_llave_de_pruebas"


def resend_ok():
    return respuesta_http(200, {"id": "correo-de-prueba"})


class ComponerTests(TestCase):
    def setUp(self):
        self.reposado = nuevo_producto("Reposado Suave", "450.00")
        self.anejo = nuevo_producto("Añejo Premium", "680.00")
        self.pedido = nuevo_pedido([(self.reposado, 2), (self.anejo, 1)], nombre="Rosa Pérez", correo="Rosa@Ejemplo.com")

    def aviso(self, tipo):
        """El aviso leído de la base, como lo lee enviar_por_id."""
        n = Notificacion.objects.create(pedido=self.pedido, tipo=tipo, destinatario=self.pedido.cliente_email)
        return Notificacion.objects.select_related("pedido").get(id=n.id)

    def test_confirmacion_lleva_lineas_importes_y_la_liga_firmada(self):
        """La confirmación lleva el título como asunto, las líneas y los importes del pedido guardado y la liga firmada."""
        asunto, html = correos.componer(self.aviso("confirmacion"))
        self.assertEqual(asunto, f"Tu pedido #{self.pedido.folio} está confirmado")
        for texto in ("Rosa Pérez", "Reposado Suave", "Añejo Premium", "$1,580.00", "$252.80", "Sin costo", "$1,832.80"):
            self.assertIn(texto, html)
        firma = firma_de_seguimiento(self.pedido.folio, "rosa@ejemplo.com")
        self.assertIn(f"{settings.SITIO_URL}/seguimiento/{self.pedido.folio}?firma={firma}", html)
        self.assertIn(correos.LEYENDA, html)

    @override_settings(COSTO_ENVIO=correos.Decimal("99.00"))
    def test_confirmacion_con_costo_de_envio_lo_muestra_en_pesos(self):
        """Si el envío cuesta, el correo lo muestra en pesos en lugar de "Sin costo"."""
        _, html = correos.componer(self.aviso("confirmacion"))
        self.assertIn("$99.00", html)
        self.assertNotIn("Sin costo", html)

    def test_la_leyenda_sale_de_la_base_cuando_existe(self):
        """La leyenda de venta a mayores es la que el negocio editó en el panel."""
        TextoLegal.objects.create(clave="leyenda", titulo="Leyenda", contenido="Leyenda editada desde el panel.")
        _, html = correos.componer(self.aviso("confirmacion"))
        self.assertIn("Leyenda editada desde el panel.", html)
        self.assertNotIn(correos.LEYENDA, html)

    def test_pendiente_lleva_la_liga_para_completar_el_pago_y_su_vencimiento(self):
        """El pago pendiente lleva el total, la pantalla de pago pendiente con su sesión y la hora en que vence."""
        pago = Pago.objects.create(pedido=self.pedido, referencia="cs_test_pendiente", importe=self.pedido.total)
        asunto, html = correos.componer(self.aviso("pendiente"))
        self.assertEqual(asunto, f"Completa el pago de tu pedido #{self.pedido.folio}")
        self.assertIn("$1,832.80", html)
        self.assertIn(f"{settings.SITIO_URL}/pago/pendiente?session_id=cs_test_pendiente", html)
        self.assertIn(correos.fecha_hora(pago.creado + correos.VIGENCIA_SESION), html)

    def test_pendiente_sin_intento_de_pago_manda_al_sitio(self):
        """Sin un intento de pago registrado, la liga lleva al sitio y el plazo se dice en general."""
        _, html = correos.componer(self.aviso("pendiente"))
        self.assertIn(f'href="{settings.SITIO_URL}"', html)
        self.assertIn("las próximas 24 horas", html)

    def test_envio_lleva_paqueteria_guia_y_fecha_estimada(self):
        """El aviso de envío lleva la paquetería, la guía, la fecha estimada en español y la liga firmada."""
        Envio.objects.filter(pedido=self.pedido).update(paqueteria="Estafeta", guia="EST123456789MX",
                                                        fecha_estimada=date(2026, 11, 20))
        asunto, html = correos.componer(self.aviso("envio"))
        self.assertEqual(asunto, f"Tu pedido #{self.pedido.folio} va en camino")
        for texto in ("Estafeta", "EST123456789MX", "20 de noviembre"):
            self.assertIn(texto, html)
        self.assertIn(f"/seguimiento/{self.pedido.folio}?firma=", html)

    def test_envio_sin_fecha_estimada_dice_por_confirmar(self):
        Envio.objects.filter(pedido=self.pedido).update(paqueteria="Estafeta", guia="EST1", fecha_estimada=None)
        _, html = correos.componer(self.aviso("envio"))
        self.assertIn("por confirmar", html)

    def test_fechas_en_espanol_y_en_la_hora_de_la_ciudad_de_mexico(self):
        """Las fechas salen con el mes en español y la hora local de la Ciudad de México, con a.m. y p.m."""
        utc = ZoneInfo("UTC")
        self.assertEqual(correos.fecha(date(2026, 1, 5)), "5 de enero")
        self.assertEqual(correos.fecha_hora(datetime(2026, 11, 10, 0, 30, tzinfo=utc)), "9 de noviembre, 6:30 p.m.")
        self.assertEqual(correos.fecha_hora(datetime(2026, 11, 10, 15, 5, tzinfo=utc)), "10 de noviembre, 9:05 a.m.")
        self.assertEqual(correos.pesos("1234.5"), "1,234.50")


class EnviarTests(TestCase):
    def setUp(self):
        self.pedido = nuevo_pedido([(nuevo_producto(), 1)])
        self.aviso = Notificacion.objects.create(pedido=self.pedido, tipo="confirmacion", destinatario="cliente@ejemplo.com")

    @override_settings(RESEND_API_KEY=LLAVE)
    def test_sale_con_resend_y_queda_enviado(self):
        """Con llave, el correo sale por la API de Resend con el remitente, la llave y una llave de idempotencia por aviso."""
        with mock.patch("pedidos.correos.requests.post", return_value=resend_ok()) as resend:
            self.assertTrue(correos.enviar(self.aviso))
        url = resend.call_args.args[0]
        datos, cabeceras = resend.call_args.kwargs["json"], resend.call_args.kwargs["headers"]
        self.assertEqual(url, "https://api.resend.com/emails")
        self.assertEqual(datos["from"], "Tequila El Viejito <pedidos@tequilaelviejito.shop>")
        self.assertEqual(datos["to"], ["cliente@ejemplo.com"])
        self.assertEqual(datos["subject"], f"Tu pedido #{self.pedido.folio} está confirmado")
        self.assertIn("<html", datos["html"])
        self.assertEqual(cabeceras, {"Authorization": f"Bearer {LLAVE}", "Idempotency-Key": f"notificacion-{self.aviso.id}"})
        self.aviso.refresh_from_db()
        self.assertEqual((self.aviso.estado, self.aviso.intentos), ("enviado", 1))
        self.assertIsNotNone(self.aviso.enviado)

    @override_settings(RESEND_API_KEY=LLAVE)
    def test_rechazo_de_resend_queda_fallido(self):
        """Si Resend rechaza el correo, el aviso queda fallido con su intento contado, listo para reintentarse."""
        with mock.patch("pedidos.correos.requests.post", return_value=respuesta_http(422, {"message": "dominio sin verificar"})), \
                self.assertLogs("pedidos.correos", "WARNING"):
            self.assertFalse(correos.enviar(self.aviso))
        self.aviso.refresh_from_db()
        self.assertEqual((self.aviso.estado, self.aviso.intentos, self.aviso.enviado), ("fallido", 1, None))

    @override_settings(RESEND_API_KEY=LLAVE)
    def test_una_falla_de_red_no_lanza(self):
        """Una falla de red no sale de la función: el aviso queda fallido."""
        with mock.patch("pedidos.correos.requests.post", side_effect=requests.ConnectionError("sin red")), \
                self.assertLogs("pedidos.correos", "ERROR"):
            self.assertFalse(correos.enviar(self.aviso))
        self.aviso.refresh_from_db()
        self.assertEqual(self.aviso.estado, "fallido")

    def test_sin_llave_no_intenta_y_el_aviso_sigue_en_la_cola(self):
        with mock.patch("pedidos.correos.requests.post") as resend:
            self.assertFalse(correos.enviar(self.aviso))
        resend.assert_not_called()
        self.aviso.refresh_from_db()
        self.assertEqual((self.aviso.estado, self.aviso.intentos), ("en_cola", 0))

    @override_settings(RESEND_API_KEY=LLAVE)
    def test_un_aviso_ya_enviado_no_se_vuelve_a_mandar(self):
        Notificacion.objects.filter(id=self.aviso.id).update(estado="enviado")
        self.aviso.refresh_from_db()
        with mock.patch("pedidos.correos.requests.post") as resend:
            self.assertTrue(correos.enviar(self.aviso))
        resend.assert_not_called()

    def test_enviar_por_id_de_un_aviso_que_no_existe(self):
        self.assertFalse(correos.enviar_por_id(999999))


@override_settings(STRIPE_WEBHOOK_SECRET=SECRETO_WEBHOOK, RESEND_API_KEY=LLAVE)
class WebhookConCorreoTests(TestCase):
    URL = "/api/webhooks/pasarela/"

    def setUp(self):
        self.pedido = nuevo_pedido([(nuevo_producto(), 2)], correo="ana@ejemplo.com")
        self.pago = Pago.objects.create(pedido=self.pedido, referencia="cs_test_correo", importe=self.pedido.total)

    def avisar(self, evento):
        cuerpo = json.dumps(evento)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.URL, cuerpo, content_type="application/json", headers={"Stripe-Signature": firmar(cuerpo)})

    def sesion(self, **campos):
        objeto = {"id": "cs_test_correo", "object": "checkout.session", "payment_intent": "pi_test_correo",
                  "payment_status": "paid", "status": "complete", "amount_total": 81198, "currency": "mxn"}
        objeto.update(campos)
        return objeto

    def test_pago_completado_manda_un_solo_correo_aunque_el_aviso_se_repita(self):
        """El aviso de pago manda la confirmación una vez; el mismo aviso otra vez no manda otro correo."""
        evento = evento_stripe("checkout.session.completed", self.sesion(), id_evento="evt_test_correo")
        with mock.patch("pedidos.correos.requests.post", return_value=resend_ok()) as resend:
            primero, segundo = self.avisar(evento), self.avisar(evento)
        self.assertEqual((primero.status_code, segundo.status_code), (200, 200))
        self.assertEqual(resend.call_count, 1)
        aviso = Notificacion.objects.get()
        self.assertEqual((aviso.tipo, aviso.estado, aviso.destinatario), ("confirmacion", "enviado", "ana@ejemplo.com"))

    def test_si_resend_falla_el_pago_se_aplica_igual(self):
        """Con Resend caído, el webhook responde 200, el pedido queda pagado y el aviso, fallido para el reintento."""
        with mock.patch("pedidos.correos.requests.post", return_value=respuesta_http(500, {"message": "caído"})), \
                self.assertLogs("pedidos.correos", "WARNING"):
            r = self.avisar(evento_stripe("checkout.session.completed", self.sesion()))
        self.assertEqual(r.status_code, 200)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado_pago, "pagado")
        self.assertEqual(Notificacion.objects.get().estado, "fallido")

    def test_sesion_terminada_sin_pago_manda_el_correo_de_pago_pendiente(self):
        """Un pago que todavía no llega (efectivo o transferencia) manda el correo de pago pendiente."""
        with mock.patch("pedidos.correos.requests.post", return_value=resend_ok()) as resend:
            self.avisar(evento_stripe("checkout.session.completed", self.sesion(payment_status="unpaid")))
        self.assertEqual(resend.call_args.kwargs["json"]["subject"], f"Completa el pago de tu pedido #{self.pedido.folio}")
        self.assertEqual(Notificacion.objects.get().tipo, "pendiente")


@override_settings(RESEND_API_KEY=LLAVE)
class GuiaConCorreoTests(ConPanel, TestCase):
    def test_registrar_la_guia_manda_el_aviso_de_envio(self):
        """Al registrar la guía, el aviso de envío sale cuando se confirma la transacción."""
        sesion = self.sesion_de(nueva_cuenta())
        pedido = nuevo_pedido([(nuevo_producto(), 1)], estado_pago="pagado", correo="maria@ejemplo.com")
        guia = {"paqueteria": "Estafeta", "guia": "EST123456789MX", "fecha_estimada": "2026-11-20"}
        with mock.patch("pedidos.correos.requests.post", return_value=resend_ok()) as resend:
            with self.captureOnCommitCallbacks(execute=True):
                r = self.llamar("post", f"/api/admin/envios/{pedido.id}/guia/", guia, headers=sesion)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(resend.call_args.kwargs["json"]["subject"], f"Tu pedido #{pedido.folio} va en camino")
        self.assertEqual(Notificacion.objects.get().estado, "enviado")


class ComandoTests(TestCase):
    def setUp(self):
        self.pedido = nuevo_pedido([(nuevo_producto(), 1)])
        crear = lambda estado, intentos: Notificacion.objects.create(pedido=self.pedido, tipo="confirmacion",
                                                                     destinatario="c@ejemplo.com", estado=estado,
                                                                     intentos=intentos)
        self.en_cola, self.fallido = crear("en_cola", 0), crear("fallido", 1)
        self.agotado, self.enviado = crear("fallido", 5), crear("enviado", 1)

    def correr(self, *args):
        salida = StringIO()
        call_command("enviar_correos", *args, stdout=salida)
        return salida.getvalue()

    def test_sin_llave_avisa_y_no_manda_nada(self):
        with mock.patch("pedidos.correos.requests.post") as resend:
            self.assertIn("Falta RESEND_API_KEY", self.correr())
        resend.assert_not_called()

    @override_settings(RESEND_API_KEY=LLAVE)
    def test_reintenta_la_cola_y_los_fallidos_hasta_el_maximo_de_intentos(self):
        """Manda los que están en cola o fallaron con menos intentos que el máximo; no toca los enviados ni los agotados."""
        with mock.patch("pedidos.correos.requests.post", return_value=resend_ok()) as resend:
            self.assertIn("Enviados: 2. Fallidos: 0.", self.correr())
        self.assertEqual(resend.call_count, 2)
        for aviso, estado in ((self.en_cola, "enviado"), (self.fallido, "enviado"), (self.agotado, "fallido")):
            aviso.refresh_from_db()
            self.assertEqual(aviso.estado, estado)

    @override_settings(RESEND_API_KEY=LLAVE)
    def test_con_resend_caido_cuenta_los_fallidos_y_respeta_el_maximo(self):
        with mock.patch("pedidos.correos.requests.post", side_effect=requests.ConnectionError("sin red")), \
                self.assertLogs("pedidos.correos", "ERROR"):
            self.assertIn("Enviados: 0. Fallidos: 1.", self.correr("--max-intentos", "1"))
