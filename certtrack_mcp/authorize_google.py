from __future__ import print_function
import os.path
import google.auth.transport.requests
import google_auth_oauthlib.flow
import google.oauth2.credentials
from google.oauth2.credentials import Credentials

# Scopes que vamos a necesitar (Sheets y Drive)
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def main():
    creds = None
    # Si ya existe token.json, lo usamos
    if os.path.exists("certtrack_mcp/token.json"):
        creds = Credentials.from_authorized_user_file("certtrack_mcp/token.json", SCOPES)

    # Si no hay credenciales válidas, forzamos login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(google.auth.transport.requests.Request())
        else:
            flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                "certtrack_mcp/google_credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Guardamos el token para próximos usos
        with open("certtrack_mcp/token.json", "w") as token:
            token.write(creds.to_json())

    print("✅ Autorización completada, token.json generado.")

if __name__ == "__main__":
    main()
