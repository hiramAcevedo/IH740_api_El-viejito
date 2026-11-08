# Tequila El Viejito: API de pedidos y pagos

**Proyecto VIII (IH740) | Universidad de Guadalajara, Sistema de Universidad Virtual**

El servicio en Python del sistema web de Tequila El Viejito. Calcula el importe de cada pedido con los precios de la base,
abre la sesión de cobro con la pasarela de pago y recibe sus avisos (webhooks) para dejar el estado del pago en la base.
El sitio en Vue 3 vive en [IH739-IH740_website_El-viejito](https://github.com/aliyatdev/IH739-IH740_website_El-viejito)
y consume esta API.

## Equipo

| Rol | Integrante |
|-----|------------|
| Product Owner (PO) | Marcela López Núñez |
| Scrum Master (SM) | Arturo Daniel Aguilar González |
| Developer (DEV) | Hiram Agustín Acevedo López |

**Asesora:** Úrsula del Pilar González Robles

## Stack

| Capa | Tecnología |
|------|-----------|
| API | Python con Django REST Framework |
| Base de datos | PostgreSQL en Supabase, la misma del sitio |
| Despliegue | Vercel, con el soporte de Python de la plataforma |
| Pasarela de pago | en modo de prueba; la elección se documenta en este repositorio |

## Endpoints

El contrato que fijó la Integradora 2 y que el sitio usa desde `src/lib/api.js`.

| Método | Ruta | Qué hace | Sprint |
|--------|------|----------|--------|
| GET | `/api/productos/` | Los productos activos con su precio | 2 |
| POST | `/api/pedidos/calcular/` | Cotiza el carrito con los precios vigentes de la base, el IVA y el envío | 2 |
| POST | `/api/pedidos/crear/` | Registra el pedido con el importe de aquí, la dirección (`envios`) y la confirmación de edad, que exige | 2 y 4 |
| POST | `/api/pagos/sesion/` | Abre la sesión de Checkout de Stripe y registra el intento en `pagos`; Stripe regresa al sitio | 2 y 4 |
| GET | `/api/pagos/regreso/` | Lo que pregunta la pantalla de regreso: la sesión según Stripe y `estado_pago` según la base | 2 y 4 |
| POST | `/api/webhooks/pasarela/` | Los avisos firmados de Stripe; la clave única de `pagos_eventos` impide aplicar dos veces el mismo | 4 |
| POST | `/api/pedidos/seguimiento/` | El pedido, sólo si correo y folio coinciden | 4 |
| GET | `/api/pedidos/seguimiento/<folio>/` | Lo mismo con la liga firmada del correo de confirmación | 4 |
| GET | `/api/legal/<clave>/` | Aviso de privacidad, términos de venta y leyenda | 4 |
| GET | `/api/admin/resumen/` | Las cuentas del dashboard | 4 |
| GET, PATCH | `/api/admin/pedidos/` | Los pedidos con sus dos estados; el PATCH cambia sólo el logístico | 2 y 4 |
| GET, POST | `/api/admin/envios/` y `.../<id>/guia/` | Los envíos y su guía; con la guía, el pedido pasa a enviado y el aviso queda en la cola | 4 |
| GET | `/api/admin/pagos/` y `.../<id>/eventos/` | Los intentos de cobro y sus avisos | 4 |
| PUT | `/api/admin/legal/<clave>/` | Edita un texto legal | 4 |
| GET, POST, PATCH, DELETE | `/api/admin/usuarios/` | Sólo el superadministrador: cuentas del panel, alta directa, apagado y baja | 4 |
| POST | `/api/admin/invitaciones/` | Sólo el superadministrador: la liga de invitación, que vence y sirve una vez | 4 |
| GET, POST | `/api/invitaciones/<clave>/` | Pública: leer la invitación y crear la cuenta | 4 |

Las rutas de `/api/admin/` piden el token de la sesión de Supabase Auth del panel: la API lo valida con Supabase y
comprueba en `usuarios_admin` que la cuenta siga activa. Crear y borrar cuentas pide la llave de servicio.

## Correr en local

```bash
uv sync
cp .env.example .env    # se llenan las llaves de prueba de Stripe y la cadena del pooler de sesión de Supabase
uv run python manage.py runserver
```

Los modelos de `productos`, `pedidos` y `usuarios_admin` salen de las tablas de Proyecto VII con `inspectdb` y son
no administrados: ninguna migración las crea ni las altera, salvo la columna `estado_pago` de `pedidos`, que agrega una
migración con SQL aditivo. Las tablas de la API (`pagos`, `pagos_eventos`, `envios`, `pedidos_historial`,
`textos_legales`, `notificaciones_pedido` e `invitaciones`) tienen RLS encendido y sin políticas: sólo la API las lee y
las escribe.

Para que los avisos de Stripe lleguen a la API en local, la CLI de Stripe los reenvía y da el secreto de su firma:

```bash
stripe listen --api-key "$STRIPE_SECRET_KEY" --forward-to 127.0.0.1:8000/api/webhooks/pasarela/
```

## Llaves y variables de entorno

Ninguna llave entra al repositorio. En local van en `.env` (ignorado por git; `.env.example` trae los nombres) y en
Vercel, en las variables de cada entorno. Stripe trabaja en su entorno de prueba, con llaves `pk_test_` y `sk_test_`.

Por ahora hay una sola base, la `main` de Supabase, que es la de producción: las ramas de la base piden el plan Pro.
Mientras tanto, los cambios a la base son sólo aditivos y los pedidos de prueba van marcados en `notas`.

## Contribución

Ramas por sprint y pull request hacia `main`:

```bash
git clone https://github.com/hiramAcevedo/IH740_api_El-viejito.git
git switch -c sprint-1-tu-nombre
git commit -m "Sprint 1: descripcion de lo que hiciste"
git push origin sprint-1-tu-nombre
# Pull request hacia main
```

---

*Licenciatura en Desarrollo de Sistemas Web, UDG Virtual*
