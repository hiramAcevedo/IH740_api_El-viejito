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

El contrato que fijó la Integradora 2. Cada ruta se documenta aquí conforme queda funcionando.

| Método | Ruta | Qué hace | Sprint |
|--------|------|----------|--------|
| GET | `/api/productos/` | Los productos activos con su precio | 2 |
| POST | `/api/pedidos/calcular/` | Cotiza el carrito con los precios vigentes de la base, el IVA y el envío | 2 |
| POST | `/api/pedidos/crear/` | Registra el pedido como pendiente con el importe calculado aquí y devuelve su folio | 2 |
| POST | `/api/pagos/sesion/` | Abre la sesión de Checkout de Stripe con las líneas del pedido y registra el intento en `pagos` | 2 |
| GET | `/api/pagos/regreso/` | A donde vuelve el comprador desde Stripe: el estado de su sesión | 2 |
| GET | `/api/admin/pedidos/` | Los pedidos para el panel; sin la sesión de Supabase de un administrador activo responde 401 | 2 |
| POST | `/api/webhooks/pasarela/` | Recibe los avisos firmados de Stripe; un aviso repetido no se aplica dos veces (`pagos_eventos`) | 3 |

La consulta del pedido por correo y folio, para la vista de seguimiento del sitio, se define en el sprint 3.

## Correr en local

```bash
uv sync
cp .env.example .env    # se llenan las llaves de prueba de Stripe y la cadena del pooler de sesión de Supabase
uv run python manage.py runserver
```

Los modelos de `productos`, `pedidos` y `usuarios_admin` salen de las tablas de Proyecto VII con `inspectdb` y son
no administrados: ninguna migración las crea ni las altera. La única tabla que crea esta API es `pagos`, con RLS
encendido y sin políticas, de modo que sólo la API la lee y la escribe.

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
