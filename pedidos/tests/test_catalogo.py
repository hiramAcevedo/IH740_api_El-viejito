"""El catálogo público y la cotización del carrito: GET /api/productos/ y POST /api/pedidos/calcular/."""
import uuid
from decimal import Decimal

from django.test import TestCase

from .comun import nuevo_producto


class CatalogoTests(TestCase):
    def test_fuera_de_debug_un_navegador_recibe_json(self):
        """Sin DEBUG, la API sólo habla JSON: un navegador que pide HTML recibe JSON, no la API navegable de DRF."""
        r = self.client.get("/api/productos/", headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/json")

    def test_catalogo_publico_solo_activos_con_precio(self):
        """El catálogo lista sólo los productos activos, con su precio, del más barato al más caro."""
        reposado = nuevo_producto("Tequila Reposado 750 ml", "429.00", tipo="Reposado")
        blanco = nuevo_producto("Tequila Blanco 750 ml", "349.99")
        nuevo_producto("Tequila Añejo 750 ml", "559.00", activo=False, tipo="Añejo")

        r = self.client.get("/api/productos/")

        self.assertEqual(r.status_code, 200)
        productos = r.json()
        self.assertEqual([p["nombre"] for p in productos], [blanco.nombre, reposado.nombre])
        self.assertEqual([Decimal(str(p["precio"])) for p in productos], [Decimal("349.99"), Decimal("429.00")])
        self.assertEqual(set(productos[0]), {"id", "nombre", "descripcion", "tipo", "precio", "imagen_url", "activo"})
        self.assertTrue(all(p["activo"] for p in productos))


class CotizacionTests(TestCase):
    URL = "/api/pedidos/calcular/"

    def setUp(self):
        self.blanco = nuevo_producto("Tequila Blanco 750 ml", "349.99")
        self.reposado = nuevo_producto("Tequila Reposado 750 ml", "429.00", tipo="Reposado")

    def cotizar(self, items, **extra):
        return self.client.post(self.URL, {"items": items, **extra}, content_type="application/json")

    def test_cotizacion_con_precios_de_la_base_iva_y_envio_gratis(self):
        """La cotización usa los precios de la base aunque el sitio mande otros: IVA del 16 % al centavo y envío en cero."""
        r = self.cotizar([{"producto_id": str(self.blanco.id), "cantidad": 2, "precio": "1.00"},
                          {"producto_id": str(self.reposado.id), "cantidad": 1, "precio": "1.00"}],
                         metodo_entrega="envio", total="3.00")

        self.assertEqual(r.status_code, 200)
        d = r.json()
        # 2 x 349.99 + 429.00 = 1,128.98; IVA 180.6368 se redondea a 180.64; total 1,309.62
        self.assertEqual([(l["precio"], l["cantidad"], l["subtotal"]) for l in d["lineas"]],
                         [("349.99", 2, "699.98"), ("429.00", 1, "429.00")])
        self.assertEqual((d["subtotal"], d["iva"], d["envio"], d["total"], d["moneda"]),
                         ("1128.98", "180.64", "0.00", "1309.62", "mxn"))
        recoger = self.cotizar([{"producto_id": str(self.blanco.id), "cantidad": 1}], metodo_entrega="recoger").json()
        self.assertEqual((recoger["subtotal"], recoger["iva"], recoger["envio"], recoger["total"]),
                         ("349.99", "56.00", "0.00", "405.99"))

    def test_cotizacion_rechaza_producto_inexistente_o_inactivo(self):
        """Un producto que no existe o que está apagado no se cotiza: 400 con el id que falta."""
        inactivo = nuevo_producto("Tequila Añejo 750 ml", "559.00", activo=False, tipo="Añejo")
        for caso, producto_id in [("inexistente", str(uuid.uuid4())), ("inactivo", str(inactivo.id))]:
            with self.subTest(caso):
                r = self.cotizar([{"producto_id": str(self.blanco.id), "cantidad": 1},
                                  {"producto_id": producto_id, "cantidad": 1}])
                self.assertEqual(r.status_code, 400)
                self.assertIn(producto_id, str(r.json()["items"]))

    def test_cotizacion_rechaza_cantidades_y_carritos_invalidos(self):
        """Cantidad fuera de 1 a 24, con texto, decimal o ausente, id que no es UUID, carrito vacío o entrega desconocida: 400."""
        pid = str(self.blanco.id)
        casos = {
            "cantidad cero": {"items": [{"producto_id": pid, "cantidad": 0}]},
            "cantidad negativa": {"items": [{"producto_id": pid, "cantidad": -3}]},
            "más de 24 piezas": {"items": [{"producto_id": pid, "cantidad": 25}]},
            "cantidad con texto": {"items": [{"producto_id": pid, "cantidad": "dos"}]},
            "cantidad decimal": {"items": [{"producto_id": pid, "cantidad": 1.5}]},
            "sin cantidad": {"items": [{"producto_id": pid}]},
            "id que no es UUID": {"items": [{"producto_id": "1; DROP TABLE productos", "cantidad": 1}]},
            "carrito vacío": {"items": []},
            "sin carrito": {},
            "entrega desconocida": {"items": [{"producto_id": pid, "cantidad": 1}], "metodo_entrega": "dron"},
        }
        for caso, datos in casos.items():
            with self.subTest(caso):
                r = self.client.post(self.URL, datos, content_type="application/json")
                self.assertEqual(r.status_code, 400)
        # el límite superior sí se acepta
        self.assertEqual(self.cotizar([{"producto_id": pid, "cantidad": 24}]).status_code, 200)
