from django.urls import path

from . import views

urlpatterns = [
    path("productos/", views.productos),
    path("pedidos/calcular/", views.calcular),
    path("pedidos/crear/", views.crear),
    path("pagos/sesion/", views.sesion_pago),
    path("pagos/regreso/", views.regreso),
    path("admin/pedidos/", views.pedidos_admin),
]
