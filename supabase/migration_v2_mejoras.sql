-- Migración v2: Soporte para Administradores Dinámicos y Persistencia de Sesión
-- Ejecutar en SQL Editor de Supabase

-- 1. Agregar campo es_admin en tabla tecnicos
alter table tecnicos add column if not exists es_admin boolean not null default false;

-- Asignar administrador inicial (semilla)
update tecnicos
set es_admin = true
where nombre = 'Miguel Abraham Lopez Ortiz';

-- 2. Tabla para persistir el estado conversacional y borradores en curso
create table if not exists sesiones_estado (
  tecnico text primary key references tecnicos(nombre) on update cascade on delete cascade,
  esperando text,
  folio_activo text,
  borrador jsonb not null default '{}'::jsonb,
  actualizado timestamptz not null default now()
);

-- Habilitar RLS en sesiones_estado
alter table sesiones_estado enable row level security;
