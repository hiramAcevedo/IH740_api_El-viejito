"""El seguimiento sin cuenta: POST /api/pedidos/seguimiento/ (correo y folio) y GET /api/pedidos/seguimiento/<folio>/
(la liga firmada del correo de confirmación)."""
from urllib.parse import quote

from django.test import Client, TestCase

from pedidos.models import HistorialPedido, Pedidos

from .comun import SinErroresDelServidor, firma_de_seguimiento, nuevo_pedido, nuevo_producto

NO_COINCIDE = {"detail": "No encontramos un pedido con esos datos. Revisa el correo y el folio."}


class SeguimientoTests(SinErroresDelServidor, TestCase):
    URL = "/api/pedidos/seguimiento/"

    def setUp(self):
        self.blanco = nuevo_producto("Tequila Blanco 750 ml", "349.99")
        self.pedido = nuevo_pedido([(self.blanco, 2)], estado_pago="pagado", correo="Maria.Lopez@Ejemplo.com")
        HistorialPedido.objects.create(pedido=self.pedido, estado="pagado")
        self.otro = nuevo_pedido([(self.blanco, 1)], correo="otra@ejemplo.com")
        # para las entradas raras: una excepción en la vista llega como respuesta 500, no como error de la prueba
        self.cliente_crudo = Client(raise_request_exception=False)

    def consultar(self, datos, cliente=None):
        return (cliente or self.client).post(self.URL, datos, content_type="application/json")

    def liga(self, folio, **parametros):
        return f"{self.URL}{quote(folio, safe='')}/", parametros

    def test_correo_y_folio_correctos_devuelven_el_detalle(self):
        """Correo y folio correctos dan el detalle, sin datos personales, aunque cambien mayúsculas y minúsculas."""
        r = self.consultar({"correo": "maria.lopez@ejemplo.com", "folio": self.pedido.folio.lower()})

        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(set(d), {"folio", "creado", "estado", "estado_pago", "metodo_entrega", "lineas", "subtotal",
                                  "iva", "envio", "total", "historial", "envio_info"})
        self.assertEqual((d["folio"], d["estado"], d["estado_pago"], d["metodo_entrega"]),
                         (self.pedido.folio, "pendiente", "pagado", "envio"))
        self.assertEqual((d["subtotal"], d["iva"], d["envio"], d["total"]), ("699.98", "112.00", "0.00", "811.98"))
        self.assertEqual([(l["nombre"], l["cantidad"]) for l in d["lineas"]], [("Tequila Blanco 750 ml", 2)])
        self.assertEqual([h["estado"] for h in d["historial"]], ["pagado"])
        self.assertIsNone(d["envio_info"])  # todavía sin guía

    def test_correo_equivocado_o_folio_inexistente_dan_el_mismo_404(self):
        """Correo de otro pedido o folio que no existe: el mismo 404, sin decir cuál de los dos falló."""
        folio_libre = next(f for f in ("00000000", "FFFFFFFF") if f not in (self.pedido.folio, self.otro.folio))
        casos = {
            "correo de otro pedido": {"correo": "otra@ejemplo.com", "folio": self.pedido.folio},
            "folio inexistente": {"correo": "maria.lopez@ejemplo.com", "folio": folio_libre},
        }
        respuestas = {}
        for caso, datos in casos.items():
            with self.subTest(caso):
                respuestas[caso] = self.consultar(datos)
                self.assertEqual(respuestas[caso].status_code, 404)
                self.assertEqual(respuestas[caso].json(), NO_COINCIDE)
        self.assertEqual(*(r.content for r in respuestas.values()))

    def test_entradas_raras_dan_404_o_400_nunca_500(self):
        """Comillas, SQL, comodines de LIKE, textos enormes, tipos cambiados y JSON roto: 404 o 400, nunca 500."""
        folio = self.pedido.folio
        cuerpos = {
            "folio con comillas (inyección SQL)": {"correo": "maria.lopez@ejemplo.com", "folio": "' OR '1'='1"},
            "folio de comodines %": {"correo": "maria.lopez@ejemplo.com", "folio": "%%%%%%%%"},
            "folio de comodines _": {"correo": "maria.lopez@ejemplo.com", "folio": "________"},
            "correo con SQL": {"correo": "x@ejemplo.com'; DROP TABLE pedidos; --", "folio": folio},
            "correo con comillas": {"correo": "\"' OR 1=1 --", "folio": folio},
            "folio de 10,000 caracteres": {"correo": "maria.lopez@ejemplo.com", "folio": "A" * 10000},
            "valores nulos": {"correo": None, "folio": None},
            "tipos cambiados": {"correo": ["maria.lopez@ejemplo.com"], "folio": {"$ne": ""}},
            "cuerpo que es lista": ["maria.lopez@ejemplo.com", folio],
            "cuerpo vacío": {},
        }
        for caso, cuerpo in cuerpos.items():
            with self.subTest(caso):
                r = self.consultar(cuerpo, self.cliente_crudo)
                self.assertSin500(r, caso)
                self.assertEqual(r.status_code, 404)
        with self.subTest("JSON mal formado"):
            r = self.cliente_crudo.post(self.URL, '{"correo": "maria', content_type="application/json")
            self.assertSin500(r, "JSON mal formado")
            self.assertEqual(r.status_code, 400)
        ligas = {
            "liga con folio de comillas": self.liga("' OR '1'='1", firma="abc"),
            "liga con folio comodín %": self.liga("%", firma="abc"),
            "liga sin firma": self.liga(folio),
            "liga con firma de SQL": self.liga(folio, firma="' OR 1=1 --"),
        }
        for caso, (ruta, parametros) in ligas.items():
            with self.subTest(caso):
                r = self.cliente_crudo.get(ruta, parametros)
                self.assertSin500(r, caso)
                self.assertEqual(r.status_code, 404)
        self.assertEqual(Pedidos.objects.count(), 2)

    def test_liga_firmada_abre_el_pedido_y_rechaza_firmas_ajenas(self):
        """La liga con la firma del folio y el correo abre el pedido; la firma de otro pedido o recortada da 404."""
        firma = firma_de_seguimiento(self.pedido.folio, "Maria.Lopez@Ejemplo.com")

        r = self.client.get(*self.liga(self.pedido.folio, firma=firma))

        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["folio"], r.json()["estado_pago"]), (self.pedido.folio, "pagado"))
        casos = {
            "firma de otro pedido": self.liga(self.pedido.folio, firma=firma_de_seguimiento(self.otro.folio,
                                                                                            "otra@ejemplo.com")),
            "firma recortada": self.liga(self.pedido.folio, firma=firma[:-1]),
            "folio de otro pedido con esta firma": self.liga(self.otro.folio, firma=firma),
        }
        for caso, (ruta, parametros) in casos.items():
            with self.subTest(caso):
                r = self.client.get(ruta, parametros)
                self.assertEqual(r.status_code, 404)
                self.assertEqual(r.json(), {"detail": "La liga no es válida."})

    def test_liga_firmada_con_firma_no_ascii_da_404_y_no_500(self):
        """Una firma con caracteres fuera de ASCII en la liga es una firma inválida más: 404, no 500."""
        r = self.cliente_crudo.get(*self.liga(self.pedido.folio, firma="ñ" * 24))

        self.assertSin500(r, "firma no ASCII")
        self.assertEqual(r.status_code, 404)
