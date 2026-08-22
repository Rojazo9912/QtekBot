# FieldTI AI — Piloto Telegram (Telegram → Google Sheets & Drive)

Bot de Telegram que registra actividades de técnicos en tiempo real directamente en un Google Sheet y sube fotos de evidencia a Google Drive.

## 🚀 Características y Funcionalidades
- **Gestión de actividades**: Nueva actividad con ticket o folio interno automático (`FOLIO-0001`, `FOLIO-0002`...).
- **Controles de estado**: Pausar, reanudar y finalizar actividades en curso.
- **Consultas**: Ver actividades pendientes con el comando "Mis actividades".
- **Interpretación NLU (OpenAI)**: Interpreta mensajes en lenguaje natural ("ya terminé", "voy a atender otra falla") e interactúa pidiendo confirmación ante ambigüedades.
- **Evidencias en Google Drive**: Si el técnico envía fotos durante una actividad activa, la foto se sube automáticamente a Google Drive y se guarda el enlace en la columna "Evidencias" del Google Sheet.
- **Teclado con botones de atajo**: Teclado persistente e interactivo en Telegram para agilizar el registro.

---

## 📋 Requisitos Previos y Configuración

### 1. Telegram Bot (vía @BotFather)
1. En Telegram, busca **@BotFather** y envía el comando `/newbot`.
2. Asigna un nombre (ej. `FieldTI Bot`) y un username (ej. `fieldti_qtek_bot`).
3. Guarda el **Token de API** (`TELEGRAM_BOT_TOKEN`).
4. (Opcional) Define un token secreto arbitrario para `TELEGRAM_WEBHOOK_SECRET`.

### 2. Google Sheets & Drive API
1. En [Google Cloud Console](https://console.cloud.google.com), crea un proyecto y habilita la **Google Sheets API** y la **Google Drive API**.
2. Crea una **Cuenta de Servicio** (Service Account) y descarga la llave en formato JSON (`credentials.json`).
3. Crea un **Google Sheet** nuevo y una **Carpeta en Google Drive** para evidencias.
4. **Comparte** tanto el Google Sheet como la carpeta de Google Drive con el correo de la cuenta de servicio (campo `client_email` dentro de tu JSON) dándole permisos de **Editor**.
5. Obtén los IDs:
   - `GOOGLE_SHEET_ID`: De la URL del Sheet (la parte entre `/d/` y `/edit`).
   - `DRIVE_FOLDER_ID`: De la URL de la carpeta de Drive (la parte después de `/folders/`).

### 3. OpenAI API
Obtén tu API key en [platform.openai.com](https://platform.openai.com) (`OPENAI_API_KEY`).

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
3. Llena las variables en `.env` (coloca `credentials.json` en la raíz de tu proyecto o configura `GOOGLE_CREDENTIALS_PATH`).
4. Inicia el servidor de desarrollo:
   ```bash
   uvicorn app.main:app --reload
   ```
   *Nota: Puedes probar la interfaz web tipo chat ingresando a `http://localhost:8000` en tu navegador.*

---

## ☁️ Despliegue en Railway

1. Sube tu código a un repositorio de GitHub.
2. Crea un nuevo proyecto en Railway desde el repositorio.
3. Agrega las variables de entorno necesarias en la pestaña **Variables**:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_WEBHOOK_SECRET`
   - `OPENAI_API_KEY`
   - `GOOGLE_SHEET_ID`
   - `GOOGLE_CREDENTIALS_JSON` (copia y pega el contenido completo de tu `credentials.json`)
   - `DRIVE_FOLDER_ID`
   - `ZONA_HORARIA` (predeterminado: `America/Mexico_City`)
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

La lista de técnicos ya no vive en el código: vive en la pestaña **"Técnicos"** del Google Sheet, y el admin del bot (definido en `ADMIN_TECNICOS` en `app/config.py`) la administra desde el propio chat de Telegram:

1. El admin manda `/nuevo_tecnico Nombre Completo`. El bot da de alta al técnico y responde con un código de activación de un solo uso.
2. El admin le reenvía ese código al técnico por fuera del bot (WhatsApp, en persona, etc.).
3. El técnico abre un chat con el bot y manda `/start CÓDIGO`. Con eso, su chat de Telegram queda vinculado a su nombre **para siempre** — nadie más puede volver a usar ese código ni hacerse pasar por él, ni siquiera si el bot se reinicia.

El primer técnico (el que venga sembrado en `TECNICOS`/`TECNICOS_INFO` de `app/config.py`, usado solo para crear la pestaña "Técnicos" la primera vez) no tiene a quién mandarle el código por chat porque todavía nadie le ha escrito al bot. Para ese caso, recupera su código con:

```
GET /api/codigo-activacion?secret=<REPORTE_ADMIN_SECRET>&nombre=<nombre exacto del técnico>
```

y mándale tú mismo `/start CÓDIGO` la primera vez.

Comandos solo para el admin (los demás técnicos reciben "No tienes permiso"):
- `/nuevo_tecnico Nombre Completo` — da de alta un técnico nuevo.
- `/reporte` o `/reporte AAAA-MM-DD AAAA-MM-DD` — fija el periodo del reporte contractual en la hoja "Reporte PDF" (semana calendario actual si no se especifican fechas).

