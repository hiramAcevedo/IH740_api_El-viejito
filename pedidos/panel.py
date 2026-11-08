"""Las rutas del panel. Todas piden la sesión de Supabase Auth que el panel ya usa: la API valida el token y que la
cuenta siga activa en usuarios_admin; las de usuarios e invitaciones, además, que sea el superadministrador.

- GET   /api/admin/resumen/                las cuentas del dashboard
- GET   /api/admin/pedidos/                los pedidos con su estado logístico y el del pago
- PATCH /api/admin/pedidos/<id>/           sólo el estado logístico; el del pago lo escribe el aviso de la pasarela
- GET   /api/admin/envios/                 los pedidos con envío, su dirección y su guía
- POST  /api/admin/envios/<id>/guia/       paquetería, guía y fecha: el pedido pasa a enviado y el aviso a la cola
- GET   /api/admin/pagos/                  los intentos de cobro
- GET   /api/admin/pagos/<id>/eventos/     los avisos de la pasarela de un intento
- PUT   /api/admin/legal/<clave>/          un texto legal
- GET, POST          /api/admin/usuarios/        las cuentas y las invitaciones abiertas; el alta directa
- PATCH, DELETE      /api/admin/usuarios/<id>/   apagar, encender o dar de baja
- POST  /api/admin/invitaciones/           la liga de invitación
- GET, POST /api/invitaciones/<clave>/     pública: leer la invitación y crear la cuenta
"""
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from .models import Envio, HistorialPedido, Invitacion, Notificacion, Pago, Pedidos, TextoLegal, UsuariosAdmin
from .serializers import (AceptarInvitacionSerializer, CambioUsuarioSerializer, EstadoPedidoSerializer, GuiaSerializer,
                          InvitacionSerializer, TextoLegalSerializer, UsuarioNuevoSerializer)
from .sesion import ConSesion, EsSuperadmin, SesionSupabase
from .supabase_admin import borrar_cuenta, crear_cuenta
from .views import importes


def del_panel(*metodos, superadmin=False):
    """Una ruta del panel: los métodos, la sesión de Supabase y, si hace falta, el rol de superadministrador."""
    permisos = [ConSesion, EsSuperadmin] if superadmin else [ConSesion]

    def decorar(vista):
        return api_view(list(metodos))(authentication_classes([SesionSupabase])(permission_classes(permisos)(vista)))
    return decorar


def pedido_del_panel(p):
    return {"id": p.id, "folio": p.folio, "creado": p.created_at, "cliente_nombre": p.cliente_nombre,
            "cliente_email": p.cliente_email, "telefono": p.telefono, "estado": p.estado, "estado_pago": p.estado_pago,
            "metodo_entrega": p.metodo_entrega, "notas": p.notas, **importes(p)}


@del_panel("GET")
def resumen(request):
    con_guia = Envio.objects.exclude(guia__isnull=True).exclude(guia="").values_list("pedido_id", flat=True)
    return Response({
        "pedidos": Pedidos.objects.count(),
        "por_cobrar": Pedidos.objects.filter(estado_pago="pendiente").exclude(estado="cancelado").count(),
        "envios_por_capturar": Envio.objects.filter(pedido__estado_pago="pagado").exclude(pedido__estado="cancelado")
        .exclude(pedido_id__in=con_guia).count(),
        "usuarios": UsuariosAdmin.objects.count(),
    })


@del_panel("GET")
def pedidos(request):
    return Response([pedido_del_panel(p) for p in Pedidos.objects.order_by("-created_at")[:200]])


@del_panel("PATCH")
def pedido(request, pedido_id):
    p = Pedidos.objects.filter(id=pedido_id).first()
    if p is None:
        return Response({"detail": "Ese pedido no existe."}, status=status.HTTP_404_NOT_FOUND)
    datos = EstadoPedidoSerializer(data=request.data)
    datos.is_valid(raise_exception=True)
    if p.estado != datos.validated_data["estado"]:
        p.estado = datos.validated_data["estado"]
        p.save(update_fields=["estado"])
        HistorialPedido.objects.create(pedido=p, estado=p.estado)
    return Response(pedido_del_panel(p))


def envio_del_panel(e):
    p = e.pedido
    return {"pedido_id": p.id, "folio": p.folio, "cliente_nombre": p.cliente_nombre, "estado": p.estado,
            "estado_pago": p.estado_pago,
            "direccion": {"calle": e.calle, "colonia": e.colonia, "codigo_postal": e.codigo_postal, "ciudad": e.ciudad,
                          "estado": e.estado},
            "paqueteria": e.paqueteria, "guia": e.guia, "fecha_estimada": e.fecha_estimada,
            "aviso": p.notificaciones.filter(tipo="envio").values_list("estado", flat=True).last()}


@del_panel("GET")
def envios(request):
    lista = Envio.objects.select_related("pedido").exclude(pedido__estado="cancelado").order_by("-pedido__created_at")
    return Response([envio_del_panel(e) for e in lista])


@del_panel("POST")
def guia(request, pedido_id):
    e = Envio.objects.select_related("pedido").filter(pedido_id=pedido_id).first()
    if e is None:
        return Response({"detail": "Ese pedido no tiene envío a domicilio."}, status=status.HTTP_404_NOT_FOUND)
    if e.pedido.estado_pago != "pagado":
        return Response({"detail": "La guía se captura cuando el pago esté confirmado."}, status=status.HTTP_409_CONFLICT)
    datos = GuiaSerializer(data=request.data)
    datos.is_valid(raise_exception=True)
    with transaction.atomic():
        for campo, valor in datos.validated_data.items():
            setattr(e, campo, valor)
        e.save()
        e.pedido.estado = "enviado"
        e.pedido.save(update_fields=["estado"])
        HistorialPedido.objects.create(pedido=e.pedido, estado="enviado")
        Notificacion.objects.create(pedido=e.pedido, tipo="envio", destinatario=e.pedido.cliente_email)
    return Response(envio_del_panel(e))


@del_panel("GET")
def pagos(request):
    return Response([{"id": p.id, "pedido": p.pedido_id, "folio": p.pedido.folio, "creado": p.creado,
                      "proveedor": p.proveedor, "referencia": p.referencia, "importe": str(p.importe), "estado": p.estado}
                     for p in Pago.objects.select_related("pedido").order_by("-creado")[:200]])


@del_panel("GET")
def eventos(request, pago_id):
    pago = Pago.objects.filter(id=pago_id).first()
    if pago is None:
        return Response({"detail": "Ese intento no existe."}, status=status.HTTP_404_NOT_FOUND)
    return Response([{"recibido": e.recibido, "tipo": e.tipo, "clave": e.clave, "aplicado": True,
                      "repeticiones": e.repeticiones} for e in pago.eventos.order_by("recibido")])


@del_panel("PUT")
def legal(request, clave):
    texto = TextoLegal.objects.filter(clave=clave).first()
    if texto is None:
        return Response({"detail": "Ese texto no existe."}, status=status.HTTP_404_NOT_FOUND)
    datos = TextoLegalSerializer(data=request.data)
    datos.is_valid(raise_exception=True)
    texto.titulo, texto.contenido = datos.validated_data["titulo"], datos.validated_data["contenido"]
    texto.save()
    return Response({"clave": texto.clave, "titulo": texto.titulo, "contenido": texto.contenido, "actualizado": texto.actualizado})


def liga(clave):
    return f"/admin/registro?invitacion={clave}"


def usuario_del_panel(u):
    return {"id": u.id, "nombre": u.nombre, "email": u.email, "rol": u.rol, "estado": "activo" if u.activo else "apagado"}


@del_panel("GET", "POST", superadmin=True)
def usuarios(request):
    if request.method == "POST":
        datos = UsuarioNuevoSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        d = datos.validated_data
        nuevo_id = crear_cuenta(d["email"], d["contrasena"], d["nombre"])
        u = UsuariosAdmin.objects.create(id=nuevo_id, nombre=d["nombre"], email=d["email"], rol="admin", activo=True,
                                         created_at=timezone.now())
        return Response(usuario_del_panel(u), status=status.HTTP_201_CREATED)
    lista = [usuario_del_panel(u) for u in UsuariosAdmin.objects.order_by("-rol", "nombre")]
    abiertas = Invitacion.objects.filter(usada=False, vence__gt=timezone.now()).order_by("creado")
    lista += [{"id": f"inv-{i.clave[:8]}", "nombre": i.nombre, "email": i.email, "rol": i.rol, "estado": "invitado",
               "vence": i.vence, "liga": liga(i.clave)} for i in abiertas]
    return Response(lista)


@del_panel("PATCH", "DELETE", superadmin=True)
def usuario(request, usuario_id):
    u = UsuariosAdmin.objects.filter(id=usuario_id).first()
    if u is None:
        return Response({"detail": "Esa cuenta no existe."}, status=status.HTTP_404_NOT_FOUND)
    if u.rol == "superadmin":
        return Response({"detail": "La cuenta del superadministrador no se apaga ni se borra desde el panel."},
                        status=status.HTTP_403_FORBIDDEN)
    if request.method == "DELETE":
        u.delete()
        borrar_cuenta(usuario_id)  # sin la llave de servicio, la cuenta de Auth queda, pero ya no entra al panel
        return Response(status=status.HTTP_204_NO_CONTENT)
    datos = CambioUsuarioSerializer(data=request.data)
    datos.is_valid(raise_exception=True)
    if "estado" in datos.validated_data:
        u.activo = datos.validated_data["estado"] == "activo"
    u.save()
    return Response(usuario_del_panel(u))


@del_panel("POST", superadmin=True)
def invitar(request):
    datos = InvitacionSerializer(data=request.data)
    datos.is_valid(raise_exception=True)
    inv = Invitacion.objects.create(clave=secrets.token_urlsafe(24), vence=timezone.now() + timedelta(days=5),
                                    **datos.validated_data)
    return Response({"liga": liga(inv.clave), "vence": inv.vence}, status=status.HTTP_201_CREATED)


VENCIDA = {"detail": "La invitación ya se usó o venció. Pide una nueva a quien te invitó."}


@api_view(["GET", "POST"])
def invitacion(request, clave):
    inv = Invitacion.objects.filter(clave=clave, usada=False, vence__gt=timezone.now()).first()
    if inv is None:
        return Response(VENCIDA, status=status.HTTP_410_GONE)
    if request.method == "GET":
        return Response({"nombre": inv.nombre, "email": inv.email, "rol": inv.rol, "vence": inv.vence})
    datos = AceptarInvitacionSerializer(data=request.data)
    datos.is_valid(raise_exception=True)
    nuevo_id = crear_cuenta(inv.email, datos.validated_data["contrasena"], datos.validated_data["nombre"])
    with transaction.atomic():
        UsuariosAdmin.objects.create(id=nuevo_id, nombre=datos.validated_data["nombre"], email=inv.email, rol=inv.rol,
                                     activo=True, created_at=timezone.now())
        inv.usada = True
        inv.save(update_fields=["usada"])
    return Response({"ok": True}, status=status.HTTP_201_CREATED)
