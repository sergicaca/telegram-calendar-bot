"""
Bot de Telegram — versión 2, añade gestión de tareas pendientes.

Funciones:
  - /hoy, /manana        -> eventos de Google Calendar de hoy/mañana.
  - /tareas               -> lista tus tareas pendientes.
  - Mensaje libre, Claude decide qué quieres hacer:
      * crear un evento en el Calendar (con día/hora/color)
      * añadir una tarea pendiente a la lista
      * listar las tareas pendientes
      * planificar una tarea pendiente ya existente como evento en el Calendar
  - Cada día a la hora definida en REMINDER_HOUR (por defecto 8:00, hora de
    Madrid), te manda solo la lista de tareas pendientes por Telegram.

Las tareas pendientes se guardan en Google Tasks (una lista llamada
"Pendientes Bot" dentro de tu cuenta de Google) — así no dependen del
almacenamiento de Railway, que puede borrarse en cada redeploy, y las puedes
ver también desde la app de Google Tasks o la barra lateral de Calendar.
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

# ---------- Config desde variables de entorno ----------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
GOOGLE_REFRESH_TOKEN = os.environ["GOOGLE_REFRESH_TOKEN"]
CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")

REMINDER_HOUR = int(os.environ.get("REMINDER_HOUR", "8"))
REMINDER_MINUTE = int(os.environ.get("REMINDER_MINUTE", "0"))
TIMEZONE = ZoneInfo("Europe/Madrid")

TASKLIST_NAME = "Pendientes Bot"

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

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


def get_or_create_tasklist(service) -> str:
    """Devuelve el id de la lista 'Pendientes Bot', creándola si no existe."""
    lists = service.tasklists().list().execute().get("items", [])
    for tl in lists:
        if tl["title"] == TASKLIST_NAME:
            return tl["id"]
    new_list = service.tasklists().insert(body={"title": TASKLIST_NAME}).execute()
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


# ---------- Tasks (pendientes) ----------

def list_pending_tasks() -> str:
    service = get_tasks_service()
    tasklist_id = get_or_create_tasklist(service)
    result = service.tasks().list(tasklist=tasklist_id, showCompleted=False).execute()
    items = result.get("items", [])
    if not items:
        return "No tienes tareas pendientes. 🎉"
    lines = ["📝 Pendientes:"]
    for it in items:
        lines.append(f"• {it['title']}")
    return "\n".join(lines)


def add_pending_task(titulo: str) -> str:
    service = get_tasks_service()
    tasklist_id = get_or_create_tasklist(service)
    service.tasks().insert(tasklist=tasklist_id, body={"title": titulo}).execute()
    return f"✅ Añadido a pendientes: \"{titulo}\""


def find_task_by_title(query: str):
    """Busca (por coincidencia parcial, sin distinguir mayúsculas) una tarea
    pendiente cuyo título se parezca al que ha mencionado el usuario."""
    service = get_tasks_service()
    tasklist_id = get_or_create_tasklist(service)
    items = service.tasks().list(tasklist=tasklist_id, showCompleted=False).execute().get("items", [])
    query_low = query.lower()
    for it in items:
        if query_low in it["title"].lower() or it["title"].lower() in query_low:
            return tasklist_id, it
    return tasklist_id, None


# ---------- Interpretación del mensaje libre con Claude ----------

def interpretar_mensaje(texto_usuario: str) -> dict:
    hoy = dt.date.today().isoformat()
    prompt = f"""Hoy es {hoy}. El usuario te ha escrito este mensaje a un bot de
Telegram que gestiona su Google Calendar y una lista de tareas pendientes:

"{texto_usuario}"

Devuelve SOLO un JSON (sin texto adicional, sin markdown) con esta forma exacta:
{{
  "intencion": "crear_evento" | "anadir_tarea" | "listar_tareas" | "planificar_tarea" | "otro",
  "titulo": "...",              // título del evento o de la tarea, según intención
  "fecha": "YYYY-MM-DD",        // solo si intencion es crear_evento o planificar_tarea
  "hora_inicio": "HH:MM",       // solo si intencion es crear_evento o planificar_tarea
  "hora_fin": "HH:MM",          // solo si intencion es crear_evento o planificar_tarea
  "color": "azul|verde|rojo|amarillo|naranja|morado|rosa|gris|null"
}}

Guía:
- "anadir_tarea": el usuario quiere apuntar algo pendiente sin fecha concreta
  (p. ej. "apunta que tengo que comprar zapatillas nuevas").
- "crear_evento": el usuario da una fecha/hora concreta para algo NUEVO que no
  mencionaba como pendiente antes.
- "planificar_tarea": el usuario se refiere a un pendiente que ya existe y
  quiere ponerle fecha/hora en el calendario (p. ej. "planifica lo de las
  zapatillas el jueves a las 18h"). En "titulo" pon el texto que identifica
  la tarea a buscar (no hace falta que sea exacto).
- "listar_tareas": el usuario pregunta qué pendientes tiene.
- "otro": cualquier otra cosa (charla, pregunta no relacionada, etc.)."""

    resp = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"intencion": "otro"}


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
    await update.message.reply_text(list_pending_tasks())


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        return

    data = interpretar_mensaje(update.message.text)
    intencion = data.get("intencion")

    if intencion == "crear_evento":
        msg = create_event(data["titulo"], data["fecha"], data["hora_inicio"], data["hora_fin"], data.get("color"))
        await update.message.reply_text(msg)

    elif intencion == "anadir_tarea":
        msg = add_pending_task(data["titulo"])
        await update.message.reply_text(msg)

    elif intencion == "listar_tareas":
        await update.message.reply_text(list_pending_tasks())

    elif intencion == "planificar_tarea":
        tasklist_id, tarea = find_task_by_title(data["titulo"])
        if not tarea:
            await update.message.reply_text(
                f"No encuentro ningún pendiente parecido a \"{data['titulo']}\". "
                f"Usa /tareas para ver la lista exacta."
            )
            return
        msg = create_event(tarea["title"], data["fecha"], data["hora_inicio"], data["hora_fin"], data.get("color"))
        service = get_tasks_service()
        service.tasks().delete(tasklist=tasklist_id, task=tarea["id"]).execute()
        await update.message.reply_text(msg + "\n(Lo he quitado de pendientes ya que tiene hueco en el calendario.)")

    else:
        await update.message.reply_text(
            "No lo tengo claro. Puedes pedirme cosas como:\n"
            "• \"añade cena el viernes de 21 a 23 en naranja\"\n"
            "• \"apunta que tengo que comprar zapatillas\"\n"
            "• \"planifica lo de las zapatillas el jueves a las 18h\"\n"
            "• /hoy, /manana, /tareas"
        )


async def recordatorio_diario(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=list_pending_tasks())


def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("hoy", cmd_hoy))
    app.add_handler(CommandHandler("manana", cmd_manana))
    app.add_handler(CommandHandler("tareas", cmd_tareas))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_daily(
        recordatorio_diario,
        time=dt.time(hour=REMINDER_HOUR, minute=REMINDER_MINUTE, tzinfo=TIMEZONE),
    )

    print("Bot arrancado, esperando mensajes...")
    app.run_polling()


if __name__ == "__main__":
    main()
