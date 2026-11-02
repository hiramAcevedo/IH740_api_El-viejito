"""Lo que la API acepta del sitio: el carrito (producto y cantidad) y los datos del comprador.

El sitio nunca manda precios ni totales: el importe lo calcula el servidor con los precios de la base.
"""
from rest_framework import serializers


class LineaSerializer(serializers.Serializer):
    producto_id = serializers.UUIDField()
    cantidad = serializers.IntegerField(min_value=1, max_value=24)


class CarritoSerializer(serializers.Serializer):
    items = LineaSerializer(many=True, allow_empty=False)
    metodo_entrega = serializers.ChoiceField(choices=["envio", "recoger"], default="envio")


class PedidoSerializer(CarritoSerializer):
    cliente_nombre = serializers.CharField(max_length=120)
    cliente_email = serializers.EmailField()
    telefono = serializers.CharField(max_length=20, required=False, allow_blank=True)
    notas = serializers.CharField(max_length=500, required=False, allow_blank=True)


class SesionPagoSerializer(serializers.Serializer):
    pedido_id = serializers.UUIDField()
