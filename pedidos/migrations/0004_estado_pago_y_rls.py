"""Sprint 4: la columna estado_pago en pedidos, RLS en las tablas nuevas y los textos legales de partida.

Todo es aditivo. estado_pago nace en 'pendiente' para los pedidos que ya existen y el checkout de producción, que no
la conoce, sigue insertando igual. Las tablas nuevas quedan con RLS y sin políticas: el navegador no las lee ni las
escribe por la API REST de Supabase; sólo esta API, por su conexión a Postgres.
"""
from django.db import migrations

ESTADO_PAGO = """
ALTER TABLE public.pedidos ADD COLUMN IF NOT EXISTS estado_pago text NOT NULL DEFAULT 'pendiente';
ALTER TABLE public.pedidos DROP CONSTRAINT IF EXISTS pedidos_estado_pago_valido;
ALTER TABLE public.pedidos ADD CONSTRAINT pedidos_estado_pago_valido
  CHECK (estado_pago IN ('pendiente', 'pagado', 'rechazado', 'reembolsado'));
"""
SIN_ESTADO_PAGO = """
ALTER TABLE public.pedidos DROP CONSTRAINT IF EXISTS pedidos_estado_pago_valido;
ALTER TABLE public.pedidos DROP COLUMN IF EXISTS estado_pago;
"""
TABLAS = ["envios", "pagos_eventos", "pedidos_historial", "textos_legales", "notificaciones_pedido", "invitaciones"]
RLS = "\n".join(f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY;" for t in TABLAS)
SIN_RLS = "\n".join(f"ALTER TABLE public.{t} DISABLE ROW LEVEL SECURITY;" for t in TABLAS)

TEXTOS = {
    "privacidad": ("Aviso de privacidad",
                   "Tequila El Viejito, con domicilio en Tototlán, Jalisco, es responsable de los datos personales que nos "
                   "compartes al comprar en este sitio.\n\nPara procesar y entregar tu pedido usamos tu nombre, correo, teléfono "
                   "y, si eliges envío a domicilio, la dirección de entrega. Los usamos también para avisarte del estado de tu "
                   "pedido. No guardamos los datos de tu tarjeta: el pago lo procesa la pasarela de pago.\n\nSólo compartimos la "
                   "dirección de entrega con la paquetería que lleva tu pedido. Para acceder a tus datos, corregirlos, "
                   "cancelarlos u oponerte a su uso, escríbenos a contacto@elviejito.com."),
    "terminos": ("Términos de venta",
                 "La venta de bebidas alcohólicas en este sitio es sólo para mayores de 18 años. Al pagar confirmas que tienes "
                 "la edad legal para comprar.\n\nLos precios están en pesos mexicanos e incluyen el IVA del 16 %. El importe que "
                 "se cobra es el que calcula el sistema con los precios vigentes al momento de pagar.\n\nPuedes recibir tu "
                 "pedido en tu domicilio, con entrega de 3 a 5 días hábiles, o recogerlo en la tienda de Tototlán, Jalisco. Si "
                 "tu pedido llega dañado o no corresponde a lo que compraste, escríbenos a contacto@elviejito.com con tu folio."),
    "leyenda": ("Leyenda de venta a mayores",
                "Prohibida la venta a menores de edad. El abuso en el consumo de este producto es nocivo para la salud."),
}


def sembrar_textos(apps, schema_editor):
    TextoLegal = apps.get_model("pedidos", "TextoLegal")
    for clave, (titulo, contenido) in TEXTOS.items():
        TextoLegal.objects.get_or_create(clave=clave, defaults={"titulo": titulo, "contenido": contenido})


class Migration(migrations.Migration):

    dependencies = [
        ("pedidos", "0003_sprint4_tablas"),
    ]

    operations = [
        migrations.RunSQL(ESTADO_PAGO, reverse_sql=SIN_ESTADO_PAGO),
        migrations.RunSQL(RLS, reverse_sql=SIN_RLS),
        migrations.RunPython(sembrar_textos, migrations.RunPython.noop),
    ]
