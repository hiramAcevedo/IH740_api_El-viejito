"""Lo que la API acepta del sitio: el carrito (producto y cantidad), los datos del comprador y lo que manda el panel.

El sitio nunca manda precios ni totales: el importe lo calcula el servidor con los precios de la base.
"""
from rest_framework import serializers


class LineaSerializer(serializers.Serializer):
    producto_id = serializers.UUIDField()
    cantidad = serializers.IntegerField(min_value=1, max_value=24)


class CarritoSerializer(serializers.Serializer):
    items = LineaSerializer(many=True, allow_empty=False)
    metodo_entrega = serializers.ChoiceField(choices=["envio", "recoger"], default="envio")


class DireccionSerializer(serializers.Serializer):
    calle = serializers.CharField(max_length=160)
    colonia = serializers.CharField(max_length=120)
    codigo_postal = serializers.RegexField(r"^\d{5}$", error_messages={"invalid": "El código postal lleva cinco dígitos."})
    ciudad = serializers.CharField(max_length=120)
    estado = serializers.CharField(max_length=60)


class PedidoSerializer(CarritoSerializer):
    cliente_nombre = serializers.CharField(max_length=120)
    cliente_email = serializers.EmailField()
    telefono = serializers.CharField(max_length=20, required=False, allow_blank=True)
    notas = serializers.CharField(max_length=500, required=False, allow_blank=True)
    direccion = DireccionSerializer(required=False, allow_null=True)
    confirma_mayor_de_edad = serializers.BooleanField()

    def validate_confirma_mayor_de_edad(self, valor):
        if valor is not True:
            raise serializers.ValidationError("La venta es sólo para mayores de 18 años: hace falta la confirmación.")
        return valor

    def validate(self, datos):
        if datos.get("metodo_entrega") == "envio" and not datos.get("direccion"):
            raise serializers.ValidationError({"direccion": "Con envío a domicilio hace falta la dirección."})
        return datos


class SesionPagoSerializer(serializers.Serializer):
    pedido_id = serializers.UUIDField()


class SeguimientoSerializer(serializers.Serializer):
    correo = serializers.EmailField()
    folio = serializers.RegexField(r"^[0-9A-Fa-f]{8}$")


class EstadoPedidoSerializer(serializers.Serializer):
    estado = serializers.ChoiceField(choices=["pendiente", "confirmado", "enviado", "entregado", "cancelado"])


class GuiaSerializer(serializers.Serializer):
    paqueteria = serializers.CharField(max_length=60)
    guia = serializers.CharField(max_length=60)
    fecha_estimada = serializers.DateField()


class TextoLegalSerializer(serializers.Serializer):
    titulo = serializers.CharField(max_length=120)
    contenido = serializers.CharField(max_length=20000)


class UsuarioNuevoSerializer(serializers.Serializer):
    nombre = serializers.CharField(max_length=120)
    email = serializers.EmailField()
    contrasena = serializers.CharField(min_length=10, max_length=128, write_only=True)


class CambioUsuarioSerializer(serializers.Serializer):
    estado = serializers.ChoiceField(choices=["activo", "apagado"], required=False)
    rol = serializers.ChoiceField(choices=["admin"], required=False)


class InvitacionSerializer(serializers.Serializer):
    nombre = serializers.CharField(max_length=120)
    email = serializers.EmailField()


class AceptarInvitacionSerializer(serializers.Serializer):
    nombre = serializers.CharField(max_length=120)
    contrasena = serializers.CharField(min_length=10, max_length=128)
