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

## Endpoints del diseño

El contrato que fijó la Integradora 2. Cada ruta se documenta aquí conforme queda funcionando.

| Método | Ruta | Qué hace |
|--------|------|----------|
| POST | `/api/pedidos/calcular/` | Cotiza el carrito con los precios vigentes, el IVA y el envío |
| POST | `/api/pedidos/crear/` | Registra el pedido con `estado_pago` pendiente y devuelve su folio |
| POST | `/api/pagos/sesion/` | Abre la sesión de cobro con la pasarela y registra el intento en `pagos` |
| POST | `/api/webhooks/pasarela/` | Recibe los avisos firmados de la pasarela; un aviso repetido no se aplica dos veces (`pagos_eventos`) |

La consulta del pedido por correo y folio, para la vista de seguimiento del sitio, se define en el sprint 3.

## Llaves y variables de entorno

Ninguna llave entra al repositorio. En local van en `.env` (ignorado por git) y en Vercel, en las variables de cada
entorno: local y vista previa usan la base de prueba y las llaves de prueba de la pasarela.

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
