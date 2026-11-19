"""Los avisos de Stripe: POST /api/webhooks/pasarela/. Cada aviso se firma aquí con un secreto de prueba, como lo
haría Stripe: HMAC-SHA256 de "{momento}.{cuerpo}" en la cabecera Stripe-Signature (t=...,v1=...)."""
import json
import time
from unittest import mock

import stripe
from django.conf import settings
from django.test import TestCase, override_settings

from pedidos.models import Notificacion, Pago, PagoEvento

from .comun import SECRETO_WEBHOOK, evento_stripe, firmar, nuevo_pedido, nuevo_producto


@override_settings(STRIPE_WEBHOOK_SECRET=SECRETO_WEBHOOK)
class WebhookTests(TestCase):
    URL = "/api/webhooks/pasarela/"

    def setUp(self):
        self.blanco = nuevo_producto("Tequila Blanco 750 ml", "349.99")
        self.pedido = nuevo_pedido([(self.blanco, 2)])
        self.pago = Pago.objects.create(pedido=self.pedido, referencia="cs_test_webhook1", importe=self.pedido.total)

    def avisar(self, evento=None, *, cuerpo=None, cabecera=None, sin_firma=False):
        cuerpo = json.dumps(evento) if cuerpo is None else cuerpo
        cabeceras = {} if sin_firma else {"Stripe-Signature": cabecera or firmar(cuerpo)}
        return self.client.post(self.URL, cuerpo, content_type="application/json", headers=cabeceras)

    def sesion(self, **campos):
        objeto = {"id": "cs_test_webhook1", "object": "checkout.session", "payment_intent": "pi_test_webhook1",
                  "payment_status": "paid", "status": "complete", "amount_total": 81198, "currency": "mxn",
                  "metadata": {"pedido_id": str(self.pedido.id), "folio": self.pedido.folio}}
        objeto.update(campos)
        return objeto

    def recargar(self):
        self.pago.refresh_from_db()
        self.pedido.refresh_from_db()

    def test_aviso_sin_firma_da_400_y_no_guarda_nada(self):
        """Un aviso sin la cabecera Stripe-Signature se rechaza con 400 y no se guarda ni se aplica."""
        r = self.avisar(evento_stripe("checkout.session.completed", self.sesion()), sin_firma=True)

        self.assertEqual(r.status_code, 400)
        self.assertFalse(PagoEvento.objects.exists())
        self.recargar()
        self.assertEqual((self.pago.estado, self.pedido.estado_pago), ("creado", "pendiente"))

    def test_aviso_con_firma_invalida_da_400_y_no_guarda_nada(self):
        """Firma de otro secreto, cuerpo alterado, firma vencida o cabecera mal formada: 400 y nada guardado."""
        cuerpo = json.dumps(evento_stripe("checkout.session.completed", self.sesion()))
        alterado = cuerpo.replace("81198", "100")
        casos = {
            "firmado con otro secreto": (cuerpo, firmar(cuerpo, secreto="whsec_de_otra_cuenta")),
            "cuerpo alterado después de firmar": (alterado, firmar(cuerpo)),
            "firma de hace 10 minutos (tolerancia de 5)": (cuerpo, firmar(cuerpo, momento=int(time.time()) - 600)),
            "cabecera sin v1": (cuerpo, f"t={int(time.time())}"),
            "cabecera sin formato": (cuerpo, "basura"),
            "cuerpo que no es JSON, bien firmado": ("esto no es json", firmar("esto no es json")),
        }
        for caso, (enviado, cabecera) in casos.items():
            with self.subTest(caso):
                self.assertEqual(self.avisar(cuerpo=enviado, cabecera=cabecera).status_code, 400)

        self.assertFalse(PagoEvento.objects.exists())
        self.recargar()
        self.assertEqual((self.pago.estado, self.pedido.estado_pago), ("creado", "pendiente"))

    def test_pago_completado_marca_pagado_guarda_evento_historial_y_correo(self):
        """checkout.session.completed pagada: intento y pedido en pagado, aviso en pagos_eventos, paso en el historial y correo en la cola."""
        r = self.avisar(evento_stripe("checkout.session.completed", self.sesion(), id_evento="evt_test_completado"))

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"recibido": True, "aplicado": True, "evento": "evt_test_completado"})
        self.recargar()
        self.assertEqual((self.pago.estado, self.pago.payment_intent), ("pagado", "pi_test_webhook1"))
        self.assertEqual(self.pedido.estado_pago, "pagado")
        self.assertEqual(self.pedido.estado, "pendiente")  # el estado logístico no lo toca el aviso
        registro = PagoEvento.objects.get()
        self.assertEqual((registro.clave, registro.tipo, registro.pago_id, registro.repeticiones),
                         ("evt_test_completado", "checkout.session.completed", self.pago.id, 0))
        self.assertEqual(registro.datos["data"]["object"]["id"], "cs_test_webhook1")
        self.assertEqual(list(self.pedido.historial.values_list("estado", flat=True)), ["pagado"])
        correo = Notificacion.objects.get()
        self.assertEqual((correo.pedido_id, correo.tipo, correo.estado, correo.destinatario),
                         (self.pedido.id, "confirmacion", "en_cola", "cliente@ejemplo.com"))

    def test_aviso_repetido_se_aplica_una_sola_vez(self):
        """El mismo id de evento otra vez responde 200 sin aplicarse: sólo cuenta la repetición."""
        evento = evento_stripe("checkout.session.completed", self.sesion(), id_evento="evt_test_repetido")

        primero = self.avisar(evento)
        segundo = self.avisar(evento)
        tercero = self.avisar(evento)

        self.assertEqual(primero.json()["aplicado"], True)
        for repetido in (segundo, tercero):
            self.assertEqual(repetido.status_code, 200)
            self.assertEqual(repetido.json(), {"recibido": True, "aplicado": False, "evento": "evt_test_repetido"})
        registro = PagoEvento.objects.get()
        self.assertEqual(registro.repeticiones, 2)
        self.assertIsNotNone(registro.ultima_repeticion)
        self.assertEqual(self.pedido.historial.count(), 1)
        self.assertEqual(Notificacion.objects.count(), 1)

    def test_sesion_expirada_marca_el_intento_expirado(self):
        """checkout.session.expired deja el intento en expirado; el pedido sigue pendiente de pago y sin correo."""
        evento = evento_stripe("checkout.session.expired",
                               self.sesion(status="expired", payment_status="unpaid", payment_intent=None))

        r = self.avisar(evento)

        self.assertEqual(r.status_code, 200)
        self.recargar()
        self.assertEqual((self.pago.estado, self.pedido.estado_pago), ("expirado", "pendiente"))
        self.assertEqual(PagoEvento.objects.get().pago_id, self.pago.id)
        self.assertFalse(Notificacion.objects.exists())

    def test_pago_fallido_ubica_la_sesion_por_el_cobro_y_lo_rechaza(self):
        """payment_intent.payment_failed: la sesión se busca en Stripe por el cobro; intento fallido y pedido rechazado."""
        lista = stripe.ListObject.construct_from(
            {"object": "list", "url": "/v1/checkout/sessions", "has_more": False,
             "data": [{"id": "cs_test_webhook1", "object": "checkout.session"}]}, settings.STRIPE_SECRET_KEY)
        cobro = {"id": "pi_test_rechazado", "object": "payment_intent", "status": "requires_payment_method",
                 "last_payment_error": {"type": "card_error", "code": "card_declined", "decline_code": "insufficient_funds"}}

        with mock.patch.object(stripe.checkout.Session, "list", return_value=lista) as buscar:
            r = self.avisar(evento_stripe("payment_intent.payment_failed", cobro))

        self.assertEqual(r.status_code, 200)
        buscar.assert_called_once_with(payment_intent="pi_test_rechazado", limit=1)
        self.recargar()
        self.assertEqual((self.pago.estado, self.pago.payment_intent), ("fallido", "pi_test_rechazado"))
        self.assertEqual(self.pedido.estado_pago, "rechazado")
        self.assertEqual(PagoEvento.objects.get().pago_id, self.pago.id)

    def test_reembolso_marca_intento_y_pedido_reembolsados(self):
        """charge.refunded de un pago confirmado: intento y pedido en reembolsado y un paso más en el historial."""
        self.avisar(evento_stripe("checkout.session.completed", self.sesion()))
        cargo = {"id": "ch_test_webhook1", "object": "charge", "payment_intent": "pi_test_webhook1", "refunded": True,
                 "amount_refunded": 81198}

        with mock.patch.object(stripe.checkout.Session, "list") as buscar:
            r = self.avisar(evento_stripe("charge.refunded", cargo))

        self.assertEqual(r.status_code, 200)
        buscar.assert_not_called()  # el intento ya tenía su payment_intent desde el pago
        self.recargar()
        self.assertEqual((self.pago.estado, self.pedido.estado_pago), ("reembolsado", "reembolsado"))
        self.assertEqual(list(self.pedido.historial.order_by("id").values_list("estado", flat=True)),
                         ["pagado", "reembolsado"])

    def test_pago_diferido_rechazado_marca_el_intento_fallido_y_el_pedido_rechazado(self):
        """checkout.session.async_payment_failed (el efectivo o la transferencia no llegó): intento fallido y pedido
        rechazado, sin correo."""
        r = self.avisar(evento_stripe("checkout.session.async_payment_failed", self.sesion(payment_status="unpaid")))

        self.assertEqual(r.status_code, 200)
        self.recargar()
        self.assertEqual((self.pago.estado, self.pedido.estado_pago), ("fallido", "rechazado"))
        self.assertFalse(Notificacion.objects.exists())

    def test_aviso_de_una_sesion_ajena_se_guarda_sin_tocar_ningun_pedido(self):
        """Un aviso de una sesión que esta API no abrió, como un evento de prueba del dashboard, se guarda sin ligarse."""
        r = self.avisar(evento_stripe("checkout.session.completed", self.sesion(id="cs_test_de_otro_lado")))

        self.assertEqual(r.status_code, 200)
        self.recargar()
        self.assertEqual((self.pago.estado, self.pedido.estado_pago), ("creado", "pendiente"))
        self.assertIsNone(PagoEvento.objects.get().pago_id)
        self.assertFalse(Notificacion.objects.exists())

    def test_avisos_del_cobro_y_del_cargo_se_ligan_al_intento_sin_cambiarlo(self):
        """payment_intent.succeeded y charge.succeeded sólo se ligan al intento: el pago lo confirma la sesión."""
        self.avisar(evento_stripe("checkout.session.completed", self.sesion()))
        cobro = {"id": "pi_test_webhook1", "object": "payment_intent", "status": "succeeded"}
        cargo = {"id": "ch_test_webhook1", "object": "charge", "payment_intent": "pi_test_webhook1", "paid": True}

        with mock.patch.object(stripe.checkout.Session, "list") as buscar:
            respuestas = [self.avisar(evento_stripe(tipo, objeto))
                          for tipo, objeto in (("payment_intent.succeeded", cobro), ("charge.succeeded", cargo))]

        self.assertEqual([r.status_code for r in respuestas], [200, 200])
        buscar.assert_not_called()
        for tipo in ("payment_intent.succeeded", "charge.succeeded"):
            self.assertEqual(PagoEvento.objects.get(tipo=tipo).pago_id, self.pago.id)
        self.recargar()
        self.assertEqual((self.pago.estado, self.pedido.estado_pago), ("pagado", "pagado"))
        self.assertEqual(self.pedido.historial.count(), 1)

    def test_tipo_de_aviso_que_la_api_no_usa_se_guarda_sin_ligarse(self):
        r = self.avisar(evento_stripe("customer.created", {"id": "cus_test_1", "object": "customer"}))

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["aplicado"], True)
        self.assertIsNone(PagoEvento.objects.get().pago_id)

    def test_otro_aviso_del_mismo_pago_no_duplica_historial_ni_correo(self):
        """Si otro aviso confirma el mismo pago, como el del pago diferido tras el de la sesión, el pedido no suma otro
        paso al historial ni otro correo."""
        self.avisar(evento_stripe("checkout.session.completed", self.sesion()))
        r = self.avisar(evento_stripe("checkout.session.async_payment_succeeded", self.sesion()))

        self.assertEqual(r.status_code, 200)
        self.recargar()
        self.assertEqual((self.pago.estado, self.pedido.estado_pago), ("pagado", "pagado"))
        self.assertEqual(self.pedido.historial.count(), 1)
        self.assertEqual(Notificacion.objects.count(), 1)

    def test_el_pago_solo_se_marca_con_payment_status_paid(self):
        """Un aviso de pago diferido que no trae payment_status paid no marca el pago ni manda correo."""
        r = self.avisar(evento_stripe("checkout.session.async_payment_succeeded", self.sesion(payment_status="unpaid")))

        self.assertEqual(r.status_code, 200)
        self.recargar()
        self.assertEqual((self.pago.estado, self.pedido.estado_pago), ("creado", "pendiente"))
        self.assertFalse(Notificacion.objects.exists())

    def test_avisos_fuera_de_orden_no_deshacen_un_pago_confirmado(self):
        """Si después del pago llegan la expiración de la sesión o un cobro fallido, el pago sigue confirmado."""
        self.avisar(evento_stripe("checkout.session.completed", self.sesion()))
        fallido = {"id": "pi_test_webhook1", "object": "payment_intent", "status": "requires_payment_method"}

        self.avisar(evento_stripe("checkout.session.expired", self.sesion(status="expired")))
        self.avisar(evento_stripe("payment_intent.payment_failed", fallido))

        self.recargar()
        self.assertEqual((self.pago.estado, self.pedido.estado_pago), ("pagado", "pagado"))

    def test_el_cobro_fallido_de_otra_sesion_no_rechaza_un_pedido_ya_pagado(self):
        """Si el cliente abrió dos sesiones y pagó una, el cobro fallido de la otra no rechaza el pedido."""
        self.avisar(evento_stripe("checkout.session.completed", self.sesion()))
        otro = Pago.objects.create(pedido=self.pedido, referencia="cs_test_webhook2", payment_intent="pi_test_webhook2",
                                   importe=self.pedido.total)

        self.avisar(evento_stripe("payment_intent.payment_failed",
                                  {"id": "pi_test_webhook2", "object": "payment_intent", "status": "requires_payment_method"}))

        otro.refresh_from_db()
        self.recargar()
        self.assertEqual(otro.estado, "fallido")
        self.assertEqual(self.pedido.estado_pago, "pagado")

    def test_avisos_de_cobros_ajenos_se_guardan_sin_ligarse(self):
        """Un cobro que no salió de una sesión de esta API (Stripe no da sesión, o da una que no es nuestra) no toca nada."""
        def lista(*ids):
            return stripe.ListObject.construct_from(
                {"object": "list", "url": "/v1/checkout/sessions", "has_more": False,
                 "data": [{"id": i, "object": "checkout.session"} for i in ids]}, settings.STRIPE_SECRET_KEY)

        with mock.patch.object(stripe.checkout.Session, "list", side_effect=[lista(), lista("cs_test_de_otro_lado")]):
            fallo = self.avisar(evento_stripe("payment_intent.payment_failed", {"id": "pi_test_ajeno1", "object": "payment_intent"}))
            reembolso = self.avisar(evento_stripe("charge.refunded", {"id": "ch_test_ajeno", "object": "charge",
                                                                      "payment_intent": "pi_test_ajeno2"}))

        self.assertEqual((fallo.status_code, reembolso.status_code), (200, 200))
        self.assertEqual(list(PagoEvento.objects.values_list("pago_id", flat=True)), [None, None])
        self.recargar()
        self.assertEqual((self.pago.estado, self.pedido.estado_pago), ("creado", "pendiente"))
