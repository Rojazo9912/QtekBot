# Cambios implementados en QtekBot

## Versión 2.1 — Exportación Interactiva y Multisede en Excel

1. **Asistente Interactivo de Exportación en Telegram**:
   - Al pulsar el botón `📊 Exportar Excel` (o escribir `/reporte` sin argumentos), el bot guía al administrador paso a paso mediante botones en lugar de descargar inmediatamente la semana actual a ciegas.
   - **Paso 1: Selección de Proyecto**: Elige un proyecto en específico (`Mina San Dimas`, `Proyectos Durango`) o `🌐 Todos (Consolidado)`.
   - **Paso 2: Selección de Fechas**: Botones rápidos para `📅 Esta semana`, `🗓️ Este mes`, `📆 Hoy`, `⏮️ Semana pasada` o `✍️ Personalizado` (ingresando rango `AAAA-MM-DD AAAA-MM-DD`).
   - Opción para cancelar en cualquier momento con `❌ Cancelar`.
2. **Separación y Organización en el Archivo Excel (.xlsx)**:
   - **Orden Cronológico**: Todas las hojas ahora ordenan los reportes cronológicamente por `Fecha` y `Hora`.
   - **Pestañas por Proyecto**: Cuando el reporte es consolidado (múltiples proyectos), además de la hoja `Resumen` y `Reportes`, el Excel crea automáticamente una pestaña exclusiva para cada Proyecto (ej. pestaña `Mina San Dimas`, pestaña `Proyectos Durango`).
   - Si se selecciona un solo proyecto, el archivo se filtra y titula exclusivamente con dicho proyecto.
3. **Retrocompatibilidad Completa**:
   - Se mantiene el comando directo por texto `/reporte [desde] [hasta] [proyecto]` para ejecuciones rápidas y scripts externos.

## Versión 2.0 — Mejoras de Producción y Operación en Mina

1. **Edición Granular en Confirmación**: Al pulsar `✏️ Editar`, el bot ya no borra el reporte; permite seleccionar exactamente qué campo corregir (`Ticket`, `Departamento`, `Zona`, `Actividad`, `Estado`, `Fotos`, `Reiniciar todo` o `Volver`).
2. **Modo One-Shot (Registro Rápido en 1 solo mensaje)**: Comando `/registro <Ticket> | <Departamento> | <Zona> | <Actividad> | <Estado>`. Ideal para zonas con cobertura intermitente en interior de mina.
3. **Marca de Agua Automática en Evidencias**: Las fotos subidas a Telegram se estampan con franja inferior que detalla: `Ticket | Zona | Técnico | Fecha y Hora local`.
4. **Búsqueda y Consulta**:
   - `/buscar <ticket o folio>`: Muestra el estado, datos completos y enlaces de fotos.
   - `/zona <nombre>`: Muestra reportes recientes registrados en dicha ubicación.
5. **Exportación de Evidencias en ZIP**:
   - Comando `/fotos [desde] [hasta]` para administradores en Telegram.
   - Endpoint protegido `GET /api/exportar-fotos?desde=...&hasta=...`.
6. **Administradores Dinámicos**: Soporte para la columna `es_admin` en la tabla `tecnicos` de Supabase (con fallback retrocompatible a `config.py`).
7. **Persistencia de Sesión Conversacional**: Las sesiones y borradores activos se respaldan en Supabase (tabla `sesiones_estado`), sobreviviendo a reinicios o despliegues del contenedor.
8. **Procesamiento Asíncrono No Bloqueante**: Desacople de operaciones pesadas I/O (descargas, marcas de agua, compresión) en `asyncio.to_thread` dentro de FastAPI.

---

## Versión 1.1 — Departamentos y Zonas Dinámicas

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