"""Modelos de la API.

Productos, Pedidos y UsuariosAdmin son las tablas que ya usa el sitio: salieron de la base con
inspectdb y quedan como managed = False, así que Django las lee y escribe pero nunca las altera.
Pago es la tabla nueva del sprint 2: la crea la migración de esta app.
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

    ESTADOS = [("creado", "Creado"), ("pagado", "Pagado"), ("fallido", "Fallido"), ("expirado", "Expirado")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pedido = models.ForeignKey(Pedidos, models.DB_CASCADE, related_name="pagos")
    proveedor = models.TextField(default="stripe")
    referencia = models.TextField(unique=True)          # id de la sesión de Checkout (cs_test_...)
    estado = models.TextField(choices=ESTADOS, default="creado")
    importe = models.DecimalField(max_digits=10, decimal_places=2)
    moneda = models.TextField(default="mxn")
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pagos"
