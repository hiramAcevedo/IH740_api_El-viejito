"""Las rutas públicas de la API: la compra, el regreso de la pasarela, el seguimiento y los textos legales.

- GET  /api/productos/                 lectura pública: los productos activos con su precio.
- POST /api/pedidos/calcular/          cotiza el carrito con los precios de la base, el IVA y el envío.
- POST /api/pedidos/crear/             registra el pedido con el importe de aquí, la dirección y la confirmación de edad.
- POST /api/pagos/sesion/              abre la sesión de Checkout de Stripe y registra el intento en pagos.
- GET  /api/pagos/regreso/             lo que pregunta la pantalla de regreso del sitio: la sesión y lo que ya sabe la base.
- POST /api/pedidos/seguimiento/       el pedido, sólo si correo y folio coinciden.
- GET  /api/pedidos/seguimiento/<f>/   lo mismo con la liga firmada del correo de confirmación.
- GET  /api/legal/<clave>/             aviso de privacidad, términos de venta y leyenda.
Las del panel están en panel.py y el aviso de la pasarela en webhook.py.
"""
import hashlib
import hmac
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import stripe
from django.conf import settings
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Envio, Pago, Pedidos, Productos, TextoLegal
from .serializers import CarritoSerializer, PedidoSerializer, SeguimientoSerializer, SesionPagoSerializer

stripe.api_key = settings.STRIPE_SECRET_KEY
CENTAVO = Decimal("0.01")


def cotizar(items, metodo_entrega):
    """El importe del carrito con los precios vigentes de la base; el sitio sólo manda producto y cantidad."""
    ids = [str(i["producto_id"]) for i in items]
    productos = {str(p.id): p for p in Productos.objects.filter(id__in=ids, activo=True)}
    faltan = [i for i in ids if i not in productos]
    if faltan:
        raise serializers.ValidationError({"items": f"Producto inexistente o inactivo: {', '.join(faltan)}"})
    lineas = []
    for i in items:
        p = productos[str(i["producto_id"])]
        lineas.append({"id": str(p.id), "nombre": p.nombre, "precio": str(p.precio),
                       "cantidad": i["cantidad"], "subtotal": str(p.precio * i["cantidad"])})
    subtotal = sum(Decimal(l["subtotal"]) for l in lineas)
    iva = (subtotal * settings.IVA).quantize(CENTAVO, ROUND_HALF_UP)
    envio = settings.COSTO_ENVIO if metodo_entrega == "envio" else Decimal("0.00")
    return {"lineas": lineas, "subtotal": str(subtotal), "iva": str(iva), "envio": str(envio),
            "total": str(subtotal + iva + envio), "moneda": "mxn"}


def importes(pedido):
    """El desglose de un pedido ya guardado: el subtotal sale de sus líneas y el IVA de su total."""
    subtotal = sum(Decimal(l["subtotal"]) for l in (pedido.detalle or []))
    envio = settings.COSTO_ENVIO if pedido.metodo_entrega == "envio" else Decimal("0.00")
    total = pedido.total or Decimal("0.00")
    return {"lineas": pedido.detalle or [], "subtotal": f"{subtotal:.2f}", "iva": f"{total - subtotal - envio:.2f}",
            "envio": f"{envio:.2f}", "total": f"{total:.2f}"}


def firma_seguimiento(folio, correo):
    """La firma de la liga del correo de confirmación: sólo quien tiene el correo la conoce."""
    mensaje = f"{folio.upper()}:{correo.lower()}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), mensaje, hashlib.sha256).hexdigest()[:24]


@api_view(["GET"])
def productos(request):
    datos = Productos.objects.filter(activo=True).order_by("precio").values("id", "nombre", "tipo", "precio")
    return Response(list(datos))


@api_view(["POST"])
def calcular(request):
    carrito = CarritoSerializer(data=request.data)
    carrito.is_valid(raise_exception=True)
    return Response(cotizar(carrito.validated_data["items"], carrito.validated_data["metodo_entrega"]))


@api_view(["POST"])
def crear(request):
    datos = PedidoSerializer(data=request.data)
    datos.is_valid(raise_exception=True)
    d = datos.validated_data
    cotizacion = cotizar(d["items"], d["metodo_entrega"])
    with transaction.atomic():
        pedido = Pedidos.objects.create(
            cliente_nombre=d["cliente_nombre"], cliente_email=d["cliente_email"],
            telefono=d.get("telefono") or None, notas=d.get("notas") or None,
            metodo_entrega=d["metodo_entrega"], detalle=cotizacion["lineas"],
            cantidad=sum(l["cantidad"] for l in cotizacion["lineas"]),
            total=Decimal(cotizacion["total"]), estado="pendiente", estado_pago="pendiente",
        )
        if d["metodo_entrega"] == "envio":
            Envio.objects.create(pedido=pedido, **d["direccion"])
    return Response({"id": pedido.id, "folio": pedido.folio, **cotizacion}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def sesion_pago(request):
    datos = SesionPagoSerializer(data=request.data)
    datos.is_valid(raise_exception=True)
    pedido = Pedidos.objects.filter(id=datos.validated_data["pedido_id"]).first()
    if pedido is None or pedido.estado != "pendiente" or pedido.estado_pago == "pagado":
        return Response({"detail": "El pedido no existe o ya no está pendiente de pago."}, status=status.HTTP_404_NOT_FOUND)
    # las líneas salen de lo que se guardó en el pedido, no de lo que mande el navegador
    lineas = [{"price_data": {"currency": "mxn", "unit_amount": int(Decimal(l["precio"]) * 100),
                              "product_data": {"name": l["nombre"]}}, "quantity": l["cantidad"]}
              for l in pedido.detalle]
    subtotal = sum(Decimal(l["subtotal"]) for l in pedido.detalle)
    iva = pedido.total - subtotal
    lineas.append({"price_data": {"currency": "mxn", "unit_amount": int(iva * 100),
                                  "product_data": {"name": "IVA (16 %)"}}, "quantity": 1})
    with transaction.atomic():
        sesion = stripe.checkout.Session.create(
            mode="payment", line_items=lineas, customer_email=pedido.cliente_email,
            client_reference_id=str(pedido.id), metadata={"pedido_id": str(pedido.id), "folio": pedido.folio},
            # el comprador vuelve al sitio; la pantalla le pregunta a la API en qué estado quedó
            success_url=f"{settings.SITIO_URL}/pago/confirmado?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.SITIO_URL}/pago/error?session_id={{CHECKOUT_SESSION_ID}}",
        )
        Pago.objects.create(pedido=pedido, referencia=sesion.id, importe=pedido.total)
    return Response({"folio": pedido.folio, "sesion": sesion.id, "importe": str(pedido.total),
                     "url": sesion.url}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def regreso(request):
    """La sesión según Stripe y el pedido según la base. La pantalla da el pago por confirmado cuando la base ya lo
    tiene en pagado, es decir, cuando llegó el aviso de la pasarela; mientras tanto muestra "Confirmando el pago"."""
    try:
        sesion = stripe.checkout.Session.retrieve(request.query_params.get("session_id", ""))
    except stripe.InvalidRequestError:
        return Response({"detail": "No encontramos esa sesión de pago."}, status=status.HTTP_404_NOT_FOUND)
    # en stripe 16 la metadata es un StripeObject, no un dict: se convierte antes de leerla
    pedido = Pedidos.objects.filter(id=sesion.metadata.to_dict().get("pedido_id")).first()
    if pedido is None:
        return Response({"detail": "No encontramos ese pedido."}, status=status.HTTP_404_NOT_FOUND)
    vence = datetime.fromtimestamp(sesion.expires_at, tz=timezone.utc).isoformat() if sesion.expires_at else None
    return Response({"folio": pedido.folio, "sesion": sesion.id, "estado_sesion": sesion.status, "pago": sesion.payment_status,
                     "importe": f"{Decimal(sesion.amount_total) / 100:.2f}", "estado_pago": pedido.estado_pago,
                     "url": sesion.url if sesion.status == "open" else None, "vence": vence, **importes(pedido)})


def seguimiento_de(pedido):
    envio = getattr(pedido, "envio", None) if pedido.metodo_entrega == "envio" else None
    con_guia = envio is not None and envio.guia
    return {
        "folio": pedido.folio, "creado": pedido.created_at, "estado": pedido.estado, "estado_pago": pedido.estado_pago,
        "metodo_entrega": pedido.metodo_entrega, **importes(pedido),
        "historial": [{"estado": h.estado, "fecha": h.fecha} for h in pedido.historial.all()],
        "envio_info": {"paqueteria": envio.paqueteria, "guia": envio.guia, "fecha_estimada": envio.fecha_estimada}
        if con_guia else None,
    }


def pedido_por_folio(folio):
    # el folio son los primeros ocho caracteres del id del pedido
    return Pedidos.objects.extra(where=["id::text LIKE %s"], params=[folio.lower() + "%"]).first()


NO_COINCIDE = {"detail": "No encontramos un pedido con esos datos. Revisa el correo y el folio."}


@api_view(["POST"])
def seguimiento(request):
    datos = SeguimientoSerializer(data=request.data)
    if not datos.is_valid():
        return Response(NO_COINCIDE, status=status.HTTP_404_NOT_FOUND)
    pedido = pedido_por_folio(datos.validated_data["folio"])
    # el mismo mensaje si no existe el folio o si el correo no es el del pedido: no dice cuál de los dos falló
    if pedido is None or pedido.cliente_email.lower() != datos.validated_data["correo"].lower():
        return Response(NO_COINCIDE, status=status.HTTP_404_NOT_FOUND)
    return Response(seguimiento_de(pedido))


@api_view(["GET"])
def seguimiento_firmado(request, folio):
    pedido = pedido_por_folio(folio)
    firma = request.query_params.get("firma", "")
    if pedido is None or not hmac.compare_digest(firma, firma_seguimiento(pedido.folio, pedido.cliente_email)):
        return Response({"detail": "La liga no es válida."}, status=status.HTTP_404_NOT_FOUND)
    return Response(seguimiento_de(pedido))


@api_view(["GET"])
def legal(request, clave):
    texto = TextoLegal.objects.filter(clave=clave).first()
    if texto is None:
        return Response({"detail": "Ese texto no existe."}, status=status.HTTP_404_NOT_FOUND)
    return Response({"clave": texto.clave, "titulo": texto.titulo, "contenido": texto.contenido, "actualizado": texto.actualizado})
