"""python manage.py enviar_correos · manda los avisos que siguen en la cola o que fallaron, hasta un máximo de intentos."""
from django.conf import settings
from django.core.management.base import BaseCommand

from pedidos.correos import enviar
from pedidos.models import Notificacion


class Command(BaseCommand):
    help = "Manda con Resend los correos del pedido que siguen en la cola o que fallaron."

    def add_arguments(self, parser):
        parser.add_argument("--max-intentos", type=int, default=5,
                            help="no reintenta los avisos que ya fallaron este número de veces (5 por omisión)")

    def handle(self, *args, **opciones):
        if not settings.RESEND_API_KEY:
            self.stdout.write("Falta RESEND_API_KEY: los avisos se quedan en la cola.")
            return
        pendientes = (Notificacion.objects.select_related("pedido")
                      .filter(estado__in=["en_cola", "fallido"], intentos__lt=opciones["max_intentos"]).order_by("creado"))
        enviados = fallidos = 0
        for notificacion in pendientes:
            if enviar(notificacion):
                enviados += 1
            else:
                fallidos += 1
        self.stdout.write(f"Enviados: {enviados}. Fallidos: {fallidos}.")
