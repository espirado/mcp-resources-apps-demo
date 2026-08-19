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


def _doc_preview(uri: str) -> tuple[str, str]:
    """Return (mime, preview_html_or_text) from resources/read."""
    pdf_resp = handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": uri}}
    )
    content = pdf_resp["result"]["contents"][0]
    mime = content.get("mimeType") or ""
    if "text" in content:
        return mime, content["text"][:120000]
    raw = base64.b64decode(content["blob"])
    if raw[:4] == b"%PDF":
        import re

        parts = re.findall(rb"\((.*?)\)\s*Tj", raw)
        lines = [p.decode("latin-1", errors="replace") for p in parts]
        return mime, "\n".join(lines)[:8000] or f"(PDF {len(raw)} bytes — open in interactive app)"
    return mime, raw.decode("utf-8", errors="replace")[:8000]


def build_capture_html(payer: str = "medicare", cpt: str = "27447") -> bytes:
    claim = json.loads(
        call_tool("review_claim_requirements", {"payer": payer, "cpt": cpt})["content"][0]["text"]
    )
    cite = (claim.get("citations") or [{}])[0]
    uri = cite.get("uri") or ""
    title = cite.get("title") or uri
    source_url = cite.get("url") or claim.get("data_plane", {}).get("primary_source") or ""
    mime, preview = _doc_preview(uri) if uri else ("text/plain", "")
    chunk = json.loads(
        call_tool("read_document_bytes", {"uri": uri, "offset": 0, "length": 256})[
            "content"
        ][0]["text"]
    ) if uri else {}
    attachments = "".join(f"<li>{a}</li>" for a in claim.get("required_attachments") or [])
    citations = "".join(
        f"<li><strong>{c.get('title')}</strong><br/><code>{c.get('uri')}</code>"
        f"<br/><a href=\"{c.get('url')}\">{c.get('url')}</a></li>"
        for c in claim.get("citations") or []
    )
    css = (APP_DIR / "app.css").read_text(encoding="utf-8")
    if (mime or "").startswith("text/html"):
        import base64 as _b64

        data_url = "data:text/html;base64," + _b64.b64encode(preview.encode("utf-8")).decode("ascii")
        preview_html = (
            f'<iframe title="source" src="{data_url}" '
            f'style="width:100%;min-height:22rem;border:0;background:#fff"></iframe>'
        )
    else:
        preview_html = (
            preview.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br/>")
        )
    excerpt = (claim.get("source_excerpt") or "")[:500]
    data_plane = claim.get("data_plane") or {}
    cached_bytes = data_plane.get("cached_bytes")
    filing = (
        f"{claim.get('timely_filing_days')} days"
        if claim.get("timely_filing_days") is not None
        else "—"
    )
    pa_req = (
        "yes" if claim.get("pa_required") is True else "no" if claim.get("pa_required") is False else "—"
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
  color: #1c1917;
}}
.doc-sheet .doc-title {{ font-weight: 700; margin-bottom: 0.75rem; }}
.chunk-chip {{
  display: inline-block; margin: 0.4rem 0 0.6rem; padding: 0.2rem 0.5rem;
  border-radius: 999px; background: #ccfbf1; color: #0f766e; font-size: 0.72rem; font-weight: 700;
}}
</style></head><body>
<div class="shell">
  <header class="top">
    <div>
      <p class="eyebrow">MCP Apps · live CMS sources</p>
      <h1>Claims desk</h1>
      <p class="lede">Live fetch from CMS coverage pages / manuals. Tool returns structured requirements + URIs; the App streams the source for the reviewer.</p>
    </div>
    <div class="flow-pill">Source open for reviewer</div>
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
        <dt>Prior auth</dt><dd>{claim.get('prior_auth')}</dd>
        <dt>PA required</dt><dd>{pa_req}</dd>
        <dt>PA confidence</dt><dd>{claim.get('pa_confidence')}</dd>
        <dt>Matched rule</dt><dd>{claim.get('pa_matched_rule') or '—'}</dd>
        <dt>Timely filing</dt><dd>{filing}</dd>
        <dt>CMS source</dt><dd style="word-break:break-all">{source_url}</dd>
        <dt>Fetched</dt><dd>{cached_bytes} bytes</dd>
      </dl>
      <h3>Required attachments</h3>
      <ul>{attachments}</ul>
      <h3>Citations</h3>
      <ul class="citations">{citations}</ul>
      <p class="note">{claim.get('reviewer_notes')}</p>
      <p class="note"><em>Excerpt:</em> {excerpt.replace('<','&lt;')}</p>
    </section>
    <section class="panel doc-panel">
      <h2>3. Source document</h2>
      <div class="doc-status">Open: {title} ({mime})</div>
      <div class="chunk-chip">read_document_bytes · {chunk.get('length')} / {chunk.get('totalSize')} bytes · hasMore={chunk.get('hasMore')}</div>
      <div class="doc-sheet">
        <div class="doc-title">{title}</div>
        <div>{preview_html}</div>
      </div>
    </section>
  </div>
  <footer>
    <span>MCP host bridge: POST /mcp</span>
    <span>live CMS fetch — model never received document bytes</span>
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
