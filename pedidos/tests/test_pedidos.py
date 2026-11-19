"""La compra: crear el pedido (POST /api/pedidos/crear/), abrir el cobro (POST /api/pagos/sesion/) y la pantalla de
regreso (GET /api/pagos/regreso/). Stripe va simulado con unittest.mock."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest import mock

import stripe
from django.conf import settings
from django.test import TestCase

from pedidos.models import Envio, Pago, Pedidos, Productos

from .comun import DIRECCION, nuevo_pedido, nuevo_producto, objeto_stripe


class CrearPedidoTests(TestCase):
    URL = "/api/pedidos/crear/"

    def setUp(self):
        self.blanco = nuevo_producto("Tequila Blanco 750 ml", "349.99")

    def datos(self, **cambios):
        datos = {"cliente_nombre": "María López", "cliente_email": "maria@ejemplo.com", "telefono": "3312345678",
                 "items": [{"producto_id": str(self.blanco.id), "cantidad": 2}], "metodo_entrega": "envio",
                 "direccion": dict(DIRECCION), "confirma_mayor_de_edad": True}
        datos.update(cambios)
        return datos

    def crear(self, datos):
        return self.client.post(self.URL, datos, content_type="application/json")

    def test_crear_pedido_con_envio_queda_pendiente_con_lineas_y_direccion(self):
        """Crear responde 201 con id, folio y cotización; guarda el pedido pendiente con sus líneas, el total de aquí y la dirección."""
        r = self.crear(self.datos(total="1.00"))

        self.assertEqual(r.status_code, 201)
        d = r.json()
        pedido = Pedidos.objects.get(id=d["id"])
        self.assertEqual(d["folio"], str(pedido.id)[:8].upper())
        self.assertEqual((d["subtotal"], d["iva"], d["total"]), ("699.98", "112.00", "811.98"))
        self.assertEqual((pedido.estado, pedido.estado_pago, pedido.metodo_entrega), ("pendiente", "pendiente", "envio"))
        self.assertEqual((pedido.total, pedido.cantidad), (Decimal("811.98"), 2))
        self.assertEqual(pedido.detalle, [{"id": str(self.blanco.id), "nombre": "Tequila Blanco 750 ml", "precio": "349.99",
                                           "cantidad": 2, "subtotal": "699.98"}])
        envio = Envio.objects.get(pedido=pedido)
        self.assertEqual((envio.calle, envio.colonia, envio.codigo_postal, envio.ciudad, envio.estado),
                         tuple(DIRECCION.values()))
        self.assertIsNone(envio.guia)
        self.assertFalse(pedido.pagos.exists())

    def test_crear_pedido_para_recoger_no_guarda_direccion(self):
        """Con recoger en tienda la dirección no hace falta y no se guarda envío."""
        r = self.crear(self.datos(metodo_entrega="recoger", direccion=None))

        self.assertEqual(r.status_code, 201)
        pedido = Pedidos.objects.get(id=r.json()["id"])
        self.assertEqual(pedido.metodo_entrega, "recoger")
        self.assertFalse(Envio.objects.filter(pedido=pedido).exists())

    def test_crear_pedido_con_datos_invalidos_da_400_y_no_guarda_nada(self):
        """Sin la confirmación de edad, sin dirección con envío o con datos mal formados: 400 y la base queda igual."""
        sin_edad = self.datos()
        del sin_edad["confirma_mayor_de_edad"]
        casos = {
            "confirma_mayor_de_edad en false": self.datos(confirma_mayor_de_edad=False),
            "sin confirma_mayor_de_edad": sin_edad,
            "envío sin dirección": self.datos(direccion=None),
            "código postal de cuatro dígitos": self.datos(direccion={**DIRECCION, "codigo_postal": "4773"}),
            "correo inválido": self.datos(cliente_email="maria-arroba-ejemplo"),
            "nombre vacío": self.datos(cliente_nombre=""),
            "producto inexistente": self.datos(items=[{"producto_id": str(uuid.uuid4()), "cantidad": 1}]),
            "25 piezas": self.datos(items=[{"producto_id": str(self.blanco.id), "cantidad": 25}]),
        }
        for caso, datos in casos.items():
            with self.subTest(caso):
                self.assertEqual(self.crear(datos).status_code, 400)
        self.assertEqual((Pedidos.objects.count(), Envio.objects.count()), (0, 0))


class SesionDePagoTests(TestCase):
    URL = "/api/pagos/sesion/"

    def setUp(self):
        self.blanco = nuevo_producto("Tequila Blanco 750 ml", "349.99")
        self.pedido = nuevo_pedido([(self.blanco, 2)])  # total 811.98

    def abrir(self, pedido_id):
        return self.client.post(self.URL, {"pedido_id": str(pedido_id)}, content_type="application/json")

    def test_sesion_usa_el_importe_guardado_y_registra_el_intento(self):
        """La sesión de Stripe cobra lo guardado en el pedido aunque el precio cambie después, y el intento queda en pagos."""
        Productos.objects.filter(id=self.blanco.id).update(precio=Decimal("999.00"))
        sesion = objeto_stripe({"id": "cs_test_sesion1", "object": "checkout.session",
                                "url": "https://checkout.stripe.com/c/pay/cs_test_sesion1"})

        with mock.patch.object(stripe.checkout.Session, "create", return_value=sesion) as crear_sesion:
            r = self.abrir(self.pedido.id)

        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json(), {"folio": self.pedido.folio, "sesion": "cs_test_sesion1", "importe": "811.98",
                                    "url": "https://checkout.stripe.com/c/pay/cs_test_sesion1"})
        crear_sesion.assert_called_once()
        enviado = crear_sesion.call_args.kwargs
        self.assertEqual([(l["price_data"]["product_data"]["name"], l["price_data"]["unit_amount"], l["quantity"])
                          for l in enviado["line_items"]],
                         [("Tequila Blanco 750 ml", 34999, 2), ("IVA (16 %)", 11200, 1)])
        self.assertEqual(sum(l["price_data"]["unit_amount"] * l["quantity"] for l in enviado["line_items"]), 81198)
        self.assertEqual((enviado["mode"], enviado["customer_email"], enviado["client_reference_id"]),
                         ("payment", "cliente@ejemplo.com", str(self.pedido.id)))
        self.assertEqual(enviado["metadata"], {"pedido_id": str(self.pedido.id), "folio": self.pedido.folio})
        self.assertEqual(enviado["success_url"], f"{settings.SITIO_URL}/pago/confirmado?session_id={{CHECKOUT_SESSION_ID}}")
        self.assertEqual(enviado["cancel_url"], f"{settings.SITIO_URL}/pago/error?session_id={{CHECKOUT_SESSION_ID}}")
        pago = Pago.objects.get(pedido=self.pedido)
        self.assertEqual((pago.referencia, pago.importe, pago.estado, pago.proveedor, pago.moneda),
                         ("cs_test_sesion1", Decimal("811.98"), "creado", "stripe", "mxn"))

    def test_sesion_rechaza_pedido_pagado_cancelado_inexistente_o_id_invalido(self):
        """Pedido pagado, cancelado o inexistente: 404 sin llamar a Stripe; un id que no es UUID: 400."""
        pagado = nuevo_pedido([(self.blanco, 1)], estado_pago="pagado")
        cancelado = nuevo_pedido([(self.blanco, 1)], estado="cancelado")
        casos = [("pedido ya pagado", pagado.id, 404), ("pedido cancelado", cancelado.id, 404),
                 ("pedido inexistente", uuid.uuid4(), 404), ("id que no es UUID", "' OR 1=1 --", 400)]

        with mock.patch.object(stripe.checkout.Session, "create") as crear_sesion:
            for caso, pedido_id, codigo in casos:
                with self.subTest(caso):
                    self.assertEqual(self.abrir(pedido_id).status_code, codigo)

        crear_sesion.assert_not_called()
        self.assertFalse(Pago.objects.exists())


class RegresoDePagoTests(TestCase):
    URL = "/api/pagos/regreso/"
    VENCE = 1795000000

    def setUp(self):
        self.blanco = nuevo_producto("Tequila Blanco 750 ml", "349.99")
        self.pedido = nuevo_pedido([(self.blanco, 2)])

    def sesion(self, **campos):
        datos = {"id": "cs_test_regreso1", "object": "checkout.session", "status": "complete", "payment_status": "paid",
                 "amount_total": 81198, "currency": "mxn", "url": None, "expires_at": self.VENCE,
                 "metadata": {"pedido_id": str(self.pedido.id), "folio": self.pedido.folio}}
        datos.update(campos)
        return objeto_stripe(datos)

    def regreso(self, sesion):
        with mock.patch.object(stripe.checkout.Session, "retrieve", return_value=sesion) as consultar:
            r = self.client.get(self.URL, {"session_id": sesion.id})
        consultar.assert_called_once_with(sesion.id)
        return r

    def test_regreso_pagado_y_confirmado_por_el_aviso(self):
        """Stripe dice pagada y el aviso ya llegó: estado_pago pagado, sin liga de cobro y con el desglose del pedido."""
        Pedidos.objects.filter(id=self.pedido.id).update(estado_pago="pagado")

        r = self.regreso(self.sesion())

        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual((d["estado_sesion"], d["pago"], d["estado_pago"]), ("complete", "paid", "pagado"))
        self.assertEqual((d["folio"], d["sesion"], d["importe"], d["url"]),
                         (self.pedido.folio, "cs_test_regreso1", "811.98", None))
        self.assertEqual((d["subtotal"], d["iva"], d["envio"], d["total"]), ("699.98", "112.00", "0.00", "811.98"))

    def test_regreso_pagado_en_stripe_sin_aviso_sigue_pendiente(self):
        """Stripe ya cobró pero el aviso no ha llegado: la base sigue en pendiente (la pantalla muestra Confirmando el pago)."""
        r = self.regreso(self.sesion())

        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["pago"], r.json()["estado_pago"]), ("paid", "pendiente"))

    def test_regreso_sesion_abierta_devuelve_la_liga_y_el_vencimiento(self):
        """Sesión abierta sin pagar: pendiente, con la liga para volver a Stripe y la hora en que vence."""
        url = "https://checkout.stripe.com/c/pay/cs_test_regreso1"

        r = self.regreso(self.sesion(status="open", payment_status="unpaid", url=url))

        d = r.json()
        self.assertEqual((d["estado_sesion"], d["pago"], d["estado_pago"], d["url"]), ("open", "unpaid", "pendiente", url))
        self.assertEqual(d["vence"], datetime.fromtimestamp(self.VENCE, tz=timezone.utc).isoformat())

    def test_regreso_sesion_expirada_sin_liga(self):
        """Sesión expirada: pendiente y sin liga de cobro, aunque Stripe todavía mande una."""
        r = self.regreso(self.sesion(status="expired", payment_status="unpaid",
                                     url="https://checkout.stripe.com/c/pay/cs_test_regreso1"))

        d = r.json()
        self.assertEqual((d["estado_sesion"], d["pago"], d["estado_pago"], d["url"]),
                         ("expired", "unpaid", "pendiente", None))

    def test_regreso_sesion_o_pedido_desconocido_da_404(self):
        """Sesión que Stripe no conoce, sin session_id o con un pedido que no existe en la base: 404."""
        no_existe = stripe.InvalidRequestError("No such checkout.session: cs_test_nada", "id")
        with mock.patch.object(stripe.checkout.Session, "retrieve", side_effect=no_existe):
            with self.subTest("sesión desconocida"):
                self.assertEqual(self.client.get(self.URL, {"session_id": "cs_test_nada"}).status_code, 404)
            with self.subTest("sin session_id"):
                self.assertEqual(self.client.get(self.URL).status_code, 404)
        with self.subTest("pedido que no existe"):
            ajena = self.sesion(metadata={"pedido_id": str(uuid.uuid4())})
            self.assertEqual(self.regreso(ajena).status_code, 404)
