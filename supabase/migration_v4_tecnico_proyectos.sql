-- Migración v4: Asignación de proyectos a técnicos
-- Ejecutar en Supabase > SQL Editor

-- 1. Agregar columna proyecto a la tabla tecnicos
alter table tecnicos add column if not exists proyecto text not null default 'Ambos';
alter table tecnicos add column if not exists proyecto_id bigint references proyectos(id);

comment on column tecnicos.proyecto is 'Proyecto(s) asignados al técnico: Mina San Dimas, Proyectos Durango, Ambos o lista separada por comas';

-- 2. Asegurar que los técnicos actuales tengan valor por defecto
update tecnicos set proyecto = 'Ambos' where proyecto is null;
