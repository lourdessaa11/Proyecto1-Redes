# certtrack_mcp/graph_email_user.py
from __future__ import annotations
import os, json, time, hashlib
from typing import Dict, Any
import requests
import msal

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
# Scopes delegados para usuario personal (@outlook.com):
SCOPES = ["Mail.Send"]  # delegados, no ".default"

CACHE_PATH = os.path.join("certtrack_mcp", "graph_user_cache.json")

class GraphUserEmailError(Exception):
    pass

def _public_client():
    client_id = os.getenv("MS_CLIENT_ID", "").strip()
    if not client_id:
        raise GraphUserEmailError("MS_CLIENT_ID vacío. Registra la app como 'Public client' y coloca el client_id.")
    # 'consumers' funciona para cuentas personales (@outlook.com)
    authority = "https://login.microsoftonline.com/consumers"
    cache = msal.SerializableTokenCache()
    if os.path.exists(CACHE_PATH):
        cache.deserialize(open(CACHE_PATH, "r", encoding="utf-8").read())
    app = msal.PublicClientApplication(client_id=client_id, authority=authority, token_cache=cache)
    return app, cache

def _acquire_user_token() -> str:
    app, cache = _public_client()
    # 1) Intenta silent
    accounts = app.get_accounts()
    if accounts:
        res = app.acquire_token_silent(scopes=SCOPES, account=accounts[0])
        if res and "access_token" in res:
            return res["access_token"]

    # 2) Device Code Flow (interactivo en consola 1a vez)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise GraphUserEmailError("No se pudo iniciar device flow.")
    print("\n== Microsoft Device Code ==")
    print(flow["message"])  # incluye URL y código
    res = app.acquire_token_by_device_flow(flow)
    if "access_token" not in res:
        raise GraphUserEmailError(f"Error en device flow: {res.get('error_description')}")
    # persistir cache
    if isinstance(cache, msal.SerializableTokenCache):
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            f.write(cache.serialize())
    return res["access_token"]

def send_mail_via_graph_user(to: str, subject: str, html: str) -> Dict[str, Any]:
    token = _acquire_user_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": True
    }
    # Delegado: enviamos como el usuario autenticado -> /me/sendMail
    resp = requests.post(f"{GRAPH_BASE}/me/sendMail", headers=headers, data=json.dumps(payload), timeout=30)
    if resp.status_code not in (200, 202):
        raise GraphUserEmailError(f"Graph (delegado) fallo: {resp.status_code} {resp.text}")

    stamp = str(time.time())
    message_id = "graph-user-" + hashlib.sha1(f"{to}|{subject}|{stamp}".encode("utf-8")).hexdigest()[:16]
    return {"ok": True, "message_id": message_id, "provider": "graph_user"}
