-- Migración v3: Soporte para Proyectos y Sedes (Mina vs Proyectos Durango)
-- Ejecutar en Supabase > SQL Editor

-- 1. Tabla proyectos
create table if not exists proyectos (
  id bigint generated always as identity primary key,
  nombre text not null unique,
  tipo text not null default 'Mina' check (tipo in ('Mina', 'Durango')),
  cliente text not null default '',
  activo boolean not null default true,
  creado timestamptz not null default now()
);

-- Semillas iniciales de proyectos
insert into proyectos (nombre, tipo, cliente)
values 
  ('Mina San Dimas', 'Mina', 'First Majestic'),
  ('Proyectos Durango', 'Durango', 'Qtek Computación')
on conflict (nombre) do nothing;

-- 2. Vincular zonas a proyectos
alter table zonas add column if not exists proyecto_id bigint references proyectos(id);
alter table zonas add column if not exists proyecto text default 'Mina San Dimas';

-- Asignar las zonas existentes a Mina San Dimas
update zonas
set proyecto = 'Mina San Dimas',
    proyecto_id = (select id from proyectos where nombre = 'Mina San Dimas')
where proyecto_id is null;

-- Insertar zonas iniciales para Durango
insert into zonas (nombre, proyecto, proyecto_id)
values
  ('Oficinas Qtek', 'Proyectos Durango', (select id from proyectos where nombre = 'Proyectos Durango')),
  ('Soporte en Sitio', 'Proyectos Durango', (select id from proyectos where nombre = 'Proyectos Durango')),
  ('Infraestructura Redes', 'Proyectos Durango', (select id from proyectos where nombre = 'Proyectos Durango')),
  ('Cliente Corporativo', 'Proyectos Durango', (select id from proyectos where nombre = 'Proyectos Durango'))
on conflict (nombre) do nothing;

-- 3. Vincular reportes a proyectos
alter table reportes add column if not exists proyecto text default 'Mina San Dimas';
alter table reportes add column if not exists proyecto_id bigint references proyectos(id);

update reportes
set proyecto = 'Mina San Dimas',
    proyecto_id = (select id from proyectos where nombre = 'Mina San Dimas')
where proyecto is null;

-- Índices de consulta rápida
create index if not exists reportes_proyecto_idx on reportes (proyecto_id);
create index if not exists reportes_proyecto_nombre_idx on reportes (proyecto);
create index if not exists zonas_proyecto_idx on zonas (proyecto_id);

-- Habilitar RLS en proyectos
alter table proyectos enable row level security;
