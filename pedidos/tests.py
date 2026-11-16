import json
import uuid
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from .models import Productos


class BackendUnitTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        ahora = timezone.now()
        # Creamos productos de prueba en memoria con los precios reales del catálogo
        self.reposado = Productos.objects.create(
            id=uuid.uuid4(),
            nombre="Reposado Suave",
            tipo="reposado",
            precio=Decimal("450.00"),
            activo=True,
            created_at=ahora,
        )
        self.anejo = Productos.objects.create(
            id=uuid.uuid4(),
            nombre="Añejo Premium",
            tipo="añejo",
            precio=Decimal("680.00"),
            activo=True,
            created_at=ahora,
        )
        self.inactivo = Productos.objects.create(
            id=uuid.uuid4(),
            nombre="Edición Agotada",
            tipo="blanco",
            precio=Decimal("320.00"),
            activo=False,
            created_at=ahora,
        )

    def test_01_catalogo_publico_solo_activos(self):
        """GET /api/productos/ debe devolver sólo los productos activos sin requerir sesión[cite: 3]."""
        res = self.client.get("/api/productos/")
        self.assertEqual(res.status_code, 200)
        nombres = [p["nombre"] for p in res.data]
        self.assertIn("Reposado Suave", nombres)
        self.assertNotIn("Edición Agotada", nombres)

    def test_02_calcular_cotizacion_con_iva_servidor(self):
        """POST /api/pedidos/calcular/ calcula subtotal, 16% IVA y envío gratis desde BD[cite: 1, 3]."""
        payload = {
            "items": [
                {"producto_id": str(self.reposado.id), "cantidad": 2},  # 900.00
                {"producto_id": str(self.anejo.id), "cantidad": 1},     # 680.00
            ]
        }
        res = self.client.post("/api/pedidos/calcular/", payload, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Decimal(str(res.data["subtotal"])), Decimal("1580.00"))
        self.assertEqual(Decimal(str(res.data["iva"])), Decimal("252.80"))
        self.assertEqual(Decimal(str(res.data["total"])), Decimal("1832.80"))

    def test_03_rechaza_producto_inactivo_con_400(self):
        """POST /api/pedidos/calcular/ rechaza productos inactivos con HTTP 400[cite: 3]."""
        payload = {"items": [{"producto_id": str(self.inactivo.id), "cantidad": 1}]}
        res = self.client.post("/api/pedidos/calcular/", payload, format="json")
        self.assertEqual(res.status_code, 400)

    def test_04_crear_pedido_exige_mayoria_edad(self):
        """POST /api/pedidos/crear/ rechaza con 400 si falta confirma_mayor_de_edad[cite: 1]."""
        payload = {
            "cliente_nombre": "Daniel Prueba",
            "cliente_email": "daniel@example.com",
            "telefono": "3312345678",
            "metodo_entrega": "recoger",
            "confirma_mayor_de_edad": False,
            "items": [{"producto_id": str(self.reposado.id), "cantidad": 1}],
        }
        res = self.client.post("/api/pedidos/crear/", payload, format="json")
        self.assertEqual(res.status_code, 400)

    def test_05_crear_pedido_valido_genera_folio_8_chars(self):
        """POST /api/pedidos/crear/ guarda pedido pendiente y devuelve folio de 8 caracteres[cite: 1, 3]."""
        payload = {
            "cliente_nombre": "Daniel Prueba",
            "cliente_email": "daniel@example.com",
            "telefono": "3312345678",
            "metodo_entrega": "recoger",
            "confirma_mayor_de_edad": True,
            "items": [{"producto_id": str(self.reposado.id), "cantidad": 2}],
        }
        res = self.client.post("/api/pedidos/crear/", payload, format="json")
        self.assertIn(res.status_code, (200, 201))
        self.assertEqual(len(res.data["folio"]), 8)
        self.assertEqual(Decimal(str(res.data["total"])), Decimal("1044.00"))

    def test_06_ruta_admin_rechaza_sin_token_401(self):
        """GET /api/admin/resumen/ rechaza peticiones sin sesión con HTTP 401[cite: 1]."""
        res = self.client.get("/api/admin/resumen/")
        self.assertEqual(res.status_code, 401)

    def test_07_webhook_rechaza_firma_invalida_400(self):
        """POST /api/webhooks/pasarela/ rechaza firmas Stripe falsas con HTTP 400[cite: 1]."""
        res = self.client.post(
            "/api/webhooks/pasarela/",
            data=json.dumps({"id": "evt_falso"}),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=firma_falsa",
        )
        self.assertEqual(res.status_code, 400)
