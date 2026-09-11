"""
Ejecuta esto UNA SOLA VEZ, en tu ordenador (no en Railway), para obtener
el refresh_token que luego pegarás como variable de entorno en Railway.

Antes de correrlo:
  1. Ve a https://console.cloud.google.com/ , crea un proyecto.
  2. Activa las APIs "Google Calendar API" y "Tasks API" (menú APIs y
     servicios > Biblioteca, una a una).
  3. En "APIs y servicios > Credenciales" crea una credencial OAuth de tipo
     "Aplicación de escritorio". Descarga el JSON y guárdalo en esta misma
     carpeta como client_secret.json.
  4. pip install google-auth-oauthlib

Al ejecutar `python get_refresh_token.py` se abrirá el navegador, inicias
sesión con la cuenta de Google de tu Calendar, aceptas permisos, y el
script imprime tu CLIENT_ID, CLIENT_SECRET y REFRESH_TOKEN por consola.
"""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0)

print("\n\nGuarda estos tres valores como variables de entorno en Railway:\n")
print(f"GOOGLE_CLIENT_ID={creds.client_id}")
print(f"GOOGLE_CLIENT_SECRET={creds.client_secret}")
print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
