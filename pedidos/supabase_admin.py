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


def _cabeceras():
    if not settings.SUPABASE_SERVICE_KEY:
        raise SinLlaveDeServicio()
    return {"apikey": settings.SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"}


def crear_cuenta(email, contrasena, nombre):
    """Crea la cuenta ya confirmada (el proyecto no confirma solo) y devuelve su id."""
    r = requests.post(f"{settings.SUPABASE_URL}/auth/v1/admin/users", headers=_cabeceras(), timeout=10,
                      json={"email": email, "password": contrasena, "email_confirm": True, "user_metadata": {"nombre": nombre}})
    if r.status_code not in (200, 201):
        raise APIException(r.json().get("msg") or r.json().get("message") or "Supabase no creó la cuenta.")
    return r.json()["id"]


def borrar_cuenta(user_id):
    if not settings.SUPABASE_SERVICE_KEY:
        return False
    r = requests.delete(f"{settings.SUPABASE_URL}/auth/v1/admin/users/{user_id}", headers=_cabeceras(), timeout=10)
    return r.status_code in (200, 204)
