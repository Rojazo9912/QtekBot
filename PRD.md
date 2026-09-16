# PRD — Reporte de Campo Ágil para Mina

**Versión:** 1.1 — actualizado tras el piloto implementado  
**Estado:** Piloto funcional en Telegram, pendiente de aprobación para producción  
**Canal:** Telegram Bot  

*Este documento actualiza la v1.0 con lo que realmente se construyó y probó. Los cambios respecto al documento original están marcados explícitamente — no se ocultó ningún ajuste de alcance.*

---

## 0. Resumen de cambios frente al PRD v1.0

La decisión más importante: se mantuvo la pila tecnológica de un piloto anterior (Python + FastAPI + Google Sheets + Google Drive + Railway) en vez de migrar a la pila originalmente especificada (Node.js/TypeScript + Supabase PostgreSQL + Supabase Storage). El FLUJO de conversación del PRD v1.0 se implementó completo; la infraestructura de datos es distinta.

| Aspecto | PRD v1.0 (pedido) | Implementado |
|---|---|---|
| **Backend** | Node.js + TypeScript | Python + FastAPI |
| **Base de datos** | PostgreSQL (Supabase) | Google Sheets |
| **Archivos/evidencias** | Supabase Storage | Google Drive |
| **Flujo de conversación** | Botones, ticket obligatorio, ubicación fija, confirmación | Igual — implementado completo |
| **Auth / roles** | TECHNICIAN / SUPERVISOR / ADMIN | No implementado |
| **Resiliencia offline** | Reintentos + idempotencia | Parcial — ver sección 15 |
| **Dashboard** | Web dedicada (React/Next.js) | El propio Google Sheet |

---

## 1. Objetivo

El sistema debe permitir que un técnico registre una actividad en pocos pasos. Sin cambios respecto al v1.0.

El reporte solamente solicita:
1. Ticket
2. Ubicación
3. Actividad realizada
4. Estado
5. Foto opcional

El sistema obtiene automáticamente: Técnico, Fecha, Hora, Número de reporte.

**✔ Cumplido tal cual se pidió**

---

## 2. Flujo principal (implementado)

### Paso 1 — Ticket
🎫 **Ingresa el número de ticket:** Obligatorio, texto libre, sin IA de por medio.

### Paso 2 — Ubicación
📍 **Lista fija por botones:** Nivel 10 / Nivel 11 / Nivel 12 / Otra. Configurable editando una lista en el código (no requiere base de datos aparte).

### Paso 3 — Actividad
📝 **Texto libre**, sin campos adicionales, tal como especifica el v1.0.

### Paso 4 — Estado
📊 **Tres botones:** ✅ Terminado / ⏸️ Pendiente / ❌ No solucionado.

### Paso 5 — Evidencia
📷 **Opcional, por botón** (Agregar foto / Omitir). Permite varias fotos antes de continuar, con confirmación 'Otra foto / Continuar' entre cada una — este sub-paso no estaba detallado en el v1.0 y se añadió para permitir más de una foto sin ambigüedad.

**✔ Los 5 pasos están implementados y probados de punta a punta**

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
| **Tecnico** | Nombre del técnico | Automático (por sesión) |
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
