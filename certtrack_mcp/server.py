# certtrack_mcp/server.py
import os
import csv
from datetime import datetime
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

# SDK servidor MCP (está en mcp[cli])
from mcp.server.fastmcp import FastMCP

# Nombre del server (así lo verá el cliente)
mcp = FastMCP("CertTrack-MCP")

# Carga variables (luego usaremos GOOGLE_SHEETS_MASTER_ID, etc.)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

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

@mcp.tool()
def health() -> dict:
    """
    Comprobación simple del servidor.
    """
    return {"ok": True, "server": "CertTrack-MCP"}

@mcp.tool()
def list_my_certs(spreadsheet_id: str, nombre: str) -> dict:
    """
    Lista certificaciones por nombre desde un CSV local 'data/master.csv'.
    Más adelante, este backend se conectará a Google Sheets usando spreadsheet_id.
    """
    certs = []
    if not os.path.isfile(DATA_CSV):
        return {"count": 0, "certs": [], "note": "no master.csv found"}

    with open(DATA_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("nombre","").strip().lower() == nombre.strip().lower():
                try:
                    vig_meses = int(row.get("vigencia_meses","0"))
                except:
                    vig_meses = 0
                vence = _vence_el(row.get("fecha","1970-01-01"), vig_meses)
                certs.append({
                    "certificacion": row.get("certificacion",""),
                    "fecha": row.get("fecha",""),
                    "vigencia_meses": vig_meses,
                    "vence_el": vence,
                    "proveedor": row.get("proveedor",""),
                    "tipo": row.get("tipo",""),
                    "costo": float(row.get("costo","0") or 0),
                    "drive_file_id": row.get("drive_file_id","")
                })

    return {"count": len(certs), "certs": certs}

@mcp.tool()
def sheets_append_cert(
    spreadsheet_id: str,
    row: dict
) -> dict:
    """
    Inserta una certificación en el CSV local (mock de Google Sheets).
    Requiere: id, certificacion, nombre, fecha (YYYY-MM-DD), vigencia_meses.
    Opcional: proveedor, tipo, costo, drive_file_id.
    Retorna: status, inserted_at_row (número de fila incluyendo encabezado).
    """
    required = ["id", "certificacion", "nombre", "fecha", "vigencia_meses"]
    missing = [k for k in required if not str(row.get(k, "")).strip()]
    if missing:
        return {"status": f"error: faltan campos obligatorios: {', '.join(missing)}"}

    # valida fecha
    try:
        _ = _parse_date(row["fecha"])
    except Exception:
        return {"status": "error: fecha debe tener formato YYYY-MM-DD"}

    # normaliza tipos
    try:
        vig_meses = int(row.get("vigencia_meses", 0))
    except Exception:
        return {"status": "error: vigencia_meses debe ser entero"}

    try:
        costo_val = float(row.get("costo", 0) or 0)
    except Exception:
        return {"status": "error: costo debe ser numérico"}

    # asegura que exista el CSV
    os.makedirs(os.path.dirname(DATA_CSV), exist_ok=True)
    if not os.path.isfile(DATA_CSV):
        with open(DATA_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id","certificacion","nombre","fecha","vigencia_meses","proveedor","tipo","costo","drive_file_id"])

    # verifica duplicado por id
    with open(DATA_CSV, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for existing in r:
            if existing.get("id", "").strip() == str(row["id"]).strip():
                return {"status": f"error: id duplicado: {row['id']}"}

    # inserta al final
    with open(DATA_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            row.get("id","").strip(),
            row.get("certificacion","").strip(),
            row.get("nombre","").strip(),
            row.get("fecha","").strip(),
            str(vig_meses),
            row.get("proveedor","").strip(),
            row.get("tipo","").strip(),
            str(costo_val),
            row.get("drive_file_id","").strip(),
        ])

    # calcula número de fila (incluye encabezado)
    with open(DATA_CSV, "r", encoding="utf-8") as f:
        total_rows = sum(1 for _ in f)

    return {"status": "ok", "inserted_at_row": total_rows}

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


if __name__ == "__main__":
    # Corre por STDIO (ideal para integrarlo con tu cliente)
    mcp.run()
