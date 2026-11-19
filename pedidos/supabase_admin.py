"""Lo que sólo puede hacer el servidor en Supabase Auth: crear y borrar cuentas con la llave de servicio.

La llave de servicio nunca viaja al navegador; vive en el .env de la API (SUPABASE_SERVICE_KEY). Sin ella, el alta
directa y la aceptación de una invitación responden 503 con la razón.
"""
import requests
from django.conf import settings
from rest_framework.exceptions import APIException


class SinLlaveDeServicio(APIException):
    status_code = 503
    default_detail = "Falta la llave de servicio de Supabase en la API: no se pueden crear cuentas."


class CorreoConCuenta(APIException):
    status_code = 409
    default_detail = "Ya existe una cuenta con ese correo."


class CuentaRechazada(APIException):
    status_code = 400
    default_detail = "Supabase no creó la cuenta."


class SupabaseNoResponde(APIException):
    status_code = 502
    default_detail = "Supabase Auth no respondió; intenta de nuevo en unos minutos."


def _cabeceras():
    if not settings.SUPABASE_SERVICE_KEY:
        raise SinLlaveDeServicio()
    return {"apikey": settings.SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"}


def crear_cuenta(email, contrasena, nombre):
    """Crea la cuenta ya confirmada (el proyecto no confirma solo) y devuelve su id."""
    try:
        r = requests.post(f"{settings.SUPABASE_URL}/auth/v1/admin/users", headers=_cabeceras(), timeout=10,
                          json={"email": email, "password": contrasena, "email_confirm": True,
                                "user_metadata": {"nombre": nombre}})
    except requests.RequestException:
        raise SupabaseNoResponde()
    if r.status_code in (200, 201):
        return r.json()["id"]
    if r.status_code >= 500:
        raise SupabaseNoResponde()
    try:
        cuerpo = r.json()
    except ValueError:
        cuerpo = {}
    # un 4xx de Supabase es un rechazo con razón (correo con cuenta, contraseña que no cumple su política): no un 500
    if cuerpo.get("error_code") == "email_exists":
        raise CorreoConCuenta()
    raise CuentaRechazada(cuerpo.get("msg") or cuerpo.get("message") or CuentaRechazada.default_detail)


def borrar_cuenta(user_id):
    if not settings.SUPABASE_SERVICE_KEY:
        return False
    r = requests.delete(f"{settings.SUPABASE_URL}/auth/v1/admin/users/{user_id}", headers=_cabeceras(), timeout=10)
    return r.status_code in (200, 204)
