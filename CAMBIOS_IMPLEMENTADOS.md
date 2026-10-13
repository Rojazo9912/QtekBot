# Cambios implementados en QtekBot

## Resumen

Se actualizó QtekBot para trabajar con departamentos y zonas dinámicas, además de reforzar la seguridad de evidencias y endpoints administrativos.

## Departamentos

- Se agregó la tabla `departamentos` en Supabase.
- Se creó automáticamente el departamento inicial `Infraestructura`.
- Los departamentos activos se consultan desde Supabase.
- El administrador puede crear departamentos desde Telegram:

```text
/nuevo_departamento Mantenimiento
```

- El administrador puede consultar los departamentos disponibles:

```text
/departamentos
```

- No se permiten departamentos duplicados.

## Zonas

- Se agregó la tabla `zonas` en Supabase.
- Se cargaron inicialmente:
  - Nivel 10
  - Nivel 11
  - Nivel 12
- Cuando el técnico selecciona `Otra`, la nueva zona se guarda automáticamente.
- Las zonas quedan disponibles para futuros reportes.
- No se permiten zonas vacías o duplicadas.

## Flujo actualizado del reporte

El flujo ahora es:

1. Ticket.
2. Departamento.
3. Zona.
4. Actividad.
5. Estado.
6. Evidencias.
7. Confirmación.

El departamento se guarda junto con cada reporte.

## Migración de base de datos

Archivo:

```text
supabase/migration_departamentos_zonas.sql
```

La migración crea:

- `departamentos`
- `zonas`
- `reportes.departamento_id`
- `reportes.zona_id`
- `reportes.creado_por`

También inserta los catálogos iniciales y relaciona los reportes existentes con `Infraestructura` cuando corresponde.

## Seguridad implementada

- El webhook de Telegram rechaza peticiones si no existe o no coincide `TELEGRAM_WEBHOOK_SECRET`.
- Los endpoints administrativos usan `X-Admin-Secret`.
- Las evidencias tienen límite de 10 MB.
- Solo se aceptan imágenes.
- Se valida que el archivo sea realmente una imagen.
- Storage rechaza archivos vacíos, demasiado grandes o con MIME no permitido.
- Los mensajes web tienen límites de longitud.

## Archivos modificados

- `app/bot_logic.py`: flujo de departamento y zona.
- `app/db.py`: catálogos dinámicos y persistencia del departamento.
- `app/main.py`: comandos administrativos de Telegram y validaciones.
- `app/storage.py`: validación de evidencias.
- `supabase/migration_departamentos_zonas.sql`: migración de base de datos.

## Comandos administrativos

```text
/nuevo_tecnico Nombre Completo
/nuevo_departamento Nombre
/departamentos
/reporte
/reporte AAAA-MM-DD AAAA-MM-DD
```

## Verificación

Se verificó la compilación de los módulos Python modificados. Las pruebas antiguas que asumen un flujo sin departamento deben actualizarse para contemplar el nuevo paso.