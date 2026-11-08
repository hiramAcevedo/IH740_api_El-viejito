"""POST /api/webhooks/pasarela/ · los avisos de Stripe.

1. Comprueba la firma con el secreto del webhook: un aviso sin firma válida se rechaza y no se guarda.
2. Guarda el aviso en pagos_eventos con su id como clave única. Si esa clave ya existe, el aviso es una repetición:
   se cuenta y no se aplica otra vez.
3. Aplica el aviso: el intento en pagos y estado_pago en el pedido, el historial y, con el pago confirmado, el correo de
   confirmación en la cola. El estado logístico del pedido no se toca.
"""
import stripe
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import HistorialPedido, Notificacion, Pago, PagoEvento


def pago_por_intent(intent_id):
    pago = Pago.objects.filter(payment_intent=intent_id).first()
    if pago is None and intent_id:
        # el aviso del cobro no trae la sesión: se busca la sesión de Checkout de ese cobro
        sesiones = stripe.checkout.Session.list(payment_intent=intent_id, limit=1)
        if sesiones.data:
            pago = Pago.objects.filter(referencia=sesiones.data[0].id).first()
            if pago is not None:
                pago.payment_intent = intent_id
                pago.save(update_fields=["payment_intent", "actualizado"])
    return pago


def marcar_pagado(pago):
    pedido = pago.pedido
    pago.estado = "pagado"
    pago.save(update_fields=["estado", "actualizado"])
    if pedido.estado_pago != "pagado":
        pedido.estado_pago = "pagado"
        pedido.save(update_fields=["estado_pago"])
        HistorialPedido.objects.create(pedido=pedido, estado="pagado")
        Notificacion.objects.create(pedido=pedido, tipo="confirmacion", destinatario=pedido.cliente_email)


def aplicar(evento):
    """Devuelve el intento de pago al que corresponde el aviso, si alguno."""
    objeto = evento.data.object
    tipo = evento.type
    if tipo.startswith("checkout.session."):
        pago = Pago.objects.filter(referencia=objeto.id).select_related("pedido").first()
        if pago is None:
            return None
        if objeto.payment_intent and not pago.payment_intent:
            pago.payment_intent = objeto.payment_intent
            pago.save(update_fields=["payment_intent", "actualizado"])
        if tipo in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
            if objeto.payment_status == "paid":
                marcar_pagado(pago)
            elif tipo == "checkout.session.completed":
                # efectivo o transferencia: la sesión terminó, el pago llega después
                Notificacion.objects.create(pedido=pago.pedido, tipo="pendiente", destinatario=pago.pedido.cliente_email)
        elif tipo == "checkout.session.async_payment_failed":
            pago.estado = "fallido"
            pago.save(update_fields=["estado", "actualizado"])
            pago.pedido.estado_pago = "rechazado"
            pago.pedido.save(update_fields=["estado_pago"])
        elif tipo == "checkout.session.expired" and pago.estado != "pagado":
            pago.estado = "expirado"
            pago.save(update_fields=["estado", "actualizado"])
        return pago
    if tipo == "payment_intent.payment_failed":
        pago = pago_por_intent(objeto.id)
        if pago is not None and pago.estado != "pagado":
            pago.estado = "fallido"
            pago.save(update_fields=["estado", "actualizado"])
            if pago.pedido.estado_pago != "pagado":
                pago.pedido.estado_pago = "rechazado"
                pago.pedido.save(update_fields=["estado_pago"])
        return pago
    if tipo in ("payment_intent.succeeded", "charge.succeeded", "charge.failed", "payment_intent.created",
                "charge.updated"):
        return pago_por_intent(getattr(objeto, "payment_intent", None) or objeto.id)
    if tipo == "charge.refunded":
        pago = pago_por_intent(objeto.payment_intent)
        if pago is not None:
            pago.estado = "reembolsado"
            pago.save(update_fields=["estado", "actualizado"])
            pago.pedido.estado_pago = "reembolsado"
            pago.pedido.save(update_fields=["estado_pago"])
            HistorialPedido.objects.create(pedido=pago.pedido, estado="reembolsado")
        return pago
    return None


@csrf_exempt
@require_POST
def webhook(request):
    try:
        evento = stripe.Webhook.construct_event(request.body, request.headers.get("Stripe-Signature", ""),
                                                settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.SignatureVerificationError):
        return JsonResponse({"detail": "Firma inválida: el aviso no se guardó."}, status=400)

    try:
        with transaction.atomic():
            registro = PagoEvento.objects.create(clave=evento.id, tipo=evento.type, datos=evento.to_dict())
            registro.pago = aplicar(evento)
            registro.save(update_fields=["pago"])
    except IntegrityError:
        # la clave ya estaba: el mismo aviso llegó otra vez y no se aplica de nuevo
        PagoEvento.objects.filter(clave=evento.id).update(repeticiones=F("repeticiones") + 1,
                                                          ultima_repeticion=timezone.now())
        return JsonResponse({"recibido": True, "aplicado": False, "evento": evento.id})
    return JsonResponse({"recibido": True, "aplicado": True, "evento": evento.id})
