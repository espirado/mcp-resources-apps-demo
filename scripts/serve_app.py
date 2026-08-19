#!/usr/bin/env python3
"""Local host: claims-desk MCP App + server-rendered capture pages for screenshots."""
from __future__ import annotations

import base64
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp_pdf_demo.server import call_tool, handle_message  # noqa: E402

APP_DIR = ROOT / "app"
PORT = 8765


def _pdf_preview_text(uri: str) -> str:
    """Best-effort extract of Latin-1 strings from our simple fixture PDFs."""
    pdf_resp = handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": uri}}
    )
    raw = base64.b64decode(pdf_resp["result"]["contents"][0]["blob"])
    # Pull printable runs from Tj operators: (text) Tj
    import re

    parts = re.findall(rb"\((.*?)\)\s*Tj", raw)
    lines = []
    for p in parts:
        try:
            lines.append(p.decode("latin-1"))
        except Exception:
            continue
    return "\n".join(lines) if lines else "(binary PDF — open in interactive app)"


def build_capture_html(payer: str = "acme-health", cpt: str = "27447") -> bytes:
    claim = json.loads(
        call_tool("review_claim_requirements", {"payer": payer, "cpt": cpt})["content"][0]["text"]
    )
    cite = (claim.get("citations") or [{}])[0]
    uri = cite.get("uri") or "demo://policies/acme-ortho-2026"
    title = cite.get("title") or uri
    preview = _pdf_preview_text(uri)
    # Also prove chunked path was used conceptually
    chunk = json.loads(
        call_tool("read_document_bytes", {"uri": uri, "offset": 0, "length": 256})[
            "content"
        ][0]["text"]
    )
    attachments = "".join(f"<li>{a}</li>" for a in claim.get("required_attachments") or [])
    citations = "".join(
        f"<li><strong>{c.get('title')}</strong><br/><code>{c.get('uri')}</code></li>"
        for c in claim.get("citations") or []
    )
    css = (APP_DIR / "app.css").read_text(encoding="utf-8")
    preview_html = "<br/>".join(
        line.replace("&", "&amp;").replace("<", "&lt;") for line in preview.splitlines()
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" />
<title>Claims Desk capture</title>
<style>{css}
body {{ background: #f3efe6; }}
.doc-sheet {{
  flex: 1; min-height: 22rem; overflow: auto; padding: 1.25rem 1.4rem;
  border: 1px solid var(--line); border-radius: 0.65rem; background: #fff;
  font-family: Georgia, "Iowan Old Style", serif; font-size: 0.92rem; line-height: 1.45;
  color: #1c1917; box-shadow: inset 0 0 0 1px rgba(0,0,0,0.02);
}}
.doc-sheet .doc-title {{ font-weight: 700; margin-bottom: 0.75rem; }}
.chunk-chip {{
  display: inline-block; margin-top: 0.4rem; padding: 0.2rem 0.5rem;
  border-radius: 999px; background: #ccfbf1; color: #0f766e; font-size: 0.72rem; font-weight: 700;
}}
</style></head><body>
<div class="shell">
  <header class="top">
    <div>
      <p class="eyebrow">MCP Apps demo · personal project</p>
      <h1>Claims desk</h1>
      <p class="lede">Payer policies live in PDFs. The agent returned structured requirements + citation URIs; the App fetched the source policy for the reviewer.</p>
    </div>
    <div class="flow-pill">PDF open for reviewer</div>
  </header>
  <section class="query panel">
    <h2>1. Claim scenario</h2>
    <p><strong>Payer:</strong> {claim.get('payer')} &nbsp;·&nbsp; <strong>CPT:</strong> {claim.get('cpt')}</p>
  </section>
  <div class="grid">
    <section class="panel">
      <h2>2. Agent / tool result</h2>
      <div class="status-row">
        <span class="badge">{claim.get('status')}</span>
        <span>{claim.get('procedure')}</span>
      </div>
      <dl class="meta">
        <dt>Timely filing</dt><dd>{claim.get('timely_filing_days')} days</dd>
        <dt>Prior auth</dt><dd>{claim.get('prior_auth')}</dd>
      </dl>
      <h3>Required attachments</h3>
      <ul>{attachments}</ul>
      <h3>Policy citations (URIs)</h3>
      <ul class="citations">{citations}</ul>
      <p class="note">{claim.get('reviewer_notes')}</p>
    </section>
    <section class="panel doc-panel">
      <h2>3. Source policy PDF</h2>
      <div class="doc-status">Open: {title}</div>
      <div class="chunk-chip">read_document_bytes · chunk 0 · {chunk.get('length')} / {chunk.get('totalSize')} bytes · hasMore={chunk.get('hasMore')}</div>
      <div class="doc-sheet">
        <div class="doc-title">{title}</div>
        <div>{preview_html}</div>
      </div>
    </section>
  </div>
  <footer>
    <span>MCP host bridge: POST /mcp</span>
    <span>model never received PDF bytes</span>
  </footer>
</div>
</body></html>"""
    return html.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return
        if path == "/capture/claim":
            qs = parse_qs(parsed.query)
            payer = (qs.get("payer") or ["acme-health"])[0]
            cpt = (qs.get("cpt") or ["27447"])[0]
            body = build_capture_html(payer, cpt)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/", "/index.html"):
            body = (APP_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/static/"):
            rel = path[len("/static/") :]
            file_path = APP_DIR / rel
            if not file_path.is_file():
                self.send_error(404)
                return
            data = file_path.read_bytes()
            ctype = "application/octet-stream"
            if rel.endswith(".css"):
                ctype = "text/css"
            elif rel.endswith(".js"):
                ctype = "text/javascript"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self._cors()
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/mcp":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            message = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "invalid json")
            return
        message.setdefault("id", 1)
        message.setdefault("jsonrpc", "2.0")
        resp = handle_message(message)
        if resp is None:
            self.send_response(204)
            self._cors()
            self.end_headers()
            return
        body = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Claims desk on http://127.0.0.1:{PORT}", flush=True)
    print("Interactive UI /  |  Screenshot capture /capture/claim  |  MCP POST /mcp", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
