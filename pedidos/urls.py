from django.urls import path

from . import panel, views, webhook

urlpatterns = [
    # la compra y el regreso de la pasarela
    path("productos/", views.productos),
    path("pedidos/calcular/", views.calcular),
    path("pedidos/crear/", views.crear),
    path("pagos/sesion/", views.sesion_pago),
    path("pagos/regreso/", views.regreso),
    # el aviso de la pasarela
    path("webhooks/pasarela/", webhook.webhook),
    # el seguimiento sin cuenta y los textos legales
    path("pedidos/seguimiento/", views.seguimiento),
    path("pedidos/seguimiento/<str:folio>/", views.seguimiento_firmado),
    path("legal/<str:clave>/", views.legal),
    # el panel
    path("admin/resumen/", panel.resumen),
    path("admin/pedidos/", panel.pedidos),
    path("admin/pedidos/<uuid:pedido_id>/", panel.pedido),
    path("admin/envios/", panel.envios),
    path("admin/envios/<uuid:pedido_id>/guia/", panel.guia),
    path("admin/pagos/", panel.pagos),
    path("admin/pagos/<uuid:pago_id>/eventos/", panel.eventos),
    path("admin/legal/<str:clave>/", panel.legal),
    path("admin/usuarios/", panel.usuarios),
    path("admin/usuarios/<uuid:usuario_id>/", panel.usuario),
    path("admin/invitaciones/", panel.invitar),
    path("invitaciones/<str:clave>/", panel.invitacion),
]
