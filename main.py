import os
import json
import requests
import logging
from datetime import datetime
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import asyncio

load_dotenv()

# logging discreto
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL_ID = "claude-sonnet-4-20250514"

REMOTE_MCP_URL = os.getenv("REMOTE_MCP_URL", "").strip() or "https://hello-mcp-remote-203021435289.us-central1.run.app/rpc"

def jsonrpc_call(url: str, method: str, params: dict | None = None, req_id: int = 1) -> dict:
    payload = {"jsonrpc": "2.0", "method": method, "id": req_id}
    if params:
        payload["params"] = params
    r = requests.post(url, headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=15)
    r.raise_for_status()
    return r.json()

# helper para loggear llamadas MCP
async def log_mcp_call(session, tool_name: str, arguments: dict):
    import time
    t0 = time.time()
    logging.info(f"mcp-req | tool={tool_name} | args={arguments}")
    try:
        result = await session.call_tool(tool_name, arguments=arguments)
        dt = round((time.time() - t0) * 1000)
        # recorta para no inundar el log
        preview = str(result)
        if len(preview) > 500:
            preview = preview[:500] + "...[truncado]"
        logging.info(f"mcp-res | tool={tool_name} | ms={dt} | result={preview}")
        return result
    except Exception as e:
        dt = round((time.time() - t0) * 1000)
        logging.error(f"mcp-err | tool={tool_name} | ms={dt} | err={repr(e)}")
        raise

def call_llm(messages, max_tokens=400):
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Falta ANTHROPIC_API_KEY en .env")

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload = {"model": MODEL_ID, "max_tokens": max_tokens, "messages": messages}

    # registra tamaño del turno antes de llamar
    logging.info(f"req | turns={len(messages)}")

    resp = requests.post(ANTHROPIC_URL, headers=headers, data=json.dumps(payload), timeout=60)

    if resp.status_code >= 400:
        # registra error y lo propaga
        body = None
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        logging.error(f"res | status={resp.status_code} | body={body}")
        resp.raise_for_status()

    data = resp.json()
    parts = data.get("content", [])
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()

    # request id si existe (nombre neutro)
    req_id = resp.headers.get("x-request-id") or data.get("id")
    logging.info(f"res | status={resp.status_code} | id={req_id} | chars={len(text)}")

    return text or "[Respuesta vacía]"


def main():
    print("Chat listo. Escribe 'salir' para terminar.\n")
    print("Comandos disponibles:")
    print("  /setup-repo   → crea README y hace commit (demo FS+Git)")
    print("  /mis-certs Nombre Apellido → lista certificaciones (CertTrack-MCP)")
    print("  /add-cert ... → agrega certificación al maestro (CertTrack-MCP)")
    print("  /vencen días → muestra certificaciones que vencen en los próximos X días (default 30)")
    print("  /correo to=... subject=\"...\" html=\"...\" → envía correo (mock) vía CertTrack-MCP")
    print("  /health-remote → prueba el MCP remoto trivial (Cloud Run)")
    print("  /echo-remote msg → envía un mensaje al MCP remoto trivial (Cloud Run)")
    print("  demo          → demo Filesystem MCP (sandbox)")
    print("  gitdemo       → demo Git MCP (repo sandbox)\n")

    # Historial de conversación (memoria de sesión)
    history = []
    system_note = (
        "Eres un asistente técnico para un prototipo de consola. "
        "Responde de forma breve y directa, con pasos reproducibles."
    )
    # Nota: Para Anthropic simulamos 'system' como primer turno del asistente
    history.append({"role": "assistant", "content": [{"type": "text", "text": system_note}]})

    while True:
        user_text = input("Tú: ").strip()
        if not user_text:
            continue
        if user_text.lower() in {"salir", "exit", "quit"}:
            print("Fin de la sesión.")
            break

        # --- comandos especiales (MCP) ---
        if user_text.startswith("/setup-repo"):
            print("Ejecutando preparación de repo (Filesystem + Git)…")
            asyncio.run(git_demo())
            print("Listo. Escribe otra instrucción o 'salir'.\n")
            continue

        if user_text.lower().startswith("/mis-certs"):
            # Formato: /mis-certs Nombre Apellido
            partes = user_text.split(maxsplit=1)
            if len(partes) < 2:
                print("Uso: /mis-certs <Nombre y Apellido>\n")
            else:
                nombre = partes[1].strip()
                print(f"Buscando certificaciones de: {nombre} …")
                asyncio.run(certtrack_list(nombre))
            continue

        if user_text.lower().startswith("/add-cert"):
            # Uso:
            # /add-cert id=abc certificacion="Redes 1" nombre="Laura Lopez" fecha=2025-09-01 vigencia_meses=12 proveedor=Cisco tipo=Tecnica costo=100
            args_str = user_text[len("/add-cert"):].strip()
            row = parse_kv_args(args_str)
            requeridos = {"id","certificacion","nombre","fecha","vigencia_meses"}
            faltan = [r for r in requeridos if r not in row or not row[r]]
            if faltan:
                print("Faltan campos:", ", ".join(faltan))
                print('Ejemplo:\n  /add-cert id=u3-dev-003 certificacion="DevOps I" nombre="Laura Lopez" fecha=2025-10-01 vigencia_meses=12 proveedor=AWS tipo=Tecnica costo=150\n')
            else:
                print("Insertando certificación…")
                asyncio.run(certtrack_add_cert(row))
            continue

        if user_text.lower().startswith("/correo"):
            # Uso:
            # /correo to=alguien@example.com subject="Aviso de vencimiento"
            #         html="<p>Tu certificación X vence el 2025-10-01.</p>"
            args = parse_kv_args(user_text[len("/correo"):].strip())
            faltan = [k for k in ("to", "subject", "html") if k not in args or not args[k]]
            if faltan:
                print("Faltan campos:", ", ".join(faltan))
                print('Ejemplo:\n  /correo to=usuario@example.com subject="Aviso" html="<p>Texto del mensaje</p>"\n')
            else:
                asyncio.run(certtrack_send_email(args["to"], args["subject"], args["html"]))
            continue


        if user_text.lower().startswith("/vencen"):
            # Uso: /vencen 45   (por defecto 30 si no pones número)
            partes = user_text.split(maxsplit=1)
            days = 30
            if len(partes) == 2 and partes[1].strip().isdigit():
                days = int(partes[1].strip())
            print(f"Calculando alertas para los próximos {days} días…")
            asyncio.run(certtrack_alerts(days))
            continue


        if user_text == "demo":
            asyncio.run(fs_demo())
            continue

        if user_text == "gitdemo":
            asyncio.run(git_demo())
            continue

        elif user_text.startswith("/health-remote"):
            try:
                resp = jsonrpc_call(REMOTE_MCP_URL, "health", None, 1)
                print("\n=== Remote health ===")
                print(json.dumps(resp, indent=2, ensure_ascii=False))
                print("=====================\n")
            except Exception as e:
                print(f"[remote] error: {e}")
            continue

        elif user_text.startswith("/echo-remote"):
            # uso: /echo-remote tu mensaje aquí
            msg = user_text[len("/echo-remote"):].strip() or "hello"
            try:
                resp = jsonrpc_call(REMOTE_MCP_URL, "echo", {"msg": msg}, 2)
                print("\n=== Remote echo ===")
                print(json.dumps(resp, indent=2, ensure_ascii=False))
                print("===================\n")
            except Exception as e:
                print(f"[remote] error: {e}")
            continue

        # --- conversación normal ---
        logging.info(f"user: {user_text}")
        history.append({"role": "user", "content": [{"type": "text", "text": user_text}]})
        reply = call_llm(history, max_tokens=500)
        history.append({"role": "assistant", "content": [{"type": "text", "text": reply}]})
        logging.info(f"assistant: {reply}")
        print(f"Asistente: {reply}\n")


async def fs_demo():
    r"""
    Conecta a un servidor MCP de filesystem vía STDIO y crea un archivo de prueba.
    Requiere que ya esté corriendo:
      npx -y @modelcontextprotocol/server-filesystem "C:\\Users\\lourd\\mcp-sandbox"
    """
    fs_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", r"C:\Users\lourd\mcp-sandbox"],
    )

    async with stdio_client(fs_params) as (fs_read, fs_write):
        async with ClientSession(fs_read, fs_write) as fs_sess:
            await fs_sess.initialize()

            tools = await fs_sess.list_tools()
            print("Herramientas disponibles:", [t.name for t in tools.tools])

            # Crear archivo README.txt
            target = r"C:\Users\lourd\mcp-sandbox\README.txt"
            await log_mcp_call(fs_sess, "write_file", {
                "path": target,
                "content": "Proyecto inicializado.\n"
            })
            print("Archivo creado/escrito en:", target)

            # Listar directorio
            await log_mcp_call(fs_sess, "list_directory", {
                "path": r"C:\Users\lourd\mcp-sandbox"
            })

async def git_demo():
    r"""
    Flujo pedido por la consigna:
    - Crear README.md en el repo con Filesystem MCP
    - git add + git commit con Git MCP
    Requiere tener corriendo:
      1) Filesystem MCP server apuntando a C:\Users\lourd\mcp-sandbox
      2) Git MCP server sobre C:\Users\lourd\mcp-sandbox\demo-repo
    """
    # === 1) Crear README.md con Filesystem ===
    fs_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", r"C:\Users\lourd\mcp-sandbox"],
    )
    target = r"C:\Users\lourd\mcp-sandbox\demo-repo\README.md"

    async with stdio_client(fs_params) as (fs_read, fs_write):
        async with ClientSession(fs_read, fs_write) as fs_sess:
            await fs_sess.initialize()
            fs_tools = await fs_sess.list_tools()
            fs_tool_names = {t.name for t in fs_tools.tools}
            if "write_file" not in fs_tool_names:
                raise RuntimeError(f"No encontré herramienta 'write_file'. Tengo: {fs_tool_names}")

            await log_mcp_call(fs_sess, "write_file", {
                "path": target,
                "content": "# Proyecto Demo\nInicializado via MCP.\n"
            })
            print("Archivo README.md creado vía Filesystem MCP.")

    # === 2) git add + commit con Git MCP ===
    git_params = StdioServerParameters(
        command="python",
        args=["-m", "mcp_server_git", "--repository", r"C:\Users\lourd\mcp-sandbox\demo-repo"],
    )
    repo = r"C:\Users\lourd\mcp-sandbox\demo-repo"

    async with stdio_client(git_params) as (git_read, git_write):
        async with ClientSession(git_read, git_write) as git_sess:
            await git_sess.initialize()
            tools = await git_sess.list_tools()
            git_tool_names = {t.name for t in tools.tools}
            print("Herramientas Git disponibles:", sorted(git_tool_names))

            # git add README.md
            await log_mcp_call(git_sess, "git_add", {
                "repo_path": repo,
                "files": ["README.md"]
            })
            print("Archivo añadido al índice (staged).")

            # git commit
            await log_mcp_call(git_sess, "git_commit", {
                "repo_path": repo,
                "message": "Add README via MCP"
            })
            print("Commit realizado.")

            # git status final
            st = await log_mcp_call(git_sess, "git_status", {"repo_path": repo})
            print("Estado post-commit:", st)

async def mcp_repo_setup():
    r"""Crea README.md en demo-repo (filesystem) y hace git add+commit (git)."""
    # Filesystem → crear README.md
    fs_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", r"C:\Users\lourd\mcp-sandbox"],
    )
    target = r"C:\Users\lourd\mcp-sandbox\demo-repo\README.md"
    async with stdio_client(fs_params) as (fs_read, fs_write):
        async with ClientSession(fs_read, fs_write) as fs_sess:
            await fs_sess.initialize()
            await log_mcp_call(fs_sess, "write_file", {
                "path": target,
                "content": "# Proyecto Demo\nInicializado via MCP.\n"
            })

    # Git → add + commit
    git_params = StdioServerParameters(
        command="python",
        args=["-m", "mcp_server_git", "--repository", r"C:\Users\lourd\mcp-sandbox\demo-repo"],
    )
    repo = r"C:\Users\lourd\mcp-sandbox\demo-repo"
    async with stdio_client(git_params) as (git_read, git_write):
        async with ClientSession(git_read, git_write) as git_sess:
            await git_sess.initialize()
            await log_mcp_call(git_sess, "git_add", {"repo_path": repo, "files": ["README.md"]})
            await log_mcp_call(git_sess, "git_commit", {"repo_path": repo, "message": "Add README via MCP"})
            st = await log_mcp_call(git_sess, "git_status", {"repo_path": repo})
            print("Estado post-commit:", st)

async def certtrack_list(nombre: str):
    """
    Invoca el servidor CertTrack-MCP por STDIO y llama a la tool list_my_certs.
    Lanza su propio proceso: `python -m certtrack_mcp.server`.
    """
    params = StdioServerParameters(
        command="python",
        args=["-m", "certtrack_mcp.server"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Descubre herramientas (opcional, útil para depuración)
            tools = await session.list_tools()
            print("CertTrack tools:", [t.name for t in tools.tools])

            # Llama a list_my_certs (spreadsheet_id es simbólico por ahora, usa CSV local)
            res = await session.call_tool(
                "list_my_certs",
                arguments={"spreadsheet_id": "local", "nombre": nombre}
            )
            print("\n=== Resultado list_my_certs ===")
            print(res)
            print("================================\n")

def parse_kv_args(text: str) -> dict:
    """
    Parsea pares clave=valor separados por espacio.
    Soporta valores con espacios si van entre comillas.
    Ej:
      id=abc certificacion="Redes 1" nombre="Laura Lopez" fecha=2025-09-01 vigencia_meses=12 proveedor=Cisco tipo=Tecnica costo=100
    """
    import shlex
    parts = shlex.split(text)
    out = {}
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
    return out

async def certtrack_add_cert(row: dict):
    r"""
    Lanza CertTrack-MCP y llama a sheets_append_cert con los campos recibidos.
    Requeridos por el server: id, certificacion, nombre, fecha, vigencia_meses
    """
    params = StdioServerParameters(
        command="python",
        args=["-m", "certtrack_mcp.server"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await log_mcp_call(
                session, "sheets_append_cert",
                {"spreadsheet_id": "local", "row": row}
            )
            print("\n=== Resultado sheets_append_cert ===")
            print(res)
            print("====================================\n")

async def certtrack_alerts(days_before: int = 30):
    r"""Lanza CertTrack-MCP y llama alerts_schedule_due (mock CSV)."""
    params = StdioServerParameters(
        command="python",
        args=["-m", "certtrack_mcp.server"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await log_mcp_call(
                session, "alerts_schedule_due",
                {"spreadsheet_id": "local", "days_before": int(days_before)}
            )
            print("\n=== Alertas de vencimiento ===")
            print(res)
            print("================================\n")


async def certtrack_send_email(to: str, subject: str, html: str):
    """Invoca outlook_send_email del servidor CertTrack-MCP (mock)."""
    params = StdioServerParameters(
        command="python",
        args=["-m", "certtrack_mcp.server"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await log_mcp_call(
                session, "outlook_send_email",
                {"to": to, "subject": subject, "html": html}
            )
            print("\n=== Resultado outlook_send_email ===")
            print(res)
            print("====================================\n")



if __name__ == "__main__":
    main()
