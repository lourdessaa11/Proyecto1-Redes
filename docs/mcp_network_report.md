# MCP Networking Report — Local HTTP (JSON-RPC visible)

## Scenario
- Server: Hello-MCP-Remote (local Docker) listening on 127.0.0.1:8080
- Client: curl (host machine)

## Capture
- File: captures/jsonrpc_local_http.pcapng
- Filter: tcp.port == 8080

## Findings
1) **TCP handshake**  
   - SYN / SYN-ACK / ACK (3-way handshake).
2) **HTTP request**  
   - `POST /rpc HTTP/1.1`  
   - Header `Content-Type: application/json`  
   - Body JSON-RPC:  
     ```json
     { "jsonrpc": "2.0", "method": "echo", "params": {"msg": "hola local"}, "id": 2 }
     ```
3) **HTTP response**  
   - `200 OK`, body JSON-RPC:  
     ```json
     { "jsonrpc": "2.0", "result": {"echo": "hola local"}, "id": 2 }
     ```

## OSI / TCP-IP mapping
- Capa 7 (Aplicación): JSON-RPC 2.0 sobre HTTP.
- Capa 4 (Transporte): TCP (puerto 8080).
- Capa 3 (Red): IPv4 (127.0.0.1 → 127.0.0.1).
- Capa 2 (Enlace): Loopback virtual (host local).

## Notes
- Esta captura muestra el **contenido JSON-RPC en claro**. 
- Para la nube (HTTPS), el cuerpo estará cifrado; veremos TLS y tamaños, no el JSON.

---

# MCP Networking Report — Remote HTTPS (Cloud Run)

## Scenario
- Server: Hello-MCP-Remote deployed in Cloud Run
- Client: PowerShell (Invoke-RestMethod)

## Capture
- File: captures/jsonrpc_remote_https.pcapng
- Filter: tcp.port == 443

## Findings
1) **TCP handshake** (3-way handshake).
2) **TLS handshake**: ClientHello, ServerHello, Certificate, Key Exchange.
3) **Encrypted traffic**: TLS Application Data frames (JSON-RPC not visible).

## OSI / TCP-IP mapping
- Capa 7 (Aplicación): JSON-RPC 2.0 sobre HTTP → cifrado con TLS.
- Capa 4 (Transporte): TCP (puerto 443).
- Capa 3 (Red): IPv4 (cliente público → servidor Cloud Run).
- Capa 2 (Enlace): Interfaz física (Wi-Fi/Ethernet).

## Notes
- A diferencia de la captura local (HTTP en claro), aquí los cuerpos JSON-RPC están protegidos por TLS.
