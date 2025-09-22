# certtrack_mcp/server.py
import os
import csv
from datetime import datetime
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from datetime import datetime
from googleapiclient.errors import HttpError
from .google_sheets import read_range, append_rows


# SDK servidor MCP (está en mcp[cli])
from mcp.server.fastmcp import FastMCP

# Nombre del server (así lo verá el cliente)
mcp = FastMCP("CertTrack-MCP")

# Carga variables (luego usaremos GOOGLE_SHEETS_MASTER_ID, etc.)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

SHEET_ID = os.getenv("GOOGLE_SHEETS_MASTER_ID")
SHEET_TAB = os.getenv("GOOGLE_SHEETS_TAB", "Master")

CSV_PATH = os.path.join("certtrack_mcp", "data", "master.csv")

HEADERS = [
    "id","certificacion","nombre","fecha",
    "vigencia_meses","proveedor","tipo","costo","drive_file_id"
]
HEADER_RANGE = f"{SHEET_TAB}!A1:I1"
DATA_RANGE   = f"{SHEET_TAB}!A2:I"


DATA_CSV = os.path.join(os.path.dirname(__file__), "data", "master.csv")
os.makedirs(os.path.dirname(DATA_CSV), exist_ok=True)
# Si no existe un CSV maestro local, creamos uno de ejemplo
if not os.path.isfile(DATA_CSV):
    with open(DATA_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id","certificacion","nombre","fecha","vigencia_meses","proveedor","tipo","costo","drive_file_id"])
        w.writerow(["u1-net-001","Networking Básico","Laura López","2024-09-15","12","Cisco","Tecnica", "100",""])
        w.writerow(["u2-sec-002","Seguridad I","Luis Pérez","2025-01-10","6","CompTIA","Seguridad","200",""])

def _parse_date(yyyy_mm_dd: str) -> datetime:
    return datetime.strptime(yyyy_mm_dd, "%Y-%m-%d")

def _vence_el(fecha: str, vigencia_meses: int) -> str:
    d = _parse_date(fecha) + relativedelta(months=vigencia_meses)
    return d.strftime("%Y-%m-%d")

def _use_sheets() -> bool:
    # Sheets solo si hay ID y credenciales listas
    return bool(SHEET_ID) and os.path.exists(os.path.join("certtrack_mcp","token.json"))

def _ensure_csv_exists():
    os.makedirs(os.path.dirname(DATA_CSV), exist_ok=True)
    if not os.path.isfile(DATA_CSV):
        with open(DATA_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "id","certificacion","nombre","fecha","vigencia_meses","proveedor","tipo","costo","drive_file_id"
            ])

def _read_all_rows_csv():
    _ensure_csv_exists()
    with open(DATA_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return HEADERS, []
    return rows[0], rows[1:]

def _normalize_headers(hs):
    return [h.strip().lower() for h in hs]

def _as_row_from_payload(payload: dict, headers_lower: list[str]) -> list[str]:
    p = {k.lower(): v for k, v in payload.items()}
    return [str(p.get(h, "")) for h in headers_lower]

def _load_sheet_rows():
    headers = read_range(SHEET_ID, HEADER_RANGE)
    headers = headers[0] if headers else HEADERS
    data = read_range(SHEET_ID, DATA_RANGE)
    return headers, data

def _validate_date(fmtdate: str) -> None:
    datetime.strptime(fmtdate, "%Y-%m-%d")  # YYYY-MM-DD

@mcp.tool()
def health() -> dict:
    """
    Comprobación simple del servidor.
    """
    return {"ok": True, "server": "CertTrack-MCP"}

@mcp.tool()
def list_my_certs(spreadsheet_id: str, nombre: str) -> dict:
    """
    Lista certificaciones por 'nombre' (case-insensitive).
    Lee desde Google Sheets si hay SHEET_ID + token; si no, CSV local (fallback).
    """
    def _normalize_headers(hs):
        return [h.strip().lower() for h in hs]

    def _load_sheet_rows():
        headers = read_range(SHEET_ID, HEADER_RANGE)
        headers = headers[0] if headers else HEADERS
        data = read_range(SHEET_ID, DATA_RANGE)
        return headers, data

    try:
        if SHEET_ID and os.path.exists(os.path.join("certtrack_mcp","token.json")):
            # === Sheets ===
            headers, data = _load_sheet_rows()
            hnorm = _normalize_headers(headers)
            # mapeo robusto por nombre de columna
            needed = ["id","certificacion","nombre","fecha","vigencia_meses","proveedor","tipo","costo","drive_file_id"]
            idx = {col: hnorm.index(col) for col in needed if col in hnorm}

            out = []
            for r in data:
                if not r:
                    continue
                nm = r[idx["nombre"]] if "nombre" in idx and len(r) > idx["nombre"] else ""
                if nm.strip().lower() == nombre.strip().lower():
                    item = {}
                    for col in ["certificacion","fecha","vigencia_meses","proveedor","tipo","costo","drive_file_id"]:
                        if col in idx and len(r) > idx[col]:
                            item[col] = r[idx[col]]
                        else:
                            item[col] = ""
                    # tipados suaves
                    try:
                        item["vigencia_meses"] = int(item["vigencia_meses"] or 0)
                    except:
                        item["vigencia_meses"] = 0
                    try:
                        item["costo"] = float(item["costo"] or 0)
                    except:
                        item["costo"] = 0.0

                    # calcula vence_el localmente
                    try:
                        vence = _vence_el(item["fecha"] or "1970-01-01", item["vigencia_meses"])
                    except:
                        vence = ""
                    item["vence_el"] = vence
                    out.append(item)

            return {"ok": True, "source": "sheets", "count": len(out), "certs": out}

        else:
            # === CSV fallback ===
            if not os.path.isfile(DATA_CSV):
                return {"ok": True, "source": "csv", "count": 0, "certs": [], "note": "no master.csv found"}

            certs = []
            with open(DATA_CSV, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if (row.get("nombre","") or "").strip().lower() == nombre.strip().lower():
                        try:
                            vig_meses = int(row.get("vigencia_meses","0") or 0)
                        except:
                            vig_meses = 0
                        try:
                            costo = float(row.get("costo","0") or 0)
                        except:
                            costo = 0.0
                        try:
                            vence = _vence_el(row.get("fecha","1970-01-01"), vig_meses)
                        except:
                            vence = ""
                        certs.append({
                            "certificacion": row.get("certificacion",""),
                            "fecha": row.get("fecha",""),
                            "vigencia_meses": vig_meses,
                            "vence_el": vence,
                            "proveedor": row.get("proveedor",""),
                            "tipo": row.get("tipo",""),
                            "costo": costo,
                            "drive_file_id": row.get("drive_file_id","")
                        })
            return {"ok": True, "source": "csv", "count": len(certs), "certs": certs}

    except Exception as e:
        return {"ok": False, "error": f"{e}"}

@mcp.tool()
def sheets_append_cert(
    spreadsheet_id: str,  # se ignora por ahora; usamos GOOGLE_SHEETS_MASTER_ID del .env
    row: dict
) -> dict:
    """
    Inserta una certificación en Google Sheets (si hay SHEET_ID + token) o en CSV (fallback).
    Valida duplicado por 'id' y formato de fecha YYYY-MM-DD.
    Requiere: id, certificacion, nombre, fecha, vigencia_meses
    Opcional: proveedor, tipo, costo, drive_file_id
    """
    required = ["id", "certificacion", "nombre", "fecha", "vigencia_meses"]
    missing = [k for k in required if not str(row.get(k, "")).strip()]
    if missing:
        return {"status": f"error: faltan campos obligatorios: {', '.join(missing)}"}

    # valida fecha
    try:
        _validate_date(str(row["fecha"]))
    except Exception:
        return {"status": "error: fecha debe tener formato YYYY-MM-DD"}

    # normaliza tipos
    try:
        row["vigencia_meses"] = int(row.get("vigencia_meses", 0))
    except Exception:
        return {"status": "error: vigencia_meses debe ser entero"}

    try:
        row["costo"] = float(row.get("costo", 0) or 0)
    except Exception:
        return {"status": "error: costo debe ser numérico"}

    # completa llaves faltantes
    payload = {**{k: "" for k in HEADERS}, **{k: v for k, v in row.items()}}

    try:
        if _use_sheets():
            # === Google Sheets ===
            headers, data = _load_sheet_rows()
            hnorm = _normalize_headers(headers)

            # validar duplicado por 'id'
            if "id" in hnorm:
                id_idx = hnorm.index("id")
                existing = {r[id_idx] for r in data if r and len(r) > id_idx}
                if str(payload["id"]).strip() in existing:
                    return {"status": f"error: id duplicado: {payload['id']}"}
            else:
                # si la hoja no tiene encabezado, usamos HEADERS canónicos
                headers, hnorm = HEADERS, _normalize_headers(HEADERS)

            row_out = _as_row_from_payload(payload, hnorm)
            if len(row_out) < len(headers):
                row_out += [""] * (len(headers) - len(row_out))

            append_rows(SHEET_ID, f"{SHEET_TAB}!A1", [row_out])  # values.append (USER_ENTERED)
            return {"status": "ok", "store": "sheets"}

        else:
            # === CSV fallback ===
            headers, data = _read_all_rows_csv()
            hnorm = _normalize_headers(headers)
            if "id" in hnorm:
                id_idx = hnorm.index("id")
                existing = {r[id_idx] for r in data if r and len(r) > id_idx}
                if str(payload["id"]).strip() in existing:
                    return {"status": f"error: id duplicado: {payload['id']}"}
            else:
                headers, hnorm = HEADERS, _normalize_headers(HEADERS)

            row_out = _as_row_from_payload(payload, hnorm)
            if len(row_out) < len(headers):
                row_out += [""] * (len(headers) - len(row_out))

            _ensure_csv_exists()
            with open(DATA_CSV, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(row_out)

            # calcula número de fila (incluye encabezado)
            with open(DATA_CSV, "r", encoding="utf-8") as f:
                total_rows = sum(1 for _ in f)

            return {"status": "ok", "store": "csv", "inserted_at_row": total_rows}

    except HttpError as e:
        return {"status": f"error: Sheets API error: {e}"}
    except Exception as e:
        return {"status": f"error: {e}"}


@mcp.tool()
def alerts_schedule_due(spreadsheet_id: str, days_before: int = 30) -> dict:
    r"""
    Calcula certificaciones que vencen dentro de 'days_before' días (mock sobre CSV local).
    Retorna: { count, alerts: [ { email, certificacion, vence_el, sheet_row } ] }
    """
    if not os.path.isfile(DATA_CSV):
        return {"count": 0, "alerts": [], "note": "no master.csv found"}

    today = datetime.now().date()
    alerts = []
    with open(DATA_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # +1 por encabezado; DictReader empieza en datos
        row_index = 1
        for row in reader:
            row_index += 1
            try:
                vig_meses = int(row.get("vigencia_meses", "0") or 0)
            except:
                vig_meses = 0
            fecha = row.get("fecha", "1970-01-01")
            try:
                vence = _parse_date(fecha) + relativedelta(months=vig_meses)
                vence_date = vence.date()
            except Exception:
                continue

            dias_restantes = (vence_date - today).days
            if 0 <= dias_restantes <= int(days_before):
                # mock: construye email a partir del nombre
                nombre = (row.get("nombre", "") or "").strip()
                # muy simple: "nombre.apellido@example.com" si hay dos palabras
                parts = [p for p in nombre.split(" ") if p]
                if len(parts) >= 2:
                    email = f"{parts[0].lower()}.{parts[-1].lower()}@example.com"
                else:
                    email = f"{(nombre or 'user').lower().replace(' ', '.') }@example.com"

                alerts.append({
                    "email": email,
                    "certificacion": row.get("certificacion", ""),
                    "vence_el": vence.strftime("%Y-%m-%d"),
                    "sheet_row": row_index
                })

    return {"count": len(alerts), "alerts": alerts}

@mcp.tool()
def outlook_send_email(to: str, subject: str, html: str) -> dict:
    r"""
    Mock de envío de correo (Outlook/Microsoft Graph).
    Por ahora solo registra en consola/log y devuelve un message_id ficticio.
    """
    # Validaciones mínimas
    to_s = (to or "").strip()
    subj = (subject or "").strip()
    body = (html or "").strip()
    if not to_s or "@" not in to_s:
        return {"ok": False, "message_id": "", "error": "destinatario inválido"}
    if not subj:
        return {"ok": False, "message_id": "", "error": "subject vacío"}
    if not body:
        return {"ok": False, "message_id": "", "error": "html vacío"}

    # Simulación de envío
    import time, hashlib
    stamp = str(time.time())
    message_id = "mock-" + hashlib.sha1(f"{to_s}|{subj}|{stamp}".encode("utf-8")).hexdigest()[:16]

    # “Envío” (por ahora, solo imprime a consola)
    print("\n--- MOCK OUTLOOK SEND ---")
    print(f"To: {to_s}")
    print(f"Subject: {subj}")
    print(f"HTML (preview 200): {body[:200]}{'...' if len(body)>200 else ''}")
    print(f"Message-Id: {message_id}")
    print("-------------------------\n")

    return {"ok": True, "message_id": message_id}



if __name__ == "__main__":
    # Corre por STDIO (ideal para integrarlo con tu cliente)
    mcp.run()
