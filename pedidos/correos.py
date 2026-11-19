"""Los correos del pedido: la confirmación del pago, el pago pendiente y el aviso de envío.

Cada aviso se guarda primero en la cola (notificaciones_pedido) y, cuando la transacción que lo creó se confirma, sale
con Resend. El envío es de mejor esfuerzo: si falla, o si la API no tiene RESEND_API_KEY, el aviso queda en la cola con
su estado y el comando enviar_correos lo reintenta. Nunca rompe la respuesta de quien lo encoló, y un aviso repetido de
Stripe no manda otro correo, porque el webhook no aplica dos veces el mismo aviso. Resend recibe además una llave de
idempotencia por aviso, así que un reintento no duplica un correo que ya salió.
"""
import logging
import re
from datetime import timedelta
from decimal import Decimal

import requests
from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from .models import Notificacion, TextoLegal

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
PLANTILLAS = {"confirmacion": "correos/confirmacion.html", "pendiente": "correos/pago-pendiente.html",
              "envio": "correos/aviso-envio.html"}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre",
         "diciembre"]
LEYENDA = "Prohibida la venta a menores de edad. El abuso en el consumo de este producto es nocivo para la salud."
# Stripe Checkout cierra la sesión 24 horas después de abrirla, si no se le pide otra cosa
VIGENCIA_SESION = timedelta(hours=24)


def pesos(valor):
    return f"{Decimal(valor):,.2f}"


def fecha(dia):
    return f"{dia.day} de {MESES[dia.month - 1]}"


def fecha_hora(momento):
    local = timezone.localtime(momento)
    hora = local.strftime("%I:%M").lstrip("0") or "12:00"
    return f"{fecha(local)}, {hora} {'a.m.' if local.hour < 12 else 'p.m.'}"


def liga_seguimiento(pedido):
    from .views import firma_seguimiento  # aquí, para no importar views al cargar el módulo
    return f"{settings.SITIO_URL}/seguimiento/{pedido.folio}?firma={firma_seguimiento(pedido.folio, pedido.cliente_email)}"


def contexto(notificacion):
    """Los datos de la plantilla, sacados del pedido tal como está guardado."""
    from .views import importes
    pedido = notificacion.pedido
    texto = TextoLegal.objects.filter(clave="leyenda").first()
    datos = {"nombre": pedido.cliente_nombre, "folio": pedido.folio, "leyenda": texto.contenido if texto else LEYENDA}
    if notificacion.tipo == "confirmacion":
        cuenta = importes(pedido)
        envio = Decimal(cuenta["envio"])
        datos.update(lineas=[{"nombre": l["nombre"], "cantidad": l["cantidad"], "subtotal": pesos(l["subtotal"])}
                             for l in cuenta["lineas"]],
                     subtotal=pesos(cuenta["subtotal"]), iva=pesos(cuenta["iva"]),
                     envio="Sin costo" if envio == 0 else f"${pesos(envio)}", total=pesos(cuenta["total"]),
                     liga_seguimiento=liga_seguimiento(pedido))
    elif notificacion.tipo == "pendiente":
        pago = pedido.pagos.order_by("-creado").first()
        datos.update(total=pesos(pedido.total or 0),
                     liga_pago=f"{settings.SITIO_URL}/pago/pendiente?session_id={pago.referencia}" if pago else settings.SITIO_URL,
                     vence=fecha_hora(pago.creado + VIGENCIA_SESION) if pago else "las próximas 24 horas")
    else:
        envio = pedido.envio
        datos.update(paqueteria=envio.paqueteria, guia=envio.guia,
                     fecha_estimada=fecha(envio.fecha_estimada) if envio.fecha_estimada else "por confirmar",
                     liga_seguimiento=liga_seguimiento(pedido))
    return datos


def componer(notificacion):
    """El asunto y el HTML del correo; el asunto es el título de la plantilla."""
    html = render_to_string(PLANTILLAS[notificacion.tipo], contexto(notificacion))
    asunto = re.search(r"<title>(.*?)</title>", html, re.S).group(1).strip()
    return asunto, html


def enviar(notificacion):
    """Manda un aviso de la cola. Devuelve True si salió; sin llave no intenta nada y el aviso sigue en la cola."""
    if not settings.RESEND_API_KEY:
        return False
    if notificacion.estado == "enviado":
        return True
    try:
        asunto, html = componer(notificacion)
        respuesta = requests.post(RESEND_URL, timeout=10, json={
            "from": settings.CORREO_REMITENTE, "to": [notificacion.destinatario], "subject": asunto, "html": html,
        }, headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Idempotency-Key": f"notificacion-{notificacion.id}"})
        salio = respuesta.status_code in (200, 201)
        if not salio:
            log.warning("Resend rechazó el aviso %s: %s", notificacion.id, respuesta.status_code)
    except Exception:  # el correo nunca tumba a quien lo encoló
        log.exception("No se pudo mandar el aviso %s", notificacion.id)
        salio = False
    notificacion.intentos += 1
    notificacion.estado = "enviado" if salio else "fallido"
    notificacion.enviado = timezone.now() if salio else None
    notificacion.save(update_fields=["estado", "intentos", "enviado"])
    return salio


def enviar_por_id(notificacion_id):
    notificacion = Notificacion.objects.select_related("pedido").filter(id=notificacion_id).first()
    return enviar(notificacion) if notificacion else False


def encolar(pedido, tipo):
    """Deja el aviso en la cola y lo manda cuando se confirme la transacción que lo creó."""
    notificacion = Notificacion.objects.create(pedido=pedido, tipo=tipo, destinatario=pedido.cliente_email)
    transaction.on_commit(lambda: enviar_por_id(notificacion.id))
    return notificacion
