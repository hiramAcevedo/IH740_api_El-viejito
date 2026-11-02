"""Los endpoints del contrato de la Integradora 2 que tocan en los sprints 1 y 2.

- GET  /api/productos/        lectura pública: los productos activos con su precio.
- POST /api/pedidos/calcular/ cotiza el carrito con los precios de la base, el IVA y el envío.
- POST /api/pedidos/crear/    registra el pedido con el importe calculado aquí y devuelve su folio.
- POST /api/pagos/sesion/     abre la sesión de Checkout de Stripe y registra el intento en pagos.
- GET  /api/pagos/regreso/    a donde vuelve el comprador: el estado de su sesión en Stripe.
- GET  /api/admin/pedidos/    operación del panel: sin la sesión de Supabase responde 401.
"""
from decimal import ROUND_HALF_UP, Decimal

import stripe
from django.conf import settings
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from .models import Pago, Pedidos, Productos
from .serializers import CarritoSerializer, PedidoSerializer, SesionPagoSerializer
from .sesion import ConSesion, SesionSupabase

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
    pedido = Pedidos.objects.create(
        cliente_nombre=d["cliente_nombre"], cliente_email=d["cliente_email"],
        telefono=d.get("telefono") or None, notas=d.get("notas") or None,
        metodo_entrega=d["metodo_entrega"], detalle=cotizacion["lineas"],
        cantidad=sum(l["cantidad"] for l in cotizacion["lineas"]),
        total=Decimal(cotizacion["total"]), estado="pendiente",
    )
    return Response({"id": pedido.id, "folio": pedido.folio, **cotizacion}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def sesion_pago(request):
    datos = SesionPagoSerializer(data=request.data)
    datos.is_valid(raise_exception=True)
    pedido = Pedidos.objects.filter(id=datos.validated_data["pedido_id"]).first()
    if pedido is None or pedido.estado != "pendiente":
        return Response({"detail": "El pedido no existe o ya no está pendiente."}, status=status.HTTP_404_NOT_FOUND)
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
            success_url=f"{settings.REGRESO_URL}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.REGRESO_URL}?session_id={{CHECKOUT_SESSION_ID}}",
        )
        Pago.objects.create(pedido=pedido, referencia=sesion.id, importe=pedido.total)
    return Response({"folio": pedido.folio, "sesion": sesion.id, "importe": str(pedido.total),
                     "url": sesion.url}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def regreso(request):
    # el estado definitivo lo escribirá el webhook (sprint 3); aquí sólo se informa lo que dice Stripe
    sesion = stripe.checkout.Session.retrieve(request.query_params.get("session_id", ""))
    # en stripe 16 la metadata es un StripeObject, no un dict: se convierte antes de leerla
    return Response({"folio": sesion.metadata.to_dict().get("folio"), "sesion": sesion.id, "estado_sesion": sesion.status,
                     "pago": sesion.payment_status, "importe": f"{Decimal(sesion.amount_total) / 100:.2f}"})


@api_view(["GET"])
@authentication_classes([SesionSupabase])
@permission_classes([ConSesion])
def pedidos_admin(request):
    datos = Pedidos.objects.order_by("-created_at").values("id", "cliente_nombre", "total", "estado")[:20]
    return Response(list(datos))
