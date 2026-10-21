# FieldTI — Reporte de Campo Ágil para Mina y Proyectos Durango (QtekBot)

Bot de Telegram para el registro de actividades en campo en tiempo real, con soporte bivalente para **Operación Minera** (Mina San Dimas / First Majestic) y **Proyectos Locales en Durango** (Qtek Computación / Clientes Corporativos). Los reportes se guardan en **Supabase Postgres**, las fotos de evidencia en **Supabase Storage**, y el admin descarga el reporte en **Excel** con carátulas y resúmenes diferenciados por proyecto o consolidado.

> 📄 **Migración de Base de Datos:** Para actualizar tu base de datos de Supabase existente a la versión multi-proyecto, ejecuta el script [`supabase/migration_v3_proyectos_mina_durango.sql`](supabase/migration_v3_proyectos_mina_durango.sql) en el Editor SQL de Supabase.

## 🚀 Características y Flujo Principal

1. **Flujo de Registro en 8 Pasos**:
   - 🏗️ **Proyecto / Sede**: Selección del proyecto (`⛏️ Mina San Dimas`, `🏙️ Proyectos Durango`, o proyectos adicionales dados de alta).
   - 🎫 **Ticket**: Número de ticket u orden de trabajo (texto libre o `Sin ticket` con generación automática `S/T-XXXX`).
   - 🏢 **Departamento**: Selección dinámica por catálogo de Supabase (ej. `Infraestructura`, `Sistemas`, `Redes`).
   - 📍 **Zona / Ubicación**: Catálogo inteligente **filtrado según el proyecto seleccionado** (ej. Mina: `Nivel 10`, `Nivel 11`, `Planta Beneficio`; Durango: `Oficinas Centrales`, `Taller Qtek`, `Site Corporativo`, `Otra`).
   - 📝 **Actividad**: Descripción de la actividad realizada.
   - 📊 **Estado**: Estado final (`Terminado`, `Pendiente`, `No solucionado`).
   - 📷 **Evidencia**: Carga opcional de fotos con marca de agua automática (ticket, técnico, zona, proyecto, fecha/hora).
   - 📋 **Confirmación Interactiva**: Resumen completo previo al guardado con opciones `✅ Guardar`, `✏️ Editar`, `❌ Cancelar`.
2. **Registro Rápido One-Shot**:
   - `/registro <Proyecto> | <Ticket> | <Depto> | <Zona> | <Actividad> | <Estado>` (soporta tanto formato completo de 6 campos como formato legacy de 4-5 campos asumiendo Mina).
3. **Gestión de Proyectos y Sedes**:
   - `/proyectos`: Listado de proyectos y sedes activas, o `/proyecto <nombre>` para buscar actividades de un proyecto.
   - `/nuevo_proyecto Nombre | Tipo (Mina o Durango) | Cliente`: Alta dinámica de nuevos proyectos (solo admin).
4. **Gestión de Pendientes**: Consulta de reportes pendientes con opción de continuar anexando actualizaciones con marca de tiempo.
5. **Exportación a Excel Especializada**:
   - Carátula institucional automática según proyecto: **First Majestic** para Mina San Dimas, **Qtek Computación** para Durango, o reporte consolidado.
   - Hoja **Resumen**: Desglose con tabla de métricas por Proyecto, Estado, Departamento y Ubicación.
   - Hoja **Reportes**: Columna dedicada `Proyecto`.
   - Hoja **Evidencias**: Vínculos y miniaturas de fotos de evidencias.

---

## 📋 Requisitos Previos y Configuración

### 1. Telegram Bot (vía @BotFather)
1. En Telegram, busca **@BotFather** y envía el comando `/newbot`.
2. Asigna un nombre (ej. `FieldTI Bot`) y un username (ej. `fieldti_qtek_bot`).
3. Guarda el **Token de API** (`TELEGRAM_BOT_TOKEN`).
4. Define un token secreto arbitrario para `TELEGRAM_WEBHOOK_SECRET` (obligatorio: el webhook rechaza peticiones no autorizadas con 403).

### 2. Supabase (base de datos + fotos)
1. Crea un proyecto en [supabase.com](https://supabase.com) (el plan gratuito alcanza para el piloto).
2. **Base de datos:** en **SQL Editor > New query**, pega el contenido de [`supabase/schema.sql`](supabase/schema.sql) (o corre [`supabase/migration_departamentos_zonas.sql`](supabase/migration_departamentos_zonas.sql) si tienes una base previa) y pulsa **Run**. Crea las tablas `tecnicos`, `departamentos`, `zonas` y `reportes`.
3. **Fotos:** en **Storage > New bucket**, crea un bucket llamado `evidencias` y marca **Public bucket**.
4. En **Project Settings > API** copia:
   - **Project URL** → `SUPABASE_URL`
   - **service_role key** (no la `anon`) → `SUPABASE_KEY`

Los datos se pueden ver y corregir a mano en **Table Editor** de Supabase.

---

## 🛠️ Ejecución Local

1. Instala dependencias:
   ```bash
   pip install -r requirements.txt
   ```
2. Crea el archivo `.env` basándote en `.env.example`:
   ```bash
   cp .env.example .env
   ```
3. Llena las variables en `.env`.
4. Inicia el servidor de desarrollo:
   ```bash
   uvicorn app.main:app --reload
   ```
   *Nota: Para probar la interfaz web tipo chat en `http://localhost:8000`, pon `WEBAPP_HABILITADA=true` en tu `.env`. No la actives en Railway: no tiene login y cualquiera podría escribir como cualquier técnico.*
5. Pruebas:
   ```bash
   python -m unittest discover -s tests
   ```

---

## ☁️ Despliegue en Railway

1. Sube tu código a un repositorio de GitHub.
2. Crea un nuevo proyecto en Railway desde el repositorio.
3. Agrega las variables de entorno necesarias en la pestaña **Variables**:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_WEBHOOK_SECRET`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
   - `SUPABASE_BUCKET` (predeterminado: `evidencias`)
   - `ZONA_HORARIA` (predeterminado: `America/Mexico_City`)
   - `REPORTE_ADMIN_SECRET` (obligatorio para usar los endpoints `/api/...` de admin; sin él responden 403)
4. Establece el **Start Command**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
5. Obtén la URL pública que genera Railway (ejemplo: `https://tu-app.up.railway.app`).
6. Configura el Webhook de Telegram ejecutando la siguiente petición desde tu navegador o terminal:
   ```bash
   https://api.telegram.org/bot<TU_TELEGRAM_BOT_TOKEN>/setWebhook?url=https://tu-app.up.railway.app/telegram-webhook&secret_token=<TU_TELEGRAM_WEBHOOK_SECRET>
   ```

---

## 👥 Registro de Técnicos y administración

La lista de técnicos vive en la tabla **`tecnicos`** de Supabase, y el admin del bot (definido en `ADMIN_TECNICOS` en `app/config.py`) la administra desde el propio chat de Telegram:

1. El admin manda `/nuevo_tecnico Nombre Completo` (o pulsa `👤 + Nuevo técnico`). El bot da de alta al técnico y responde con un código de activación de un solo uso.
2. El admin le reenvía ese código al técnico por fuera del bot (WhatsApp, en persona, etc.).
3. El técnico abre un chat con el bot y manda `/start CÓDIGO`. Con eso, su chat de Telegram queda vinculado a su nombre **para siempre** — nadie más puede volver a usar ese código ni hacerse pasar por él, ni siquiera si el bot se reinicia.

El primer técnico (el que venga sembrado en `TECNICOS`/`TECNICOS_INFO` de `app/config.py`, que se da de alta solo la primera vez que corre el bot) no tiene a quién mandarle el código por chat porque todavía nadie le ha escrito al bot. Para ese caso, recupera su código con:

```
GET /api/codigo-activacion?secret=<REPORTE_ADMIN_SECRET>&nombre=<nombre exacto del técnico>
```

y mándale tú mismo `/start CÓDIGO` la primera vez.

Comandos solo para el admin (los demás técnicos reciben "No tienes permiso"):
- `/nuevo_tecnico Nombre Completo` — da de alta un técnico nuevo.
- `/reporte` (o el botón `📊 Exportar Excel`) — manda el Excel de la semana calendario actual (lunes a domingo).
- `/reporte AAAA-MM-DD AAAA-MM-DD` — manda el Excel de ese periodo (ambas fechas inclusive).

Endpoints de admin (todos requieren `REPORTE_ADMIN_SECRET`, como `?secret=` o header `X-Admin-Secret`):
- `GET /api/codigo-activacion?nombre=...` — código de activación pendiente de un técnico.
- `GET /api/exportar-excel?desde=AAAA-MM-DD&hasta=AAAA-MM-DD` — descarga el Excel (sin fechas: semana actual).

Para borrar datos de prueba, usa el **Table Editor** o el **SQL Editor** de Supabase (ej. `truncate reportes restart identity;` reinicia también la numeración en `#001`).
