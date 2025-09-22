# CertTrack-MCP

Console-based host application that integrates multiple **Model Context Protocol (MCP)** servers and a custom local MCP server (**CertTrack-MCP**) to manage professional certifications. The project demonstrates:

- Interoperability with **official MCP servers** (Filesystem & Git).
- A **custom MCP server** that reads/writes a certification master dataset.
- Migration from a CSV backend to **Google Sheets** using the Google Sheets API.
- Mocked email notifications (Outlook) and due-date alerts.

> The codebase is written in Python. The host is a simple console chatbot that connects to MCP servers and exposes a small set of commands to exercise each capability.

---

## Features

- **MCP Host (console chatbot)**
  - Maintains session context and prints MCP request/response logs.
  - Connects to multiple MCP servers at once.
- **Official MCP servers**
  - Filesystem MCP: create/list files for demo flows.
  - Git MCP: initialize a repo, add a README, and commit (demo).
- **Custom MCP server: CertTrack-MCP**
  - `list_my_certs`: list certifications by person.
  - `sheets_append_cert`: insert a new certification (validates duplicates and date format).
  - `alerts_schedule_due`: compute upcoming expirations within X days.
  - `outlook_send_email`: sends real email via Microsoft Graph (Outlook.com personal account with Device Code) or falls back to a mock provider if not configured.
- **Google Sheets integration**
  - The master dataset is stored in a Google Sheet (append/read with fallback to CSV).
  - OAuth token persisted locally (`token.json`) for subsequent runs.
- **CSV fallback**
  - If Sheets is not configured, the server keeps working against `certtrack_mcp/data/master.csv`.

---

## Requirements

- Python 3.10+ (recommended 3.11+)
- A Google account to enable **Google Sheets API**
- Local environment capable of running multiple terminals (host + one or more servers)
- Optional (only if using official MCP servers locally):
  - Node.js (for Filesystem MCP server)
  - Python for Git MCP server

---

## Installation

1. **Clone** the repository.
2. **Create a virtual environment** and **install dependencies**:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate         # Windows
   # source .venv/bin/activate    # Linux/Mac
   pip install -r requirements.txt

---

## Configuration

### 1) Environment variables (Sheets)

Create a file at **`certtrack_mcp/.env`** (the server loads this exact path) with:

```
GOOGLE_SHEETS_MASTER_ID=<your_sheet_id>
GOOGLE_SHEETS_TAB=Master
```

> `GOOGLE_SHEETS_MASTER_ID` is the part between `/d/` and `/edit` in your Google Sheet URL.  
> You can change the tab name; keep it consistent in both the sheet and this variable.

### 2) Google OAuth credentials

Place your **OAuth client** file at:

```
certtrack_mcp/google_credentials.json
```

This file must be **ignored by Git** (already covered in `.gitignore`).

### 3) Prepare the Google Sheet
- Create a new Google Sheet.
- Create a tab named **`Master`** (or change `GOOGLE_SHEETS_TAB` accordingly).
- Put the **headers in row 1 (A1:I1)** exactly as follows:

```
id, certificacion, nombre, fecha, vigencia_meses, proveedor, tipo, costo, drive_file_id
```

### 4) Generate the local OAuth token

Run once:

```bash
python certtrack_mcp/authorize_google.py
```

- Sign in and approve the requested scopes.
- The script writes **`certtrack_mcp/token.json`** (also ignored by Git).

> If you later change scopes, delete `certtrack_mcp/token.json` and re-run the script.

## Email (Microsoft Graph with Outlook.com personal account — Device Code)
 
This project can send real emails using Microsoft Graph if you sign in with a personal Outlook.com account.
If email isn’t configured or fails, the server falls back to the mock provider (no external delivery).
 
### Prerequisites
- You must have a working Outlook.com mailbox (personal Microsoft account).
- Register an Azure app that supports **personal Microsoft accounts** (see Setup).
- Grant the **delegated** permission: `Mail.Send` for Microsoft Graph.
 
### Setup (Azure App — Delegated OAuth / Device Code)
1. Go to Azure Portal → Microsoft Entra ID → App registrations → **New registration**.
2. Name: `CertTrack-Mailer-User`.
3. **Supported account types**: *Accounts in any organizational directory and personal Microsoft accounts (e.g., Skype, Xbox)*.
4. Leave Redirect URI empty (Device Code does not require redirect).
5. Register the app and copy the **Application (client) ID**.
6. App → **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated** → add **Mail.Send**.
7. (If shown) App → **Authentication** → enable **Allow public client flows** (Device Code).
 
### Local configuration
Create or edit `certtrack_mcp/.env`:

```
MS_AUTH_MODE=user
MS_CLIENT_ID=<your_app_client_id>
```
 
> In **user** mode you do **not** need `MS_TENANT_ID` or `MS_CLIENT_SECRET`.
 
### First run (one-time consent)
- Start the MCP server: `python certtrack_mcp/server.py`
- Start the host: `python main.py`
- Send a test email from the host:
  ```
  /correo to=you@outlook.com subject="Test Graph User" html="<p>Hello from Device Code</p>"
  ```
- The server prints a **Device Code** message with a URL and code. Open the URL, enter the code, sign in with your Outlook.com account, and accept **Mail.Send**.
- After success, the host should show `provider: "graph_user"`. Next runs reuse the cached token.
 
### Fallback behavior
- If configuration is missing or the Graph call fails, the tool returns `provider: "mock"` and logs a simulated send. This keeps the project functional even without Graph.

---

## Running

Open **two terminals**:

### Terminal A — Start the custom MCP server

```bash
python certtrack_mcp/server.py
```

This starts the **CertTrack-MCP** server and keeps it running (listening for requests).

### Terminal B — Start the console host (chatbot)

```bash
python main.py
```

From the host, you can issue commands (see **Usage**).  
> The host connects to your local MCP server and invokes tools over MCP.

> **Optional:** If you want to run the official demo servers, start them in additional terminals 
> and then use the corresponding demo commands in the host. They are not required for CertTrack.

---

## Usage (Host Commands)

### Certification tools (CertTrack-MCP)

- **Add a certification (writes to Google Sheets or CSV fallback):**
  ```
  /add-cert id=u4-dev-006 certificacion="DevOps III" nombre="Carlos Ramirez" fecha=2025-12-10 vigencia_meses=12 proveedor=Google tipo=Tecnica costo=185
  ```

- **List certifications by person:**
  ```
  /mis-certs Carlos Ramirez
  ```

- **Show upcoming expirations:**
  ```
  /vencen 60
  ```
- **Send email (mock for now):**
  ```
  /correo to=user@example.com subject="Reminder" html="<p>Hi!</p>"
  ```

### Official MCP demos (optional)

- **Filesystem demo:**
  ```
  demo
  ```
- **Git demo:**
  ```
  gitdemo
  ```
- **Setup flow combining FS+Git:**
  ```
  /setup-repo
  ```
## Data Backends

- **Primary:** Google Sheets  
  - Append: `spreadsheets.values.append` (user-entered mode).  
  - Read: `spreadsheets.values.get` using A1 ranges.  
- **Fallback:** CSV (`certtrack_mcp/data/master.csv`).

> The server selects backend at runtime: if `GOOGLE_SHEETS_MASTER_ID` **and** `certtrack_mcp/token.json` 
> are present, it uses Sheets; otherwise CSV.

---

## Troubleshooting

- **Command writes to `store: "csv"`**
  - Ensure `.env` has `GOOGLE_SHEETS_MASTER_ID` and `certtrack_mcp/token.json` exists.

- **403 access_denied on OAuth**
  - Add your account as **Test User** in the OAuth consent screen, or mark app as **Internal**.

- **Insufficient scopes**
  - Delete `certtrack_mcp/token.json` and re-run the auth script.

- **Duplicate id**
  - Each certification must have a unique `id`.

- **Date format**
  - Use `YYYY-MM-DD`.

---

## Security Notes

- Secrets and tokens are **not** committed:
  - `google_credentials.json` and `token.json` are git-ignored.
  - `.env` files are also ignored.

---

## Optional Next Steps

- Deploy CertTrack-MCP remotely (e.g., Cloud Run).
- Capture JSON-RPC traffic with Wireshark and document OSI/TCP-IP layers.

---

## Academic Note

This project is intended to demonstrate:
- Correct use of an existing protocol (MCP),
- Integration of local and remote servers,
- Practical, non-trivial tools with an external backend (Google Sheets),





