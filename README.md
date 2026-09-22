# FieldTI — Reporte de Campo Ágil para Mina (QtekBot)

Bot de Telegram para el registro de actividades en campo para minería en tiempo real. Los reportes se guardan en **Supabase Postgres**, las fotos de evidencia en **Supabase Storage**, y el admin descarga el reporte del periodo en **Excel** cuando lo necesita.

> 📄 **Documentación oficial del PRD:** Consulta el archivo [`PRD.md`](PRD.md) para revisar las especificaciones de la **Versión 1.1** del piloto.

## 🚀 Características y Flujo Principal (PRD v1.1)

1. **Flujo de Registro en 5 Pasos**:
   - 🎫 **Ticket**: Número de ticket u orden de trabajo (obligatorio, texto libre).
   - 📍 **Ubicación**: Selección por botones (`Nivel 10`, `Nivel 11`, `Nivel 12`, `Otra`).
   - 📝 **Actividad**: Descripción de la actividad realizada.
   - 📊 **Estado**: Estado final (`Terminado`, `Pendiente`, `No solucionado`).
   - 📷 **Evidencia**: Carga opcional de una o varias fotos.
2. **Confirmación Interactiva**: Resumen previo al guardado con opciones `✅ Guardar`, `✏️ Editar`, `❌ Cancelar`.
3. **Gestión de Pendientes**: Consulta de reportes pendientes con opción de continuar anexando actualizaciones con marca de tiempo.
4. **Exportación a Excel** (solo admin): botón `📊 Exportar Excel` o `/reporte AAAA-MM-DD AAAA-MM-DD`. El archivo trae tres hojas:
   - **Resumen**: datos del contrato, periodo y totales por estado, técnico y ubicación.
   - **Reportes**: una fila por reporte, con filtros.
   - **Evidencias**: una fila por foto, con su link.
5. **Generación Automática**: Número de reporte (`#001`, `#002`...), técnico (por sesión de Telegram), fecha y hora en zona horaria local (`America/Mexico_City`).

---

## 📋 Requisitos Previos y Configuración

### 1. Telegram Bot (vía @BotFather)
1. En Telegram, busca **@BotFather** y envía el comando `/newbot`.
2. Asigna un nombre (ej. `FieldTI Bot`) y un username (ej. `fieldti_qtek_bot`).
3. Guarda el **Token de API** (`TELEGRAM_BOT_TOKEN`).
4. Define un token secreto arbitrario para `TELEGRAM_WEBHOOK_SECRET` (muy recomendado: sin él, cualquiera puede mandar updates falsos al webhook).

### 2. Supabase (base de datos + fotos)
1. Crea un proyecto en [supabase.com](https://supabase.com) (el plan gratuito alcanza para el piloto).
2. **Base de datos:** en **SQL Editor > New query**, pega el contenido de [`supabase/schema.sql`](supabase/schema.sql) y pulsa **Run**. Crea las tablas `tecnicos` y `reportes`. Correrlo otra vez no borra nada.
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
