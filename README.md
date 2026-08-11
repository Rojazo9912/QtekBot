# FieldTI AI — Piloto mínimo (WhatsApp → Google Sheets)

Bot de WhatsApp que registra actividades de técnicos directamente en un Google Sheet,
para un piloto con 2-3 técnicos (PRD, sección 23).

## Qué SÍ hace
- Nueva actividad, con ticket o folio interno automático (`FOLIO-0001`, `FOLIO-0002`...).
- Pausar / reanudar / finalizar.
- "Mis actividades" para ver pendientes.
- Interpreta lenguaje natural ("ya terminé", "voy a atender otra falla") con OpenAI,
  y pide confirmación cuando la IA no está segura — regla de negocio del PRD sección 15.

## Qué NO hace (a propósito, para no venderte más de lo que es)
- **Evidencias (fotos/audios):** WhatsApp las manda como `media_id`; falta el código para
  descargarlas de Meta y subirlas a algún storage (Google Drive, S3, etc.). Es la pieza
  obvia a agregar después.
- **Dashboard:** para el piloto, el Google Sheet mismo es el dashboard. Un dashboard de
  verdad (filtros, indicadores) es la Fase 2 del PRD.
- **Persistencia del estado de conversación:** ver la advertencia en `app/state.py` —
  vive en memoria del proceso. Si Railway reinicia el servicio a medio piloto, los
  técnicos con una conversación a medias (p. ej. "ya te pregunté el ticket, esperando
  el número") tienen que volver a empezar esa actividad. Las actividades YA guardadas
  en Sheets no se pierden. Para producción esto debe ser Supabase/Redis, como ya dice
  el PRD original — no es opcional ahí.
- **Multi-actividad simultánea real:** el piloto asume una actividad activa a la vez por
  técnico (igual que el ejemplo de la sección 6 del PRD: pausas antes de iniciar otra).

## Tres formas de usar el piloto

Este proyecto tiene TRES canales de entrada que comparten exactamente la
misma lógica de negocio (`app/bot_logic.py`) — cambia solo cómo el técnico
manda el mensaje:

### A) Telegram (recomendada — chat real, configuración simple)
Bot de verdad dentro de Telegram: notificaciones push, historial, botones de
atajos. A diferencia de WhatsApp, no hay verificación de negocio ni modo
desarrollo/producción — el token de @BotFather ya te deja mandar y recibir
mensajes de inmediato.

**1. Crea el bot:**
1. En Telegram, busca **@BotFather** y mándale `/newbot`.
2. Dale un nombre (ej. "FieldTI Actividades") y un username que termine en
   `bot` (ej. `fieldti_qtek_bot`).
3. BotFather te da un token como `123456789:AAH...` → `TELEGRAM_BOT_TOKEN`.
   **No lo pegues en ningún chat ni lo subas a GitHub** — con ese token
   cualquiera puede operar tu bot.

**2. Despliega en Railway** con Start Command:
```
uvicorn app.telegram_bot:app --host 0.0.0.0 --port $PORT
```
Variables necesarias: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`
(inventa cualquier cadena), `OPENAI_API_KEY`, `GOOGLE_SHEET_ID`,
`GOOGLE_CREDENTIALS_JSON`.

**3. Conecta el webhook** (una sola llamada, no hay pantalla que configurar
como en Meta). Con tu token y la URL de Railway, corre esto en tu navegador
o con curl:
```
https://api.telegram.org/bot<TU_TOKEN>/setWebhook?url=https://tu-app.up.railway.app/telegram-webhook&secret_token=<TU_TELEGRAM_WEBHOOK_SECRET>
```
Debería regresarte `{"ok":true,"result":true,...}`.

**4. Antes de usarlo con técnicos reales:** edita `TECNICOS` en
`app/telegram_bot.py` con los nombres reales. Cada técnico busca tu bot por
su username en Telegram y le manda `/start`.

### B) Web app
Página tipo chat en el navegador, sin instalar nada. Ver sección siguiente.

### C) Bot de WhatsApp
Más abajo en este README. El más complicado de configurar de los tres —
úsalo solo si específicamente necesitas WhatsApp.

---


Página web tipo chat, sin WhatsApp de por medio. El técnico abre un link en
el navegador de su celular, elige su nombre, y escribe o usa los botones
rápidos (Nueva actividad / Pausar / Reanudar / Finalizar / Mis actividades).

**Correr localmente:**
```bash
pip install -r requirements.txt
cp .env.example .env   # solo necesitas OPENAI_API_KEY, GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON o _PATH
uvicorn app.webapp:app --reload
```
Abre `http://localhost:8000` en el navegador.

**Desplegar en Railway:** mismos pasos que abajo, pero el Start Command es:
```
uvicorn app.webapp:app --host 0.0.0.0 --port $PORT
```
No necesitas ninguna de las variables `WHATSAPP_*` para este canal.

Antes de usarlo con técnicos reales, edita la lista `TECNICOS` en
`app/webapp.py` con los nombres reales (no números de teléfono, aquí es
solo el nombre que aparece en el botón de login).

### B) Bot de WhatsApp
Todo lo que sigue en este README, para el canal de WhatsApp Cloud API.

---



### 1. WhatsApp Cloud API (Meta)
1. Crea una app en [developers.facebook.com](https://developers.facebook.com), tipo "Business".
2. Agrega el producto "WhatsApp".
3. En "API Setup" copia el **Phone number ID** → `WHATSAPP_PHONE_ID`.
4. Genera un token (el temporal de prueba dura 24h; para el piloto real, crea una
   System User con token permanente) → `WHATSAPP_TOKEN`.
5. Inventa cualquier cadena secreta para `WHATSAPP_VERIFY_TOKEN` (la usarás en el paso 4 de despliegue).
6. **Limitación real que debes saber:** con el número de prueba de Meta solo pueden
   escribirte los números que agregues a la lista de "destinatarios de prueba" (hasta 5).
   Para que cualquier técnico use el bot sin restricción necesitas verificar un número
   de WhatsApp Business real — eso toma días, no minutos.

### 2. Google Sheets
1. Crea un Google Sheet nuevo. Copia el ID de la URL (la parte entre `/d/` y `/edit`) → `GOOGLE_SHEET_ID`.
2. En [Google Cloud Console](https://console.cloud.google.com), crea un proyecto, habilita
   la API de Google Sheets, y crea una cuenta de servicio.
3. Descarga el JSON de credenciales de esa cuenta de servicio.
4. **Comparte el Google Sheet** como Editor con el email de la cuenta de servicio
   (el campo `client_email` dentro del JSON, algo como `nombre@proyecto.iam.gserviceaccount.com`)
   — si olvidas este paso, el bot no podrá escribir y fallará en silencio hasta que revises los logs.
5. **No subas el archivo JSON a GitHub.** En Railway, abre el JSON descargado, copia
   TODO su contenido y pégalo como valor de la variable `GOOGLE_CREDENTIALS_JSON`.
   Si en vez de eso prefieres correr el bot en tu propia máquina para pruebas locales,
   ahí sí puedes guardarlo como `credentials.json` y usar `GOOGLE_CREDENTIALS_PATH`
   — pero agrega `credentials.json` a tu `.gitignore` para que nunca se suba por accidente.

### 3. OpenAI
Crea una API key en [platform.openai.com](https://platform.openai.com) → `OPENAI_API_KEY`.

### 4. Desplegar en Railway
1. Sube este código a un repo de GitHub.
2. En Railway, "New Project" → "Deploy from GitHub repo".
3. Agrega todas las variables de `.env.example` en la pestaña Variables de Railway.
4. Comando de arranque: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Sube `credentials.json` como variable o usa el volumen de Railway — **no lo subas al repo**.
6. Copia la URL pública que te da Railway (`https://tu-app.up.railway.app`).
7. En Meta for Developers > WhatsApp > Configuration, pon como Callback URL:
   `https://tu-app.up.railway.app/webhook` y como Verify Token el mismo valor de
   `WHATSAPP_VERIFY_TOKEN`. Suscríbete al campo `messages`.

### 5. Antes de probarlo con técnicos reales
- Edita el diccionario `TECNICOS` en `app/main.py` con los números reales de los 2-3
  técnicos del piloto (formato `52` + 10 dígitos, sin `+` ni espacios).
- Corre `pip install -r requirements.txt` localmente y prueba el flujo con curl o Postman
  antes de exponerlo a técnicos reales.

## Correr localmente
```bash
pip install -r requirements.txt
cp .env.example .env   # y llena los valores
uvicorn app.main:app --reload
```
Para probar el webhook desde tu máquina sin desplegar, usa `ngrok http 8000` y pon esa
URL de ngrok como Callback URL en Meta mientras pruebas.
