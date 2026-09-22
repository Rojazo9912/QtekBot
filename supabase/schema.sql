-- Esquema de QtekBot en Supabase Postgres.
-- Ejecútalo una sola vez en Supabase > SQL Editor > New query > Run.
-- Es idempotente: correrlo de nuevo no borra ni duplica nada.

create table if not exists tecnicos (
  id                bigint generated always as identity primary key,
  nombre            text not null unique,
  cargo             text not null default 'Técnico de Campo',
  imss              text not null default 'N/A',
  -- Chat de Telegram vinculado con /start CÓDIGO (null = aún no activa su cuenta)
  chat_id           bigint unique,
  -- Código de un solo uso; se borra al activarse
  codigo_activacion text unique,
  creado            timestamptz not null default now()
);

create table if not exists reportes (
  -- El número de reporte que ve el técnico (#001, #002…) sale de este id:
  -- único aunque dos técnicos guarden al mismo tiempo.
  id          bigint generated always as identity primary key,
  ticket      text not null,
  tecnico     text not null references tecnicos (nombre) on update cascade,
  ubicacion   text not null,
  actividad   text not null,
  estado      text not null check (estado in ('Terminado', 'Pendiente', 'No solucionado')),
  evidencias  text[] not null default '{}',
  creado      timestamptz not null default now(),
  actualizado timestamptz not null default now()
);

create index if not exists reportes_tecnico_estado_idx on reportes (tecnico, estado);
create index if not exists reportes_creado_idx on reportes (creado);

-- RLS activado y sin políticas: la "anon key" pública no puede leer ni
-- escribir nada. El bot usa la "service_role key", que se salta RLS.
alter table tecnicos enable row level security;
alter table reportes enable row level security;
