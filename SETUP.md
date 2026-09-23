# Guía: bot de Telegram + Google Calendar + Tareas pendientes en Railway

Tres bloques: (1) credenciales de Google, (2) credenciales de Telegram/Anthropic
que ya tienes, (3) desplegar en Railway. Es largo pero cada paso es simple.

**Novedad respecto a la primera versión:** el bot ahora también lleva una lista
de tareas pendientes. La guardo en **Google Tasks** (no en un fichero dentro de
Railway), porque el disco de Railway puede borrarse en cada redeploy y Google
Tasks es gratis, persistente, y ya lo tienes integrado en Calendar/tu móvil.
El bot crea automáticamente una lista llamada "Pendientes Bot" la primera vez
que la usas.

## 1. Credenciales de Google (una sola vez, en tu ordenador)

1. Ve a [console.cloud.google.com](https://console.cloud.google.com/) y crea un proyecto nuevo (arriba a la izquierda).
2. Menú ☰ → **APIs y servicios → Biblioteca** → busca "Google Calendar API" → **Habilitar**. Repite la búsqueda con **"Tasks API"** → **Habilitar**.
3. Menú ☰ → **APIs y servicios → Pantalla de consentimiento OAuth**:
   - Tipo de usuario: **Externo**.
   - Rellena nombre de la app y tu email. Guarda.
   - En "Usuarios de prueba" añade tu propio email de Google (así puedes usar la app sin que Google la revise).
4. Menú ☰ → **APIs y servicios → Credenciales → + Crear credenciales → ID de cliente de OAuth**:
   - Tipo de aplicación: **Aplicación de escritorio**.
   - Descarga el JSON → renómbralo `client_secret.json`.
5. En tu ordenador, en una carpeta con `get_refresh_token.py` y `client_secret.json`:
   ```
   pip install google-auth-oauthlib
   python get_refresh_token.py
   ```
   Se abrirá el navegador, inicias sesión con tu cuenta de Google, aceptas permisos
   (ahora pedirá permiso de Calendar **y** de Tasks, en la misma pantalla).
   La consola te imprimirá `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` y `GOOGLE_REFRESH_TOKEN`.
   **Guárdalos** — los necesitas en el paso 3.

   > Si ya habías hecho este paso para la primera versión del bot (solo con
   > Calendar), tienes que volver a ejecutarlo ahora: el `refresh_token`
   > antiguo no incluye permiso para Tasks y las peticiones de tareas fallarían.

## 2. Lo que ya tienes

- `TELEGRAM_BOT_TOKEN`: el token que te dio @BotFather.
- `TELEGRAM_CHAT_ID`: el que sacaste con `getUpdates` (el mismo que usamos para la tarea de Cowork).
- `ANTHROPIC_API_KEY`: clave de la API de Anthropic. Si no tienes una, se crea en [console.anthropic.com](https://console.anthropic.com/) → API Keys. (Ojo: esto factura aparte de tu suscripción de Claude, por uso — con el volumen de mensajes de un bot personal el coste es mínimo, céntimos al mes.)

## 2bis. Transcripción de audios (Groq)

Para que el bot entienda notas de voz, hace falta una clave de **Groq** (servicio de transcripción, plan gratuito sin tarjeta):

1. Ve a [console.groq.com](https://console.groq.com/) y crea una cuenta (puedes usar tu cuenta de Google para registrarte).
2. Menú → **API Keys** → **Create API Key**. Ponle un nombre y cópiala — es tu `GROQ_API_KEY`.
3. El plan gratuito da 2.000 transcripciones al día, más que de sobra para uso personal, sin necesidad de tarjeta de crédito.

## 3. Desplegar en Railway

1. Sube esta carpeta (`bot.py`, `requirements.txt`, `Procfile`) a un repositorio nuevo en GitHub.
   - Si no usas Git normalmente: en GitHub.com → "New repository" → sube los archivos directamente desde el navegador con "uploading an existing file".
2. Ve a [railway.app](https://railway.app/) → **Login with GitHub** → autoriza.
3. **New Project → Deploy from GitHub repo** → selecciona el repositorio que acabas de subir.
4. Railway detectará el `Procfile` y montará el worker. Antes de que arranque, ve a la pestaña **Variables** del servicio y añade:
   ```
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_CHAT_ID=...
   ANTHROPIC_API_KEY=...
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REFRESH_TOKEN=...
   GROQ_API_KEY=...
   ```
   Opcionales (si no las pones, usa estos valores por defecto):
   ```
   REMINDER_HOUR=8        # hora (24h) del recordatorio diario de pendientes
   REMINDER_MINUTE=0
   GOOGLE_CALENDAR_ID=primary
   ```
5. Railway redepliega solo al guardar las variables. En la pestaña **Deployments → View logs** deberías ver `Bot arrancado, esperando mensajes...`.
6. Escríbele a tu bot en Telegram: `/hoy` — debería devolverte los eventos de hoy.

## Uso una vez funcionando

- `/hoy` y `/manana` → lista de eventos de tu Google Calendar.
- `/tareas` → lista tus pendientes.
- `/deseos` → lista tu lista de deseos/compras futuras.
- *"añade cena con Marta el viernes de 21:00 a 23:00 en naranja"* → crea el evento en el Calendar con ese color.
- *"apunta que tengo que llevar el coche al taller"* → lo añade a pendientes (sin fecha).
- *"añade a la lista de la compra: unas zapatillas de correr, una batidora"* → los añade a la lista de deseos (no a pendientes).
- *"planifica lo del coche el jueves a las 10h"* → busca el pendiente parecido a "coche" (en cualquiera de las dos listas), lo pasa al Calendar ese día/hora, y lo quita de la lista.
- **Audios**: mándale una nota de voz con cualquiera de las peticiones de arriba — la transcribe con Groq/Whisper y la trata exactamente igual que si la hubieras escrito. Te contesta primero con lo que ha entendido, para que puedas comprobar que la transcripción es correcta.
- Colores reconocidos: azul, verde, rojo, amarillo, naranja, morado, rosa, gris.
- Cada día a la hora que pongas en `REMINDER_HOUR` (8:00 por defecto), el bot te manda solo por su cuenta la lista de **pendientes** (no la de deseos, que no es urgente por naturaleza) — no hace falta que se lo pidas.

## Notas

- El bot solo responde a tu `TELEGRAM_CHAT_ID` — nadie más puede usarlo aunque encuentre el nombre del bot.
- Railway tiene un plan gratuito con horas/mes de sobra para un bot de uso personal; si algún mes te acercas al límite, avisa por email antes de cobrar nada.
- Este bot es independiente de la tarea programada de Cowork del recordatorio de las 12:00 — puedes tener ambos a la vez sin que choquen.
