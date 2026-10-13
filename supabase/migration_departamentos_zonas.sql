-- Catálogos dinámicos de QtekBot: departamentos y zonas.
create table if not exists departamentos (
  id bigint generated always as identity primary key,
  nombre text not null unique,
  activo boolean not null default true,
  creado timestamptz not null default now()
);

create table if not exists zonas (
  id bigint generated always as identity primary key,
  nombre text not null unique,
  activo boolean not null default true,
  creado timestamptz not null default now()
);

insert into departamentos (nombre)
values ('Infraestructura')
on conflict (nombre) do nothing;

insert into zonas (nombre)
values ('Nivel 10'), ('Nivel 11'), ('Nivel 12')
on conflict (nombre) do nothing;

alter table reportes add column if not exists departamento text default 'Infraestructura';
alter table reportes add column if not exists departamento_id bigint references departamentos(id);
alter table reportes add column if not exists zona_id bigint references zonas(id);
alter table reportes add column if not exists creado_por text;

update reportes
set departamento = 'Infraestructura'
where departamento is null;

update reportes
set departamento_id = (select id from departamentos where nombre = 'Infraestructura')
where departamento_id is null;

update reportes
set zona_id = (select id from zonas where zonas.nombre = reportes.ubicacion)
where zona_id is null;

update reportes set creado_por = tecnico where creado_por is null;

create index if not exists reportes_departamento_idx on reportes (departamento_id);
create index if not exists reportes_zona_idx on reportes (zona_id);

alter table departamentos enable row level security;
alter table zonas enable row level security;