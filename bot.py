"""
Bot de Telegram — versión 3: audios + lista de deseos/compras futuras.

Funciones:
  - /hoy, /manana         -> eventos de Google Calendar de hoy/mañana.
  - /tareas                -> lista tus pendientes (cosas por hacer).
  - /deseos                -> lista tu lista de compras futuras / deseos.
  - Mensaje libre (texto O AUDIO), Claude decide qué quieres hacer:
      * crear un evento en el Calendar (con día/hora/color)
      * añadir uno o varios pendientes a "Pendientes" o a "Deseos/Compras"
      * listar cualquiera de las dos listas
      * planificar un pendiente ya existente como evento en el Calendar
  - Cada día a REMINDER_HOUR (8:00 por defecto, hora de Madrid), manda la
    lista de "Pendientes" (no la de deseos, que no es urgente por naturaleza).

Los audios se transcriben con Groq (Whisper Large v3 Turbo) antes de pasarlos
por el mismo intérprete que el texto — así que todo lo que puedes pedir
escribiendo, lo puedes pedir hablando.

Ambas listas se guardan en Google Tasks, en dos listas separadas
("Pendientes Bot" y "Deseos / Compras Bot") — no dependen del almacenamiento
de Railway y las puedes ver también desde la app de Google Tasks.
"""

import os
import json
import datetime as dt
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import anthropic
from groq import Groq

# ---------- Config desde variables de entorno ----------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
GOOGLE_REFRESH_TOKEN = os.environ["GOOGLE_REFRESH_TOKEN"]
CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")

REMINDER_HOUR = int(os.environ.get("REMINDER_HOUR", "8"))
REMINDER_MINUTE = int(os.environ.get("REMINDER_MINUTE", "0"))
TIMEZONE = ZoneInfo("Europe/Madrid")

# Dos listas de Google Tasks distintas, identificadas internamente por una clave corta.
TASKLIST_NAMES = {
    "pendientes": "Pendientes Bot",
    "deseos": "Deseos / Compras Bot",
}

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

COLOR_MAP = {
    "lavanda": "1", "morado": "3", "grape": "3", "violeta": "3",
    "salvia": "2", "verde": "10", "basil": "10",
    "flamenco": "4", "rosa": "4",
    "amarillo": "5", "banana": "5",
    "naranja": "6", "tangerina": "6",
    "azul": "9", "peacock": "7", "azul_claro": "7",
    "gris": "8", "grafito": "8",
    "rojo": "11", "tomate": "11",
}

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]


def get_credentials():
    return Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )


def get_calendar_service():
    return build("calendar", "v3", credentials=get_credentials())


def get_tasks_service():
    return build("tasks", "v1", credentials=get_credentials())


def get_or_create_tasklist(service, lista: str = "pendientes") -> str:
    """Devuelve el id de la lista pedida ('pendientes' o 'deseos'), creándola si no existe."""
    nombre = TASKLIST_NAMES.get(lista, TASKLIST_NAMES["pendientes"])
    tasklists = service.tasklists().list().execute().get("items", [])
    for tl in tasklists:
        if tl["title"] == nombre:
            return tl["id"]
    new_list = service.tasklists().insert(body={"title": nombre}).execute()
    return new_list["id"]


def check_auth(update: Update) -> bool:
    return update.effective_chat.id == TELEGRAM_CHAT_ID


# ---------- Calendar ----------

def list_events(day_offset: int) -> str:
    service = get_calendar_service()
    day = dt.date.today() + dt.timedelta(days=day_offset)
    start = dt.datetime.combine(day, dt.time.min).isoformat() + "Z"
    end = dt.datetime.combine(day, dt.time.max).isoformat() + "Z"

    events_result = service.events().list(
        calendarId=CALENDAR_ID, timeMin=start, timeMax=end,
        singleEvents=True, orderBy="startTime",
    ).execute()
    events = events_result.get("items", [])

    if not events:
        return f"No tienes eventos el {day.strftime('%d/%m')}."

    lines = [f"📅 Eventos del {day.strftime('%d/%m')}:"]
    for e in events:
        start_time = e["start"].get("dateTime", e["start"].get("date"))
        hora = start_time.split("T")[1][:5] if "T" in start_time else "todo el día"
        lines.append(f"• {hora} — {e.get('summary', '(sin título)')}")
    return "\n".join(lines)


def create_event(titulo, fecha, hora_inicio, hora_fin, color) -> str:
    service = get_calendar_service()
    color_id = COLOR_MAP.get((color or "").lower())
    body = {
        "summary": titulo,
        "start": {"dateTime": f"{fecha}T{hora_inicio}:00", "timeZone": "Europe/Madrid"},
        "end": {"dateTime": f"{fecha}T{hora_fin}:00", "timeZone": "Europe/Madrid"},
    }
    if color_id:
        body["colorId"] = color_id
    created = service.events().insert(calendarId=CALENDAR_ID, body=body).execute()
    color_txt = f" (color: {color})" if color_id else ""
    return f"✅ Evento creado: \"{titulo}\" el {fecha} de {hora_inicio} a {hora_fin}{color_txt}."


# ---------- Tasks (pendientes y deseos) ----------

ETIQUETAS = {"pendientes": ("📝 Pendientes", "No tienes tareas pendientes. 🎉"),
             "deseos": ("🛒 Deseos / compras futuras", "No tienes nada apuntado en deseos.")}


def list_tasks(lista: str = "pendientes") -> str:
    service = get_tasks_service()
    tasklist_id = get_or_create_tasklist(service, lista)
    result = service.tasks().list(tasklist=tasklist_id, showCompleted=False).execute()
    items = result.get("items", [])
    titulo, vacio = ETIQUETAS.get(lista, ETIQUETAS["pendientes"])
    if not items:
        return vacio
    lines = [f"{titulo}:"]
    for it in items:
        lines.append(f"• {it['title']}")
    return "\n".join(lines)


def add_tasks(titulos: list, lista: str = "pendientes") -> str:
    service = get_tasks_service()
    tasklist_id = get_or_create_tasklist(service, lista)
    for titulo in titulos:
        service.tasks().insert(tasklist=tasklist_id, body={"title": titulo}).execute()
    destino = "deseos/compras" if lista == "deseos" else "pendientes"
    if len(titulos) == 1:
        return f"✅ Añadido a {destino}: \"{titulos[0]}\""
    lineas = "\n".join(f"• {t}" for t in titulos)
    return f"✅ Añadidos {len(titulos)} a {destino}:\n{lineas}"


def find_task_by_title(query: str, lista: str = "pendientes"):
    """Busca (coincidencia parcial, sin distinguir mayúsculas) una tarea en la
    lista indicada cuyo título se parezca al que ha mencionado el usuario."""
    service = get_tasks_service()
    tasklist_id = get_or_create_tasklist(service, lista)
    items = service.tasks().list(tasklist=tasklist_id, showCompleted=False).execute().get("items", [])
    query_low = query.lower()
    for it in items:
        if query_low in it["title"].lower() or it["title"].lower() in query_low:
            return tasklist_id, it
    return tasklist_id, None


# ---------- Transcripción de audio (Groq / Whisper) ----------

async def transcribir_audio(update: Update) -> str:
    voice = update.message.voice or update.message.audio
    tg_file = await voice.get_file()
    ruta_local = f"/tmp/{voice.file_unique_id}.ogg"
    await tg_file.download_to_drive(ruta_local)

    with open(ruta_local, "rb") as f:
        transcripcion = groq_client.audio.transcriptions.create(
            file=f,
            model="whisper-large-v3-turbo",
            language="es",
        )
    os.remove(ruta_local)
    return transcripcion.text.strip()


# ---------- Interpretación del mensaje libre con Claude ----------

def interpretar_mensaje(texto_usuario: str) -> dict:
    hoy = dt.date.today().isoformat()
    prompt = f"""Hoy es {hoy}. El usuario te ha escrito este mensaje a un bot de
Telegram que gestiona su Google Calendar y dos listas de tareas: "pendientes"
(cosas por hacer) y "deseos" (cosas que quiere comprar en el futuro, una
lista de deseos/compra):

"{texto_usuario}"

Devuelve SOLO un JSON (sin texto adicional, sin markdown) con esta forma exacta:
{{
  "intencion": "crear_evento" | "anadir_tarea" | "listar_tareas" | "planificar_tarea" | "otro",
  "lista": "pendientes" | "deseos",   // a qué lista se refiere (anadir_tarea, listar_tareas, planificar_tarea). Por defecto "pendientes" si no está claro.
  "titulos": ["..."],           // lista de títulos — SOLO si intencion es anadir_tarea. Un mensaje puede pedir varios a la vez (comas, saltos de línea, guiones...) — una entrada por cada uno.
  "titulo": "...",              // título del evento (crear_evento) o texto para buscar la tarea (planificar_tarea)
  "fecha": "YYYY-MM-DD",        // solo si intencion es crear_evento o planificar_tarea
  "hora_inicio": "HH:MM",       // solo si intencion es crear_evento o planificar_tarea
  "hora_fin": "HH:MM",          // solo si intencion es crear_evento o planificar_tarea
  "color": "azul|verde|rojo|amarillo|naranja|morado|rosa|gris|null"
}}

Guía:
- "lista": "deseos" cuando el usuario hable de comprar algo, algo que quiere
  tener/pillar en el futuro, un capricho, un regalo pendiente de comprar, etc.
  "pendientes" para cualquier otra cosa por hacer (llamadas, gestiones, tareas).
- "anadir_tarea": el usuario quiere apuntar una o varias cosas, sin fecha
  concreta (p. ej. "apunta que tengo que llamar al dentista" → pendientes; o
  "añade a la lista de la compra: unas zapatillas de correr, una batidora" →
  deseos, dos entradas en "titulos"). Si el mensaje es solo la frase
  introductoria sin nada detrás, usa intencion "otro".
- "crear_evento": el usuario da una fecha/hora concreta para algo NUEVO.
- "planificar_tarea": el usuario se refiere a un pendiente que ya existe (de
  cualquiera de las dos listas) y quiere ponerle fecha/hora en el calendario.
  En "titulo" pon el texto que identifica la tarea a buscar.
- "listar_tareas": el usuario pregunta qué tiene en alguna de las dos listas.
- "otro": cualquier otra cosa (charla, pregunta no relacionada, mensaje
  incompleto sin contenido que añadir, etc.)."""

    resp = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=350,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"intencion": "otro"}
    data.setdefault("lista", "pendientes")
    if data["lista"] not in TASKLIST_NAMES:
        data["lista"] = "pendientes"
    return data


# ---------- Lógica compartida (texto y audio pasan por aquí) ----------

async def procesar_texto(update: Update, texto: str):
    data = interpretar_mensaje(texto)
    intencion = data.get("intencion")
    lista = data.get("lista", "pendientes")

    if intencion == "crear_evento":
        msg = create_event(data["titulo"], data["fecha"], data["hora_inicio"], data["hora_fin"], data.get("color"))
        await update.message.reply_text(msg)

    elif intencion == "anadir_tarea":
        titulos = data.get("titulos") or []
        if not titulos:
            await update.message.reply_text(
                "¿Qué quieres que apunte, y en qué lista? Dímelo en el mismo mensaje, "
                "p. ej. \"añade a la lista de la compra: unas zapatillas nuevas\"."
            )
            return
        msg = add_tasks(titulos, lista)
        await update.message.reply_text(msg)

    elif intencion == "listar_tareas":
        await update.message.reply_text(list_tasks(lista))

    elif intencion == "planificar_tarea":
        tasklist_id, tarea = find_task_by_title(data["titulo"], lista)
        if not tarea:
            await update.message.reply_text(
                f"No encuentro nada parecido a \"{data['titulo']}\" en esa lista. "
                f"Usa /tareas o /deseos para ver el contenido exacto."
            )
            return
        msg = create_event(tarea["title"], data["fecha"], data["hora_inicio"], data["hora_fin"], data.get("color"))
        service = get_tasks_service()
        service.tasks().delete(tasklist=tasklist_id, task=tarea["id"]).execute()
        await update.message.reply_text(msg + "\n(Lo he quitado de la lista ya que tiene hueco en el calendario.)")

    else:
        await update.message.reply_text(
            "No lo tengo claro. Puedes pedirme cosas como:\n"
            "• \"añade cena el viernes de 21 a 23 en naranja\"\n"
            "• \"apunta que tengo que llamar al dentista\"\n"
            "• \"añade a la lista de la compra: unas zapatillas\"\n"
            "• \"planifica lo de las zapatillas el jueves a las 18h\"\n"
            "• /hoy, /manana, /tareas, /deseos"
        )


# ---------- Handlers de Telegram ----------

async def cmd_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        return
    await update.message.reply_text(list_events(0))


async def cmd_manana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        return
    await update.message.reply_text(list_events(1))


async def cmd_tareas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        return
    await update.message.reply_text(list_tasks("pendientes"))


async def cmd_deseos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        return
    await update.message.reply_text(list_tasks("deseos"))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        return
    await procesar_texto(update, update.message.text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        return
    try:
        texto = await transcribir_audio(update)
    except Exception as e:
        await update.message.reply_text(f"No he podido transcribir el audio ({e}).")
        return
    if not texto:
        await update.message.reply_text("No he entendido nada en el audio, ¿puedes repetirlo?")
        return
    await update.message.reply_text(f"🎙️ Te he entendido: \"{texto}\"")
    await procesar_texto(update, texto)


async def recordatorio_diario(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=list_tasks("pendientes"))


def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("hoy", cmd_hoy))
    app.add_handler(CommandHandler("manana", cmd_manana))
    app.add_handler(CommandHandler("tareas", cmd_tareas))
    app.add_handler(CommandHandler("deseos", cmd_deseos))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

    app.job_queue.run_daily(
        recordatorio_diario,
        time=dt.time(hour=REMINDER_HOUR, minute=REMINDER_MINUTE, tzinfo=TIMEZONE),
    )

    print("Bot arrancado, esperando mensajes...")
    app.run_polling()


if __name__ == "__main__":
    main()
