"""Lo que comparten las pruebas: datos de partida, respuestas simuladas de Stripe y Supabase y la firma de los avisos."""
import hashlib
import hmac
import json
import time
import uuid
from decimal import ROUND_HALF_UP, Decimal
from unittest import mock

import requests
import stripe
from django.conf import settings
from django.utils import timezone

from pedidos.models import Envio, Pedidos, Productos, UsuariosAdmin

IVA = Decimal("0.16")
CENTAVO = Decimal("0.01")
SECRETO_WEBHOOK = "whsec_secreto_de_las_pruebas"
DIRECCION = {"calle": "Av. Hidalgo 120", "colonia": "Centro", "codigo_postal": "47730", "ciudad": "Tototlán",
             "estado": "Jalisco"}


def nuevo_producto(nombre="Tequila Blanco 750 ml", precio="349.99", activo=True, tipo="Blanco"):
    return Productos.objects.create(id=uuid.uuid4(), nombre=nombre, tipo=tipo, precio=Decimal(precio), activo=activo,
                                    created_at=timezone.now())


def nuevo_pedido(lineas, *, metodo_entrega="envio", estado="pendiente", estado_pago="pendiente",
                 correo="cliente@ejemplo.com", nombre="Cliente de Prueba", guia=None):
    """Un pedido como lo deja /api/pedidos/crear/: líneas con el precio de la base, total con IVA y, con envío, la
    dirección. lineas es una lista de (producto, cantidad)."""
    detalle = [{"id": str(p.id), "nombre": p.nombre, "precio": str(p.precio), "cantidad": c,
                "subtotal": str(p.precio * c)} for p, c in lineas]
    subtotal = sum(Decimal(linea["subtotal"]) for linea in detalle)
    total = subtotal + (subtotal * IVA).quantize(CENTAVO, ROUND_HALF_UP)
    pedido = Pedidos.objects.create(cliente_nombre=nombre, cliente_email=correo, cantidad=sum(c for _, c in lineas),
                                    total=total, estado=estado, estado_pago=estado_pago, metodo_entrega=metodo_entrega,
                                    detalle=detalle)
    if metodo_entrega == "envio":
        Envio.objects.create(pedido=pedido, guia=guia, paqueteria="Estafeta" if guia else None, **DIRECCION)
    return pedido


def nueva_cuenta(rol="admin", activo=True, nombre="Cuenta de Prueba"):
    return UsuariosAdmin.objects.create(id=uuid.uuid4(), nombre=nombre, email=f"{uuid.uuid4().hex[:10]}@elviejito.mx",
                                        rol=rol, activo=activo, created_at=timezone.now())


def respuesta_http(codigo, datos):
    """Una respuesta de requests como la que daría Supabase, sin salir a la red."""
    respuesta = requests.Response()
    respuesta.status_code = codigo
    respuesta._content = json.dumps(datos).encode()
    respuesta.headers["Content-Type"] = "application/json"
    return respuesta


def objeto_stripe(datos, clase=stripe.checkout.Session):
    """Un objeto del SDK de Stripe armado desde un dict, igual que los que regresa la API real."""
    return clase.construct_from(datos, settings.STRIPE_SECRET_KEY)


def evento_stripe(tipo, objeto, id_evento=None):
    return {"id": id_evento or f"evt_test_{uuid.uuid4().hex[:20]}", "object": "event", "type": tipo,
            "created": int(time.time()), "livemode": False, "data": {"object": objeto}}


def firmar(cuerpo, secreto=SECRETO_WEBHOOK, momento=None):
    """La cabecera Stripe-Signature: HMAC-SHA256 de "{momento}.{cuerpo}" con el secreto del webhook."""
    momento = int(time.time()) if momento is None else momento
    firma = hmac.new(secreto.encode(), f"{momento}.{cuerpo}".encode(), hashlib.sha256).hexdigest()
    return f"t={momento},v1={firma}"


def firma_de_seguimiento(folio, correo):
    """La firma de la liga del correo de confirmación, calculada aparte de la app: HMAC-SHA256 de "FOLIO:correo"."""
    mensaje = f"{folio.upper()}:{correo.lower()}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), mensaje, hashlib.sha256).hexdigest()[:24]


class SinErroresDelServidor:
    def assertSin500(self, respuesta, caso=""):
        """Falla con la excepción de la vista si la API respondió 5xx (con un Client(raise_request_exception=False))."""
        if respuesta.status_code >= 500:
            info = getattr(respuesta, "exc_info", None)
            causa = repr(info[1]) if info else respuesta.content[:200]
            self.fail(f"{caso}: la API respondió {respuesta.status_code} por {causa}")


class ConPanel(SinErroresDelServidor):
    """Supabase Auth simulado: cada token registrado con sesion_de() es de una cuenta; cualquier otro, Supabase lo
    rechaza con 401. Ninguna llamada sale a la red."""

    def setUp(self):
        super().setUp()
        self.tokens = {}
        parche = mock.patch("pedidos.sesion.requests.get", side_effect=self._supabase_auth)
        self.supabase_auth = parche.start()
        self.addCleanup(parche.stop)

    def _supabase_auth(self, url, **kwargs):
        cuenta = self.tokens.get(kwargs["headers"]["Authorization"].removeprefix("Bearer "))
        if cuenta is None:
            return respuesta_http(401, {"code": 401, "error_code": "bad_jwt", "msg": "invalid JWT"})
        return respuesta_http(200, {"id": str(cuenta.id), "email": cuenta.email, "aud": "authenticated"})

    def sesion_de(self, cuenta):
        token = f"token-de-prueba-{cuenta.id}"
        self.tokens[token] = cuenta
        return {"Authorization": f"Bearer {token}"}

    def llamar(self, metodo, ruta, datos=None, **kwargs):
        if datos is None:
            return getattr(self.client, metodo)(ruta, **kwargs)
        return getattr(self.client, metodo)(ruta, datos, content_type="application/json", **kwargs)
