"""Modelos de la API.

Productos, Pedidos y UsuariosAdmin son las tablas que ya usa el sitio: salieron de la base con
inspectdb y quedan como managed = False, así que Django las lee y escribe pero nunca las altera.
La única columna nueva en ellas, pedidos.estado_pago, la agrega una migración con SQL aditivo.
Pago es la tabla del sprint 2; las del sprint 4 (envíos, avisos de la pasarela, historial, textos legales,
cola de correos e invitaciones) las crean las migraciones de esta app, todas con RLS y sin políticas.
"""
import uuid

from django.db import models
from django.db.models.functions import Now


class Productos(models.Model):
    id = models.UUIDField(primary_key=True)
    nombre = models.TextField()
    descripcion = models.TextField(blank=True, null=True)
    tipo = models.TextField(blank=True, null=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    imagen_url = models.TextField(blank=True, null=True)
    activo = models.BooleanField()
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "productos"


class Pedidos(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    cliente_nombre = models.TextField()
    cliente_email = models.TextField()
    producto = models.ForeignKey(Productos, models.DB_SET_NULL, blank=True, null=True)
    cantidad = models.IntegerField()
    total = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    estado = models.TextField()
    notas = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(db_default=Now())
    telefono = models.TextField(blank=True, null=True)
    metodo_entrega = models.TextField(blank=True, null=True)
    detalle = models.JSONField(blank=True, null=True)
    # el estado del cobro, aparte del logístico: lo escribe sólo el aviso de la pasarela (columna del sprint 4)
    estado_pago = models.TextField(default="pendiente")

    class Meta:
        managed = False
        db_table = "pedidos"

    @property
    def folio(self):
        # el mismo folio que ya muestra el sitio: los primeros ocho caracteres del id
        return str(self.id)[:8].upper()


class UsuariosAdmin(models.Model):
    id = models.UUIDField(primary_key=True)
    nombre = models.TextField()
    email = models.TextField(unique=True)
    rol = models.TextField()
    activo = models.BooleanField()
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "usuarios_admin"


class Pago(models.Model):
    """Cada intento de cobro de un pedido: una sesión de Checkout de la pasarela."""

    ESTADOS = [("creado", "Creado"), ("pagado", "Pagado"), ("fallido", "Fallido"), ("expirado", "Expirado"),
               ("reembolsado", "Reembolsado")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pedido = models.ForeignKey(Pedidos, models.DB_CASCADE, related_name="pagos")
    proveedor = models.TextField(default="stripe")
    referencia = models.TextField(unique=True)          # id de la sesión de Checkout (cs_test_...)
    payment_intent = models.TextField(blank=True, null=True)  # para ubicar los avisos que llegan por el cobro
    estado = models.TextField(choices=ESTADOS, default="creado")
    importe = models.DecimalField(max_digits=10, decimal_places=2)
    moneda = models.TextField(default="mxn")
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pagos"


class Envio(models.Model):
    """La dirección de entrega en campos propios y, cuando sale, la paquetería con su guía."""

    pedido = models.OneToOneField(Pedidos, models.DB_CASCADE, primary_key=True, related_name="envio")
    calle = models.TextField()
    colonia = models.TextField()
    codigo_postal = models.TextField()
    ciudad = models.TextField()
    estado = models.TextField()
    paqueteria = models.TextField(blank=True, null=True)
    guia = models.TextField(blank=True, null=True)
    fecha_estimada = models.DateField(blank=True, null=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "envios"


class PagoEvento(models.Model):
    """Cada aviso de la pasarela, una sola vez: el id del evento es la clave de idempotencia. Si el mismo aviso
    vuelve a llegar, no se aplica otra vez; sólo se cuenta en repeticiones."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pago = models.ForeignKey(Pago, models.DB_SET_NULL, blank=True, null=True, related_name="eventos")
    clave = models.TextField(unique=True)
    tipo = models.TextField()
    datos = models.JSONField()
    recibido = models.DateTimeField(auto_now_add=True)
    repeticiones = models.IntegerField(default=0)
    ultima_repeticion = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "pagos_eventos"


class HistorialPedido(models.Model):
    """Los estados por los que pasa un pedido, con su fecha: lo que dibuja la línea del seguimiento."""

    pedido = models.ForeignKey(Pedidos, models.DB_CASCADE, related_name="historial")
    estado = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pedidos_historial"
        ordering = ["fecha"]


class TextoLegal(models.Model):
    """El aviso de privacidad, los términos de venta y la leyenda de venta a mayores: se editan desde el panel."""

    clave = models.TextField(primary_key=True)
    titulo = models.TextField()
    contenido = models.TextField()
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "textos_legales"


class Notificacion(models.Model):
    """La cola de correos del pedido. El envío real necesita un servicio de correo y no es de este sprint."""

    TIPOS = [("confirmacion", "Confirmación"), ("pendiente", "Pago pendiente"), ("envio", "Aviso de envío")]

    pedido = models.ForeignKey(Pedidos, models.DB_CASCADE, related_name="notificaciones")
    tipo = models.TextField(choices=TIPOS)
    destinatario = models.TextField()
    estado = models.TextField(default="en_cola")
    intentos = models.IntegerField(default=0)
    creado = models.DateTimeField(auto_now_add=True)
    enviado = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "notificaciones_pedido"


class Invitacion(models.Model):
    """La liga que genera el superadministrador: vence y sirve una sola vez."""

    clave = models.TextField(primary_key=True)
    nombre = models.TextField()
    email = models.TextField()
    rol = models.TextField(default="admin")
    vence = models.DateTimeField()
    usada = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "invitaciones"
