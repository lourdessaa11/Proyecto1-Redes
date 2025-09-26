# main.py — LLM router sobre MCP (Groq gemma2-9b-it) —
import os
import json
import re
import requests
import logging
from datetime import datetime
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import asyncio

load_dotenv()

# =========================
# Logging
# =========================
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# =========================
# LLM (Groq - OpenAI compatible)
# =========================
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "gemma2-9b-it"

# =========================
# Rutas base (normalización FS/Git)
# =========================
SANDBOX_ROOT = os.getenv("SANDBOX_ROOT", r"C:\Users\lourd\mcp-sandbox")
REPO_PATH_DEFAULT = os.getenv("REPO_PATH", os.path.join(SANDBOX_ROOT, "demo-repo"))

# =========================
# Remoto JSON-RPC (HTTP)
# =========================
REMOTE_MCP_URL = os.getenv("REMOTE_MCP_URL", "").strip() or "https://hello-mcp-remote-203021435289.us-central1.run.app/rpc"

def jsonrpc_call(url: str, method: str, params: dict | None = None, req_id: int = 1) -> dict:
    payload = {"jsonrpc": "2.0", "method": method, "id": req_id}
    if params:
        payload["params"] = params
    r = requests.post(url, headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=15)
    r.raise_for_status()
    return r.json()

# =========================
# MCP logging helper
# =========================
async def log_mcp_call(session, tool_name: str, arguments: dict):
    import time
    t0 = time.time()
    logging.info(f"mcp-req | tool={tool_name} | args={arguments}")
    try:
        result = await session.call_tool(tool_name, arguments=arguments)
        dt = round((time.time() - t0) * 1000)
        preview = str(result)
        if len(preview) > 800:
            preview = preview[:800] + "...[truncado]"
        logging.info(f"mcp-res | tool={tool_name} | ms={dt} | result={preview}")
        return result
    except Exception as e:
        dt = round((time.time() - t0) * 1000)
        logging.error(f"mcp-err | tool={tool_name} | ms={dt} | err={repr(e)}")
        raise

# =========================
# Llamada al LLM (Groq)
# =========================
def call_llm(messages, max_tokens=400):
    """
    Llama al endpoint OpenAI-compatible de Groq con el modelo gemma2-9b-it.
    Espera 'messages' como lista de dicts con 'role' en {'system','user','assistant'}
    y 'content' como lista de bloques [{'type':'text','text': '...'}] o str.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("Falta GROQ_API_KEY en .env")

    def _flatten_content(blocks):
        if isinstance(blocks, str):
            return blocks
        if isinstance(blocks, list):
            return "".join(
                b.get("text", "")
                for b in blocks
                if isinstance(b, dict) and b.get("type") == "text"
            )
        return ""

    openai_messages = []
    for m in messages:
        role = m.get("role")
        content = _flatten_content(m.get("content", ""))
        if role in ("system", "user", "assistant") and content.strip():
            openai_messages.append({"role": role, "content": content})

    payload = {
        "model": GROQ_MODEL,
        "messages": openai_messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    logging.info(f"req | turns={len(openai_messages)}")
    resp = requests.post(GROQ_URL, headers=headers, data=json.dumps(payload), timeout=60)

    if resp.status_code >= 400:
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        logging.error(f"res | status={resp.status_code} | body={body}")
        resp.raise_for_status()

    data = resp.json()
    text = (data.get("choices", [{}])[0].get("message", {}).get("content", "")) or ""
    logging.info(f"res | status={resp.status_code} | chars={len(text)}")
    return text.strip() or "[Respuesta vacía]"

# =========================
# Router prompt
# =========================
ROUTER_SYSTEM = (
    "Eres un asistente técnico para un prototipo de consola. "
    "Decide si respondes directamente o si debes invocar herramientas.\n\n"
    "Herramientas disponibles (no menciones que son herramientas):\n"
    "1) list_my_certs(nombre:str)\n"
    "2) add_cert(row:{id, certificacion, nombre, fecha, vigencia_meses, proveedor?, tipo?, costo?})\n"
    "3) upcoming_expirations(days_before:int)\n"
    "4) send_email(to:str, subject:str, html:str)\n"
    "5) fs_write(path:str, content:str)\n"
    "6) git_add_commit(repo_path:str, files:list[str], message:str)\n"
    "7) remote_health()\n"
    "8) remote_echo(msg:str)\n\n"
    "Salida obligatoria:\n"
    "- Si es UNA sola acción de herramienta, devuelve SOLO:\n"
    "{ \"action\": \"call_tool\", \"tool\": \"<nombre>\", \"args\": { ... } }\n"
    "- Si son VARIAS acciones, devuelve SOLO:\n"
    "{ \"action\": \"batch\", \"actions\": [ {\"tool\":\"<nombre>\",\"args\":{...}}, ... ] }\n"
    "- Si no se requiere herramienta, devuelve SOLO:\n"
    "{ \"action\": \"respond\", \"text\": \"<respuesta breve y clara>\" }\n"
    "No uses backticks ni bloques de código. Devuelve JSON puro y nada más."
)

# =========================
# Parser robusto de intención
# =========================
def call_llm_for_intent(history_text_turns: list[dict], user_text: str) -> dict:
    """
    Pide al LLM una intención estructurada (JSON puro) y la parsea.
    """
    messages = []
    messages.append({"role": "system", "content": [{"type": "text", "text": ROUTER_SYSTEM}]})
    for turn in history_text_turns[-8:]:
        messages.append(turn)
    messages.append({"role": "user", "content": [{"type": "text", "text": user_text}]})

    raw = call_llm(messages, max_tokens=450)

    def _strip_code_fences(s: str) -> str:
        s = s.strip()
        if s.startswith("```"):
            s = re.sub(r"^```(?:json)?\s*", "", s)
            s = re.sub(r"\s*```$", "", s)
        return s.strip()

    def _extract_json(s: str) -> dict | None:
        s = _strip_code_fences(s)
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j != -1 and j > i:
            candidate = s[i:j+1]
            try:
                return json.loads(candidate)
            except Exception:
                pass
        try:
            return json.loads(s)
        except Exception:
            return None

    intent = _extract_json(raw)
    if isinstance(intent, dict):
        return intent

    logging.error(f"router-parse-error | raw={raw[:500]}")
    return {"action": "respond", "text": raw.strip() or "No tengo una respuesta en este momento."}

# =========================
# Herramientas
# =========================
async def fs_write(path: str, content: str):
    import os as _os
    # normaliza ruta
    if not _os.path.isabs(path):
        path = _os.path.join(SANDBOX_ROOT, path)
    fs_params = StdioServerParameters(
        command="npx",
        args=["-y", "--silent", "@modelcontextprotocol/server-filesystem", SANDBOX_ROOT],
    )
    async with stdio_client(fs_params) as (r, w):
        async with ClientSession(r, w) as sess:
            await sess.initialize()
            return await log_mcp_call(sess, "write_file", {"path": path, "content": content})

async def git_add_commit(repo_path: str, files: list[str], message: str):
    import os as _os
    repo_path = repo_path or REPO_PATH_DEFAULT
    if not _os.path.isabs(repo_path):
        repo_path = _os.path.join(SANDBOX_ROOT, repo_path)

    # normaliza files relativos al repo
    norm_files = []
    for f in (files or []):
        if _os.path.isabs(f):
            try:
                rel = _os.path.relpath(f, repo_path)
                norm_files.append(rel if not rel.startswith("..") else f)
            except Exception:
                norm_files.append(f)
        else:
            norm_files.append(f)

    git_params = StdioServerParameters(
        command="python",
        args=["-m", "mcp_server_git", "--repository", repo_path],
    )
    async with stdio_client(git_params) as (r, w):
        async with ClientSession(r, w) as sess:
            await sess.initialize()
            await log_mcp_call(sess, "git_add", {"repo_path": repo_path, "files": norm_files})
            res = await log_mcp_call(sess, "git_commit", {"repo_path": repo_path, "message": message})
            status = await log_mcp_call(sess, "git_status", {"repo_path": repo_path})
            return {"commit": res, "status": status}

async def certtrack_list(nombre: str):
    params = StdioServerParameters(command="python", args=["-m", "certtrack_mcp.server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            logging.info(f"certtrack-tools: {[t.name for t in tools.tools]}")
            res = await log_mcp_call(
                session, "list_my_certs",
                {"spreadsheet_id": "local", "nombre": nombre}
            )
            return res

async def certtrack_add_cert(row: dict):
    params = StdioServerParameters(command="python", args=["-m", "certtrack_mcp.server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await log_mcp_call(session, "sheets_append_cert", {"spreadsheet_id": "local", "row": row})
            return res

async def certtrack_alerts(days_before: int = 30):
    params = StdioServerParameters(command="python", args=["-m", "certtrack_mcp.server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await log_mcp_call(session, "alerts_schedule_due", {
                "spreadsheet_id": "local", "days_before": int(days_before)
            })
            return res

async def certtrack_send_email(to: str, subject: str, html: str):
    params = StdioServerParameters(command="python", args=["-m", "certtrack_mcp.server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await log_mcp_call(session, "outlook_send_email", {"to": to, "subject": subject, "html": html})
            return res

def remote_health():
    return jsonrpc_call(REMOTE_MCP_URL, "health", None, 1)

def remote_echo(msg: str):
    return jsonrpc_call(REMOTE_MCP_URL, "echo", {"msg": msg}, 2)

# =========================
# Helpers de extracción y resumen
# =========================
def _extract_first_json_from_string(s: str):
    import json as _json
    if not isinstance(s, str):
        return None
    first = s.find("{")
    last = s.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidate = s[first:last+1]
        try:
            return _json.loads(candidate)
        except Exception:
            pass
    try:
        return _json.loads(s.strip())
    except Exception:
        return None

def _extract_json_from_mcp_result(obj) -> dict | list | None:
    """
    Intenta extraer un JSON de resultados MCP (incluye casos TextContent con string JSON dentro).
    """
    if isinstance(obj, (dict, list)):
        return obj
    # intenta atributos de SDK (lista de bloques con .text)
    try:
        content = getattr(obj, "content", None)
        if isinstance(content, list):
            for item in content:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    j = _extract_first_json_from_string(text)
                    if j is not None:
                        return j
    except Exception:
        pass
    # fallback: a string
    try:
        s = str(obj)
        j = _extract_first_json_from_string(s)
        if j is not None:
            return j
    except Exception:
        pass
    return None

def summarize_tool_result(tool: str, result: object) -> str:
    data = _extract_json_from_mcp_result(result)
    if data is None:
        try:
            return str(result)
        except Exception:
            return "Operación completada."

    try:
        # CertTrack
        if tool == "add_cert":
            status = data.get("status") or data.get("ok")
            store = data.get("store") or data.get("source")
            return f"Certificación registrada ({'ok' if status else 'error'}; backend: {store or 'desconocido'})."

        if tool == "list_my_certs":
            count = data.get("count", 0)
            certs = data.get("certs", [])
            if count == 0:
                return "No encontré certificaciones para esa persona."
            lines = [
                f"- {c.get('certificacion')} · fecha {c.get('fecha')} · vence {c.get('vence_el')}"
                for c in certs
            ]
            return "Certificaciones:\n" + "\n".join(lines)

        if tool == "upcoming_expirations":
            count = data.get("count", 0)
            alerts = data.get("alerts", [])
            if count == 0:
                return "No hay certificaciones que venzan en el rango indicado."
            lines = [
                f"- {a.get('nombre')}: {a.get('certificacion')} vence el {a.get('vence_el')}"
                for a in alerts
            ]
            return "Próximos vencimientos:\n" + "\n".join(lines)

        if tool == "send_email":
            prov = data.get("provider") or data.get("mode") or "desconocido"
            ok = data.get("ok", True)
            return f"Correo {'enviado' if ok else 'no enviado'} (proveedor: {prov})."

        # Filesystem / Git
        if tool == "fs_write":
            return "Archivo escrito correctamente."
        if tool == "git_add_commit":
            return "Commit realizado y repositorio actualizado."

        # Remoto
        if tool == "remote_health":
            return "Servicio remoto operativo."
        if tool == "remote_echo":
            if isinstance(data, dict) and isinstance(data.get("result"), dict):
                echo = data["result"].get("echo")
                return f"Remoto respondió: {echo}" if echo else json.dumps(data, ensure_ascii=False)
            return json.dumps(data, ensure_ascii=False)

        # genérico
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return "Operación completada."

# =========================
# Bucle principal
# =========================
def main():
    print("Chat listo. Escribe 'salir' para terminar.\n")

    # Memoria de conversación para el router
    convo = []
    system_note = (
        "Eres un asistente técnico para un prototipo de consola. "
        "Responde de forma breve y directa, con pasos reproducibles cuando proceda."
    )
    convo.append({"role": "system", "content": [{"type": "text", "text": system_note}]})

    while True:
        user_text = input("Tú: ").strip()
        if not user_text:
            continue
        if user_text.lower() in {"salir", "exit", "quit"}:
            print("Fin de la sesión.")
            break

        logging.info(f"user: {user_text}")
        convo.append({"role": "user", "content": [{"type": "text", "text": user_text}]})

        # 1) LLM decide acción
        intent = call_llm_for_intent(convo, user_text)
        logging.info(f"router-intent: {intent}")

        # 2) Despacho
        try:
            action = intent.get("action")

            if action == "respond":
                text = intent.get("text", "").strip() or "Ok."
                convo.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
                print(f"Asistente: {text}\n")
                continue

            if action == "batch":
                actions = intent.get("actions") or []
                for step in actions:
                    tool = step.get("tool")
                    args = step.get("args") or {}
                    out = _dispatch_tool(tool, args)
                    summary = summarize_tool_result(tool, out) if out is not None else f"{tool}: acción omitida."
                    print(f"Asistente: {summary}\n")
                # Puedes agregar summaries al historial si lo deseas
                continue

            if action == "call_tool":
                tool = intent.get("tool")
                args = intent.get("args") or {}
                out = _dispatch_tool(tool, args)
                summary = summarize_tool_result(tool, out) if out is not None else f"{tool}: acción omitida."
                convo.append({"role": "assistant", "content": [{"type": "text", "text": summary}]})
                print(f"Asistente: {summary}\n")
                continue

            # Fallback
            text = intent.get("text") or "Entendido."
            convo.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
            print(f"Asistente: {text}\n")

        except Exception as e:
            logging.exception("dispatch-error")
            msg = f"Ocurrió un error al procesar la solicitud: {e}"
            convo.append({"role": "assistant", "content": [{"type": "text", "text": msg}]})
            print(f"Asistente: {msg}\n")

def _dispatch_tool(tool: str, args: dict):
    if tool == "list_my_certs":
        return asyncio.run(certtrack_list(nombre=args.get("nombre", "")))

    if tool == "add_cert":
        return asyncio.run(certtrack_add_cert(row=args.get("row", {})))

    if tool == "upcoming_expirations":
        return asyncio.run(certtrack_alerts(days_before=int(args.get("days_before", 30))))

    if tool == "send_email":
        return asyncio.run(certtrack_send_email(
            to=args.get("to", ""), subject=args.get("subject", ""), html=args.get("html", "")
        ))

    if tool == "fs_write":
        return asyncio.run(fs_write(path=args.get("path", ""), content=args.get("content", "")))

    if tool == "git_add_commit":
        return asyncio.run(git_add_commit(
            repo_path=args.get("repo_path", ""),
            files=args.get("files", []) or [],
            message=args.get("message", "Update via MCP")
        ))

    if tool == "remote_health":
        return remote_health()

    if tool == "remote_echo":
        return remote_echo(args.get("msg", ""))

    return None

# =========================
# Demos heredadas
# =========================
async def fs_demo():
    fs_params = StdioServerParameters(
        command="npx",
        args=["-y", "--silent", "@modelcontextprotocol/server-filesystem", SANDBOX_ROOT],
    )
    async with stdio_client(fs_params) as (fs_read, fs_write):
        async with ClientSession(fs_read, fs_write) as fs_sess:
            await fs_sess.initialize()
            await log_mcp_call(fs_sess, "write_file", {
                "path": os.path.join(SANDBOX_ROOT, "README.txt"),
                "content": "Proyecto inicializado.\n"
            })
            await log_mcp_call(fs_sess, "list_directory", {"path": SANDBOX_ROOT})

async def git_demo():
    fs_params = StdioServerParameters(
        command="npx",
        args=["-y", "--silent", "@modelcontextprotocol/server-filesystem", SANDBOX_ROOT],
    )
    target = os.path.join(SANDBOX_ROOT, "demo-repo", "README.md")
    async with stdio_client(fs_params) as (fs_read, fs_write):
        async with ClientSession(fs_read, fs_write) as fs_sess:
            await fs_sess.initialize()
            await log_mcp_call(fs_sess, "write_file", {
                "path": target,
                "content": "# Proyecto Demo\nInicializado via MCP.\n"
            })
    git_params = StdioServerParameters(
        command="python",
        args=["-m", "mcp_server_git", "--repository", os.path.join(SANDBOX_ROOT, "demo-repo")],
    )
    repo = os.path.join(SANDBOX_ROOT, "demo-repo")
    async with stdio_client(git_params) as (git_read, git_write):
        async with ClientSession(git_read, git_write) as git_sess:
            await git_sess.initialize()
            await log_mcp_call(git_sess, "git_add", {"repo_path": repo, "files": ["README.md"]})
            await log_mcp_call(git_sess, "git_commit", {"repo_path": repo, "message": "Add README via MCP"})
            await log_mcp_call(git_sess, "git_status", {"repo_path": repo})

if __name__ == "__main__":
    main()
