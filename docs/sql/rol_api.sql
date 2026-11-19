-- El rol de la API en producción, con lo que la API usa y nada más.
--
-- NO ESTÁ APLICADO. Lo corre quien administra la base, con el rol postgres, en el SQL Editor de Supabase o con psql
-- por la conexión directa. Se puede correr más de una vez: no falla ni duplica nada.
--
-- Va sin contraseña a propósito. Se genera en el gestor de contraseñas, se pone aparte y no se escribe en ningún archivo:
--   alter role api_el_viejito with password '...';
-- Con ella, DATABASE_URL de la API en Vercel usa el pooler en modo transacción y el usuario rol.ref_del_proyecto:
--   postgresql://api_el_viejito.<ref>:<contraseña>@<el mismo host del pooler que ya usa la API>:6543/postgres
-- Si la contraseña lleva símbolos, van codificados en la URL (por ejemplo, = es %3D).
--
-- Las migraciones de Django no corren con este rol: siguen con postgres, que es el dueño de las tablas.

begin;

-- 1. El rol entra a la base, pero no es superusuario, no crea bases ni roles, no salta RLS y no hereda de otro rol.
--    El pooler abre para este usuario hasta Pool Size conexiones (Database Settings): si el Pool Size pasa de 20, este
--    tope sube con él.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'api_el_viejito') then
    create role api_el_viejito with login nosuperuser nocreatedb nocreaterole noinherit noreplication nobypassrls
      connection limit 20;
  end if;
end
$$;

-- Una consulta colgada no retiene la función de Vercel más de 15 segundos
alter role api_el_viejito set statement_timeout = '15s';

-- 2. El esquema public, sólo para usarlo: el rol no tiene CREATE en él, y PUBLIC tampoco desde Postgres 15.
grant usage on schema public to api_el_viejito;

-- 3. Cada tabla con las operaciones que hace la API. Ninguna otra tabla, ni django_migrations, ni los esquemas de
--    Supabase (auth, storage).
-- Las tablas de Proyecto VII
grant select on public.productos to api_el_viejito;                               -- catálogo y cotización
grant select, insert on public.pedidos to api_el_viejito;                         -- el pedido se crea con su total
grant update (estado, estado_pago) on public.pedidos to api_el_viejito;           -- después sólo cambian sus estados
grant select, insert, update, delete on public.usuarios_admin to api_el_viejito;  -- sesión del panel y sus cuentas
-- Las tablas de la API
grant select, insert, update on public.pagos to api_el_viejito;
grant select, insert, update on public.pagos_eventos to api_el_viejito;           -- update: las repeticiones de un aviso
grant select, insert, update on public.envios to api_el_viejito;
grant select, insert on public.pedidos_historial to api_el_viejito;               -- el historial sólo crece
grant select, update on public.textos_legales to api_el_viejito;                  -- el panel los edita; no crea ni borra
grant select, insert, update on public.notificaciones_pedido to api_el_viejito;
grant select, insert, update on public.invitaciones to api_el_viejito;

-- Los id numéricos de pedidos_historial y notificaciones_pedido. Con columnas identity el permiso sobra; con serial
-- hace falta. Se busca la secuencia de cada una en lugar de suponer su nombre.
do $$
declare
  tabla text;
  secuencia text;
begin
  foreach tabla in array array['pedidos_historial', 'notificaciones_pedido'] loop
    secuencia := pg_get_serial_sequence('public.' || tabla, 'id');
    if secuencia is not null then
      execute format('grant usage on sequence %s to api_el_viejito', secuencia);
    end if;
  end loop;
end
$$;

-- 4. RLS. Las tablas tienen RLS encendido y sin políticas para el navegador; este rol no es dueño de ellas, así que
--    sin una política propia no vería ninguna fila. Cada política aplica sólo a api_el_viejito y deja ver todas las
--    filas: lo que puede hacer con ellas lo limitan los grant de arriba. Para anon y authenticated no cambia nada.
--    En una tabla sin RLS la política no tiene efecto.
do $$
declare
  tabla text;
begin
  foreach tabla in array array['productos', 'pedidos', 'usuarios_admin', 'pagos', 'pagos_eventos', 'envios',
                               'pedidos_historial', 'textos_legales', 'notificaciones_pedido', 'invitaciones'] loop
    execute format('drop policy if exists api_el_viejito_acceso on public.%I', tabla);
    execute format('create policy api_el_viejito_acceso on public.%I as permissive for all to api_el_viejito '
                   'using (true) with check (true)', tabla);
  end loop;
end
$$;

commit;

-- 5. Comprobación, después del commit: lo que el rol puede hacer en cada tabla del esquema public. Deben salir sólo
--    las diez tablas de arriba, con sus operaciones. En pedidos, UPDATE sale en false porque es por columna.
-- select c.relname as tabla,
--        has_table_privilege('api_el_viejito', c.oid, 'select') as lee,
--        has_table_privilege('api_el_viejito', c.oid, 'insert') as crea,
--        has_table_privilege('api_el_viejito', c.oid, 'update') as cambia,
--        has_table_privilege('api_el_viejito', c.oid, 'delete') as borra
-- from pg_class c join pg_namespace n on n.oid = c.relnamespace
-- where n.nspname = 'public' and c.relkind in ('r', 'p', 'v', 'm')
--   and (has_table_privilege('api_el_viejito', c.oid, 'select') or has_table_privilege('api_el_viejito', c.oid, 'insert')
--        or has_table_privilege('api_el_viejito', c.oid, 'update') or has_table_privilege('api_el_viejito', c.oid, 'delete'))
-- order by 1;
--
-- Para deshacerlo, en este orden:
--   drop policy if exists api_el_viejito_acceso on public.<tabla>;   -- en cada una de las diez tablas
--   revoke all on all tables in schema public from api_el_viejito;   -- quita también el update por columna de pedidos
--   revoke all on all sequences in schema public from api_el_viejito;
--   revoke all on schema public from api_el_viejito;
--   drop role api_el_viejito;
