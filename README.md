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

## 👥 Registro de Técnicos y Asignación de Proyectos

La lista de técnicos vive en la tabla **`tecnicos`** de Supabase, y el admin del bot (definido en `ADMIN_TECNICOS` en `app/config.py`) la administra desde el propio chat de Telegram:

1. **Alta con asignación de proyecto:** El admin manda `/nuevo_tecnico Nombre Completo | Proyecto` (ej. `/nuevo_tecnico Juan Pérez | Mina San Dimas`, `/nuevo_tecnico Carlos Ruiz | Proyectos Durango`, o `/nuevo_tecnico Pedro Gómez | Ambos`).
   - El bot da de alta al técnico con su sede autorizada y genera un código de activación de un solo uso.
2. **Reasignación de proyectos:** El admin puede cambiar la sede asignada en cualquier momento con:
   `/asignar_proyecto <Nombre del Técnico> | <Proyecto>`
3. **Consulta de técnicos:** El admin puede consultar el listado completo de técnicos y sedes con `/tecnicos`.
4. **Activación:** El admin le reenvía el código al técnico. El técnico abre el bot y manda `/start CÓDIGO`. Su chat queda vinculado a su nombre y proyectos autorizados.
5. **Flujo de Reporte inteligente:**
   - Si el técnico está asignado a **un solo proyecto** (ej. solo Mina), al pulsar `➕ Nuevo reporte` se auto-asigna su proyecto y va directo al paso de Ticket.
   - Si está asignado a **varios proyectos** o "Ambos", solo podrá seleccionar entre los proyectos que el admin le autorizó.

Comandos exclusivos para administradores:
- `/nuevo_tecnico Nombre [| Proyecto]` — da de alta un técnico nuevo.
- `/asignar_proyecto Técnico | Proyecto` — cambia el proyecto asignado a un técnico.
- `/tecnicos` — lista los técnicos y sus sedes asignadas.
- `/nuevo_proyecto Nombre | Tipo | Cliente` — registra una nueva sede o proyecto.
- `/nuevo_departamento Nombre` — registra un nuevo departamento.
- `/reporte` (o el botón `📊 Exportar Excel`) — manda el Excel de la semana o periodo/proyecto especificado.
- `/fotos` — descarga las fotos de evidencia en archivo ZIP.

Endpoints de admin (todos requieren `REPORTE_ADMIN_SECRET`, como `?secret=` o header `X-Admin-Secret`):
- `GET /api/codigo-activacion?nombre=...` — código de activación pendiente de un técnico.
- `GET /api/exportar-excel?desde=AAAA-MM-DD&hasta=AAAA-MM-DD` — descarga el Excel (sin fechas: semana actual).

Para borrar datos de prueba, usa el **Table Editor** o el **SQL Editor** de Supabase (ej. `truncate reportes restart identity;` reinicia también la numeración en `#001`).
