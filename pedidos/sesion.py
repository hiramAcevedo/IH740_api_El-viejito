"""La sesión del panel: el token de Supabase Auth que el panel ya usa, validado en el servidor.

Sin token, la petición se rechaza con 401. Con token, Supabase Auth dice de quién es y la API
comprueba en usuarios_admin que la cuenta siga activa.
"""
import requests
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from .models import UsuariosAdmin


class SesionSupabase(BaseAuthentication):
    def authenticate(self, request):
        cabecera = request.headers.get("Authorization", "")
        if not cabecera.startswith("Bearer "):
            return None
        token = cabecera.removeprefix("Bearer ").strip()
        respuesta = requests.get(
            f"{settings.SUPABASE_URL}/auth/v1/user",
            headers={"apikey": settings.SUPABASE_PUBLISHABLE_KEY, "Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if respuesta.status_code != 200:
            raise AuthenticationFailed("La sesión no es válida o ya venció.")
        admin = UsuariosAdmin.objects.filter(id=respuesta.json().get("id"), activo=True).first()
        if admin is None:
            raise AuthenticationFailed("La cuenta no está activa en el panel.")
        return (admin, token)

    def authenticate_header(self, request):
        return 'Bearer realm="panel"'


class ConSesion(BasePermission):
    message = "Hace falta la sesión del panel."

    def has_permission(self, request, view):
        return request.user is not None


class EsSuperadmin(BasePermission):
    """Usuarios e invitaciones: sólo la cuenta del superadministrador."""

    message = "Sólo el superadministrador administra las cuentas del panel."

    def has_permission(self, request, view):
        return request.user is not None and getattr(request.user, "rol", "") == "superadmin"
