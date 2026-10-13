# PRD — Reporte de Campo Ágil para Mina

**Versión:** 1.2 — actualizado con departamentos, zonas dinámicas y endurecimiento de seguridad  
**Estado:** Piloto funcional en Telegram, probado con Supabase y exportación Excel  
**Canal:** Telegram Bot  

---

## 0. Resumen de evolución del producto

| Aspecto | PRD v1.0 / v1.1 | Implementado v1.2 |
|---|---|---|
| **Backend** | Python + FastAPI | Python + FastAPI |
| **Base de datos** | PostgreSQL (Supabase) | PostgreSQL (Supabase) con catálogos dinámicos (`departamentos`, `zonas`, `reportes`) |
| **Archivos/evidencias** | Supabase Storage | Supabase Storage (validación estricta de imágenes, máx 10 MB) |
| **Flujo de conversación** | 5 pasos (Ticket, Ubicación, Actividad, Estado, Foto) | 7 pasos (Ticket, Departamento, Zona, Actividad, Estado, Evidencia, Confirmación) |
| **Catálogos dinámicos** | Ubicaciones fijas | Departamentos y zonas dinámicos en Supabase con auto-registro de zonas ("Otra") |
| **Comandos Admin** | `/nuevo_tecnico`, `/reporte` | `/nuevo_tecnico`, `/nuevo_departamento`, `/departamentos`, `/reporte` |
| **Reportes y Exportación**| Excel estático | Excel dinámico agrupado por departamento y ubicación |

---

## 1. Objetivo

El sistema permite que un técnico registre una actividad en campo de forma guiada e interactiva.

El reporte solicita secuencialmente:
1. Ticket
2. Departamento
3. Zona / Ubicación
4. Actividad realizada
5. Estado final
6. Foto(s) de evidencia opcional(es)
7. Confirmación final antes del guardado

El sistema obtiene automáticamente: Técnico, Fecha, Hora, Número de reporte (`#001`, `#002`...).

---

## 2. Flujo principal (implementado en 7 pasos)

### Paso 1 — Ticket
🎫 **Ingresa el número de ticket:** Texto libre (ej. `TK-001254`) o botón **Sin ticket** (genera folio temporal `S/T-AAMMDD-HHMMSS`).

### Paso 2 — Departamento
🏢 **Selección por lista/botones:** Departamentos dinámicos de Supabase (ej. `Infraestructura`, `Mantenimiento`). Administrable vía `/nuevo_departamento` y `/departamentos`.

### Paso 3 — Zona / Ubicación
📍 **Selección dinámica:** Zonas de Supabase (ej. `Nivel 10`, `Nivel 11`, `Nivel 12`) o **Otra**. Al teclear una zona nueva o elegir Otra, se persiste automáticamente en el catálogo para futuros reportes.

### Paso 4 — Actividad
📝 **Texto libre**, descripción breve del trabajo realizado.

### Paso 5 — Estado
📊 **Tres botones:** ✅ Terminado / ⏸️ Pendiente / ❌ No solucionado.

### Paso 6 — Evidencia
📷 **Opcional, por botón** (Agregar foto / Omitir). Valida que sea imagen real y que no supere 10 MB. Permite varias fotos antes de continuar.

### Paso 7 — Confirmación
📋 **Resumen previo al guardado:** Muestra Ticket, Departamento, Ubicación, Actividad, Estado y conteo de evidencias, con opciones `✅ Guardar`, `✏️ Editar`, `❌ Cancelar`.

**✔ Los 7 pasos están implementados y probados de punta a punta**

---

## 3. Confirmación

Antes de guardar se muestra el resumen (Ticket, Ubicación, Actividad, Estado, si hay Evidencia) con tres botones: **✅ Guardar** / **✏️ Editar** / **❌ Cancelar**.

*Diferencia respecto al v1.0:* "✏️ Editar" reinicia el reporte completo desde el paso de Ticket, no permite corregir un solo campo. Simplificación deliberada para no inflar el piloto; si se necesita edición granular, es un desarrollo aparte.

---

## 4. Reporte generado

Al guardar, el bot confirma con el mismo formato del v1.0: número de reporte, ticket, ubicación, actividad, estado, técnico, fecha y hora — generados automáticamente.

---

## 5. Actividades pendientes

"⏸️ Mis pendientes" lista los reportes en estado Pendiente del técnico, cada uno con botones **▶️ Continuar** / **✅ Finalizar**.

Al elegir Continuar, el bot pide una descripción de la actualización, la anexa al campo Actividad con marca de tiempo, y vuelve a preguntar el Estado. No se crea un reporte nuevo — se actualiza el mismo, tal como pide la Regla 8.

---

## 6. Menú principal

Tres botones fijos: **➕ Nuevo reporte** · **⏸️ Mis pendientes** · **📋 Mis reportes**. Sin funciones adicionales, según el principio de simplicidad del v1.0.

---

## 7. Historial (Mis reportes)

Lista los reportes del técnico con número, ticket y estado (✅/⏸️/❌). No permite abrir un reporte individual para ver el detalle completo dentro del chat — limitación frente al v1.0, que sí lo pedía.

---

## 8. Dashboard

No se construyó un dashboard web dedicado (React/Next.js). El propio Google Sheet cumple ese papel: cualquier persona con el link puede ver los reportes, filtrar con las herramientas nativas de Sheets, y no requiere mantenimiento de un frontend aparte.

Si más adelante se necesita el dashboard con contadores diarios y filtros del v1.0, es un desarrollo nuevo, independiente del bot.

---

## 9. Modelo de datos (implementado en Google Sheets, no PostgreSQL)

Una sola hoja **"Reportes"** con estas columnas:

| Columna | Contenido | ¿Quién la llena? |
|---|---|---|
| **Numero** | Consecutivo #001, #002… | Automático |
| **Ticket** | Texto libre, obligatorio | Técnico |
| **Departamento** | Infraestructura | Automático |
| **Ubicacion** | De la lista fija, o texto si "Otra" | Técnico (botón) |
| **Actividad** | Descripción; se le anexan actualizaciones | Técnico |
| **Estado** | Terminado / Pendiente / No solucionado | Técnico (botón) |
| **Evidencias** | Links de Google Drive, uno o varios | Automático al subir foto |
| **Fecha** | YYYY-MM-DD | Automático |
| **Hora** | HH:MM:SS, zona horaria de México | Automático |
| **Actualizado** | Fecha/hora del último "Continuar" | Automático |

No existen tablas separadas de usuarios, ubicaciones o evidencias como pedía el v1.0 — todo vive en una sola hoja de cálculo. Es suficiente para un piloto de 2-3 técnicos; no escala bien a decenas de técnicos con reportes simultáneos.

---

## 10. Estados

Se usan exactamente los tres estados pedidos: **Terminado**, **Pendiente**, **No solucionado** (como texto, no como enum COMPLETED/PENDING/FAILED de una base de datos relacional — Sheets no impone ese tipo de restricción, así que la validez del valor depende del código del bot, no de la base de datos).

---

## 11. Fecha y hora

No se le pide fecha ni hora al técnico. Se registran automáticamente con zona horaria de Ciudad de México/Durango — se corrigió durante el piloto un bug donde se guardaba en UTC del servidor.

---

## 12. Número de reporte

Consecutivo automático (`#001`, `#002`…), calculado contando las filas existentes en la hoja al momento de crear el reporte. El técnico nunca lo introduce.

*Riesgo técnico no trivial:* si dos técnicos guardan un reporte al mismo tiempo exacto, podría haber una condición de carrera que duplique un número de folio. Con 2-3 técnicos el riesgo es bajo pero existe; una base de datos transaccional (como pedía el v1.0) lo evita de raíz.

---

## 13. Ticket

Obligatorio, se guarda como texto libre — acepta cualquier formato (`TK-001254`, `INC-2548`, `OT-1025`, etc.), tal como pedía el v1.0.

---

## 14. Fotografías

Opcionales, una o varias por reporte. Se suben a Google Drive (no Supabase Storage) y se guarda el link en la columna Evidencias.

*Nota de privacidad no contemplada en el v1.0:* las fotos quedan con permiso "cualquiera con el link puede ver" — no son públicas por buscador, pero tampoco están restringidas a personas específicas de la organización.

---

## 15. Conectividad y resiliencia

Esta es la sección donde más se alejó del PRD original:
- Telegram reintenta la ENTREGA del mensaje al bot si el técnico se queda sin señal — eso sí funciona, es una garantía del propio Telegram, no del código.
- NO existe un identificador único de operación para evitar duplicados en reintentos.
- Si el servidor (Railway) se reinicia justo cuando un técnico está a mitad de un reporte, se pierde el progreso de esa conversación (no los reportes ya guardados). El técnico tiene que volver a empezar ese reporte desde "➕ Nuevo reporte".

**Para cerrar esta brecha de verdad hace falta la base de datos transaccional que el PRD original pedía desde el inicio — es la limitación más seria de haber mantenido Google Sheets en vez de Postgres.**

---

## 16. Tecnologías (reales, no las especificadas en v1.0)

| Componente | Tecnología |
|---|---|
| **Backend** | Python 3.13 + FastAPI |
| **Base de datos** | Google Sheets (vía API de Google, librería `gspread`) |
| **Archivos** | Google Drive (vía Google API Python Client) |
| **Bot** | Telegram Bot API (webhooks) |
| **Hosting** | Railway |
| **Dashboard** | No implementado — se usa el Google Sheet directamente |

---

## 17. Seguridad

**Implementado:**
- Variables de entorno para todos los tokens/credenciales (no hay tokens en el código fuente).
- Secreto de verificación de webhook (`TELEGRAM_WEBHOOK_SECRET`) para que nadie más pueda mandarle peticiones falsas al bot.
- Cuenta de servicio de Google con permisos acotados solo al Sheet y carpeta de Drive compartidos explícitamente.

**NO implementado (pedido en v1.0):**
- Autenticación de usuarios más allá de una lista fija de nombres.
- Roles (`TECHNICIAN` / `SUPERVISOR` / `ADMIN`) — todos los técnicos tienen las mismas capacidades.
- Registro de auditoría de cambios (quién editó qué y cuándo, más allá de la columna "Actualizado").

---

## 18. Reglas de negocio

| Regla | Estado |
|---|---|
| 1. Todo reporte debe tener un ticket | ✔ Cumplida |
| 2. Todo reporte debe tener ubicación | ✔ Cumplida |
| 3. Todo reporte debe tener descripción de actividad | ✔ Cumplida |
| 4. Todo reporte debe tener estado | ✔ Cumplida |
| 5. La fotografía es opcional | ✔ Cumplida |
| 6. El técnico no introduce fecha ni hora | ✔ Cumplida |
| 7. El técnico no introduce su nombre | ✔ Cumplida (queda ligado a su sesión de Telegram) |
| 8. Los reportes pendientes pueden continuar | ✔ Cumplida |
| 9. No crear reportes duplicados por reintentos | ⚠ Parcial — sin identificador de operación único |

---

## 19. Estado actual del MVP

**Telegram:**
- Nuevo reporte, Ticket, Ubicación, Actividad, Estado, Fotografía, Confirmación — implementado.
- Mis pendientes, Mis reportes — implementado.

**Dashboard:**
- Lista de reportes, filtros, detalle, contadores — NO implementado (se usa el Sheet directamente).

**Backend:**
- API y lógica de reportes — implementado en Python/FastAPI.
- Base de datos relacional, usuarios con roles — NO implementado.

---

## 20. Fuera del MVP

Sin cambios respecto al v1.0 — se mantiene fuera: IA, inventario, control de materiales, mantenimiento preventivo, análisis predictivo, horas trabajadas, prioridades, categorías complejas, sistema completo de tickets, notificaciones avanzadas, integraciones externas.

*Nota: la ausencia de IA es intencional y coherente con este PRD — es distinto del piloto anterior de este mismo proyecto, que sí usaba IA para interpretar texto libre. Ese piloto se mantiene como alternativa en el mismo repositorio, no se usa aquí.*

---

## 21. Criterios de aceptación — verificación real

| Criterio | ¿Se cumple? |
|---|---|
| Un técnico puede crear un reporte rápidamente | ✔ Sí, probado |
| El ticket es obligatorio | ✔ Sí |
| La ubicación es obligatoria | ✔ Sí (botón, no se puede omitir) |
| La actividad es obligatoria | ✔ Sí |
| El estado es obligatorio | ✔ Sí (botón, no se puede omitir) |
| La foto es opcional | ✔ Sí |
| Fecha y hora automáticas | ✔ Sí, con zona horaria correcta |
| El técnico queda identificado automáticamente | ✔ Sí, por sesión de Telegram |
| El sistema genera número de reporte | ✔ Sí, consecutivo |
| Un reporte pendiente puede continuar | ✔ Sí |
| El supervisor puede consultar los reportes | ✔ Sí, vía el Google Sheet directamente |
| El sistema evita duplicados | ⚠ Parcial, sin garantía formal |
| Funciona con conexión intermitente | ⚠ Parcial — depende de reintentos de Telegram, no de lógica propia |

---

## 22. Principio del sistema

*Sin cambios: "El técnico reporta. El sistema organiza." No se agregaron campos o funciones que no estuvieran en el v1.0 — las diferencias de este documento son de infraestructura (dónde vive el dato) y de dos huecos honestos (duplicados, dashboard), no de alcance funcional para el técnico en campo.*
