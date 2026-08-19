"""Claims desk MCP server — live CMS fetches + optional RCI API enrichment.

Personal project (Andrew Espira / @espirado). Agents get structured claim
guidance and document URIs; the MCP App streams real source documents.
"""
from __future__ import annotations

import base64
import json
import logging
import sys
from pathlib import Path
from typing import Any

from mcp_pdf_demo import live

ROOT = Path(__file__).resolve().parents[2]
MAX_INLINE_BYTES = 2 * 1024 * 1024
DEFAULT_CHUNK = 64 * 1024

logger = logging.getLogger("mcp_claims_desk")

TOOLS: list[dict[str, Any]] = [
    {
        "name": "review_claim_requirements",
        "description": (
            "Resolve claim documentation requirements for a payer + CPT. "
            "Fetches live CMS coverage/policy sources and optionally enriches "
            "from an RCI knowledge API when RCI_API_KEY is set. Returns "
            "structured requirements plus document URIs — never PDF/HTML bytes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "payer": {"type": "string", "description": "e.g. medicare"},
                "cpt": {"type": "string", "description": "e.g. 27447"},
            },
            "required": ["payer", "cpt"],
        },
    },
    {
        "name": "list_policy_library",
        "description": "List live CMS policy documents wired into this claims desk.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_document_bytes",
        "description": (
            "App-only: stream a fetched policy document in base64 chunks "
            "(offset/length/hasMore). Used by the claims App to render source docs."
        ),
        "annotations": {"readOnlyHint": True},
        "_meta": {"ui": {"visibility": ["app"]}},
        "inputSchema": {
            "type": "object",
            "properties": {
                "uri": {"type": "string"},
                "offset": {"type": "integer", "default": 0},
                "length": {"type": "integer", "default": 65536},
            },
            "required": ["uri"],
        },
    },
]


def _resolve_claim(payer: str, cpt: str) -> dict[str, Any]:
    scenario = live.find_scenario(payer, cpt)
    if not scenario:
        return {
            "payer": payer,
            "cpt": cpt,
            "status": "unsupported_scenario",
            "reviewer_notes": "No cataloged CMS scenario for this payer/CPT pair yet.",
            "citations": [],
        }

    # Fetch primary source live (cached after first hit)
    primary = scenario["sources"][0]
    data, mime, meta = live.fetch_source(primary)
    if mime.startswith("text/html"):
        text = live.html_to_text(data)
    elif mime.startswith("text/"):
        text = data.decode("utf-8", errors="replace")
    else:
        text = ""
    highlights = live.extract_lcd_highlights(text) if text else {
        "prior_auth": "see_source_document",
        "required_attachments": ["clinical_notes"],
        "source_excerpt": "",
    }

    citations = []
    for src in scenario["sources"]:
        # Warm cache for all cited docs
        _, _, smeta = live.fetch_source(src)
        citations.append(
            {
                "title": src["title"],
                "uri": src["uri"],
                "url": src["url"],
                "bytes": smeta.get("bytes"),
                "mimeType": smeta.get("mimeType"),
            }
        )

    result: dict[str, Any] = {
        "payer": scenario["payer_display"],
        "cpt": scenario["cpt"],
        "procedure": scenario["procedure"],
        "status": "review_against_source",
        "prior_auth": highlights["prior_auth"],
        "required_attachments": highlights["required_attachments"],
        "source_excerpt": highlights.get("source_excerpt") or None,
        "citations": citations,
        "data_plane": {
            "cms_fetch": True,
            "primary_source": primary["url"],
            "cached_bytes": meta.get("bytes"),
        },
        "reviewer_notes": (
            "Open the cited source in the App panel and confirm documentation "
            "language before coding/submitting the claim."
        ),
    }

    # Live RCI enrichment (medicare_ffs / uhc / …)
    rci_slug = scenario.get("rci_payer_slug") or "medicare_ffs"
    category = scenario.get("service_category") or "orthopedic_surgery"
    pa = live.rci_prior_auth(rci_slug, scenario["cpt"], category)
    intel = live.rci_claim_intelligence(rci_slug, scenario["cpt"], category)

    flat = live.flatten_rci(pa, intel)
    if flat:
        result.update(flat)
        result["data_plane"]["rci_enriched"] = True
        result["data_plane"]["rci_payer_slug"] = flat.get("rci_payer_slug") or rci_slug
        if flat.get("status") == "prior_auth_required":
            result["reviewer_notes"] = (
                f"RCI determination: prior auth required"
                + (f" ({flat.get('pa_matched_rule')})" if flat.get("pa_matched_rule") else "")
                + ". Confirm attachments, then open the cited source."
            )
        elif flat.get("status") == "no_prior_auth":
            result["reviewer_notes"] = (
                f"RCI determination: prior auth not required"
                + (f" — {flat.get('pa_matched_rule')}" if flat.get("pa_matched_rule") else "")
                + ". Still verify coverage language in the cited source."
            )

    if pa is not None and "error" not in (pa or {}):
        result["data_plane"]["rci_prior_auth"] = True
    if intel is not None and "error" not in (intel or {}) and "detail" not in (intel or {}):
        result["data_plane"]["rci_claim_intelligence"] = True

    return result


def list_resources() -> list[dict[str, Any]]:
    resources = [
        {
            "uri": "demo://apps/claims-desk",
            "name": "Claims desk (MCP Apps UI)",
            "description": "Interactive claims reviewer UI",
            "mimeType": "text/html",
        }
    ]
    for src in live.list_all_sources():
        resources.append(
            {
                "uri": src["uri"],
                "name": src["title"],
                "description": src["url"],
                "mimeType": "application/pdf" if src.get("kind") == "pdf" else "text/html",
            }
        )
    return resources


def _load_bytes(uri: str) -> tuple[bytes, str]:
    if uri == "demo://apps/claims-desk":
        html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        return html.encode("utf-8"), "text/html"
    src = live.source_by_uri(uri)
    if not src:
        raise ValueError(f"Unknown resource URI: {uri}")
    data, mime, _ = live.fetch_source(src)
    return data, mime


def read_resource(uri: str) -> dict[str, Any]:
    data, mime = _load_bytes(uri)
    if len(data) > MAX_INLINE_BYTES:
        raise ValueError("Document too large for resources/read; use read_document_bytes")
    entry: dict[str, Any] = {"uri": uri, "mimeType": mime}
    if mime.startswith("text/"):
        entry["text"] = data.decode("utf-8", errors="replace")
    else:
        entry["blob"] = base64.b64encode(data).decode("ascii")
    return {"contents": [entry]}


def chunk_bytes(data: bytes, offset: int, length: int) -> dict[str, Any]:
    if offset < 0:
        raise ValueError("offset must be >= 0")
    length = max(1, min(length, DEFAULT_CHUNK * 16))
    end = min(len(data), offset + length)
    piece = data[offset:end] if offset < len(data) else b""
    return {
        "bytes": base64.b64encode(piece).decode("ascii"),
        "offset": offset,
        "length": len(piece),
        "totalSize": len(data),
        "hasMore": end < len(data),
        "nextOffset": end if end < len(data) else None,
    }


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "review_claim_requirements":
        result = _resolve_claim(arguments.get("payer", ""), arguments.get("cpt", ""))
        return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}

    if name == "list_policy_library":
        docs = []
        for src in live.list_all_sources():
            _, _, meta = live.fetch_source(src)
            docs.append({**src, **{k: meta[k] for k in ("bytes", "mimeType") if k in meta}})
        return {"content": [{"type": "text", "text": json.dumps({"documents": docs}, indent=2)}]}

    if name == "read_document_bytes":
        uri = arguments["uri"]
        offset = int(arguments.get("offset") or 0)
        length = int(arguments.get("length") or DEFAULT_CHUNK)
        data, mime = _load_bytes(uri)
        payload = {**chunk_bytes(data, offset, length), "mimeType": mime, "uri": uri}
        return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}

    return {
        "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
        "isError": True,
    }


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method", "")
    msg_id = message.get("id")
    params = message.get("params") or {}

    if method == "notifications/initialized":
        return None

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"listChanged": False, "subscribe": False},
                },
                "serverInfo": {"name": "mcp-claims-desk", "version": "0.3.0"},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            result = call_tool(params.get("name", ""), params.get("arguments") or {})
        elif method == "resources/list":
            result = {"resources": list_resources()}
        elif method == "resources/read":
            result = read_resource(params.get("uri", ""))
        elif method == "resources/templates/list":
            result = {"resourceTemplates": []}
        elif method == "ping":
            result = {}
        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
    except Exception as exc:
        logger.exception("handler error")
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32000, "message": str(exc)},
        }

    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle_message(message)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
