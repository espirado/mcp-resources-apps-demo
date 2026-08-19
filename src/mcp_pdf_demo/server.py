"""Claims-desk MCP demo: structured policy tools + PDF resources + app-only chunks.

Personal AAIF Ambassador project (Andrew Espira / @espirado). Narrative: payer
policies and claim paperwork are scattered PDFs — agents get JSON handles;
MCP Apps fetch and render source documents for humans reviewing claims.
"""
from __future__ import annotations

import base64
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
POLICIES = json.loads((FIXTURES / "policies.json").read_text(encoding="utf-8"))

MAX_INLINE_BYTES = 2 * 1024 * 1024
DEFAULT_CHUNK = 64 * 1024

logger = logging.getLogger("mcp_claims_desk")

TOOLS: list[dict[str, Any]] = [
    {
        "name": "review_claim_requirements",
        "description": (
            "Given a claim scenario (payer + CPT/HCPCS), return structured "
            "billing requirements: timely filing, prior auth hints, required "
            "attachments, and citation resource URIs for the underlying payer "
            "policy PDFs. Does NOT return PDF bytes — use resources or "
            "read_document_bytes so the MCP App can render documents for the "
            "human claims reviewer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "payer": {
                    "type": "string",
                    "description": "Payer key, e.g. acme-health",
                },
                "cpt": {
                    "type": "string",
                    "description": "Procedure code, e.g. 27447",
                },
            },
            "required": ["payer", "cpt"],
        },
    },
    {
        "name": "list_policy_library",
        "description": "List demo payer policy documents available as MCP resources.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_document_bytes",
        "description": (
            "App-only: stream a policy PDF (or Apps shell) in base64 chunks. "
            "Keeps large claim paperwork out of model context."
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


def _policy_by_id(doc_id: str) -> dict[str, Any] | None:
    for doc in POLICIES["documents"]:
        if doc["id"] == doc_id:
            return doc
    return None


def _resolve_claim(payer: str, cpt: str) -> dict[str, Any]:
    payer_key = payer.strip().lower().replace(" ", "-")
    code = cpt.strip()
    for rule in POLICIES["claim_rules"]:
        if rule["payer"] == payer_key and code in rule["cpts"]:
            docs = [_policy_by_id(d) for d in rule["document_ids"]]
            return {
                "payer": rule["payer_display"],
                "cpt": code,
                "procedure": rule["procedure"],
                "status": rule["status"],
                "timely_filing_days": rule["timely_filing_days"],
                "prior_auth": rule["prior_auth"],
                "required_attachments": rule["required_attachments"],
                "reviewer_notes": rule["reviewer_notes"],
                "citations": [
                    {
                        "title": d["title"],
                        "uri": d["uri"],
                        "pages_hint": d.get("pages_hint"),
                    }
                    for d in docs
                    if d
                ],
                "agent_guidance": (
                    "Return these citation URIs to the claims App. Do not inline PDF "
                    "bytes into the model context — the reviewer will open the source "
                    "policy in the MCP App panel."
                ),
            }
    # Fallback illustrative response
    doc = POLICIES["documents"][0]
    return {
        "payer": payer,
        "cpt": code,
        "procedure": "Unknown / not in demo table",
        "status": "needs_manual_review",
        "timely_filing_days": None,
        "prior_auth": "unknown",
        "required_attachments": ["clinical_notes"],
        "reviewer_notes": (
            "No exact demo rule matched. Open the general payer manual and verify "
            "before submitting the claim."
        ),
        "citations": [{"title": doc["title"], "uri": doc["uri"], "pages_hint": doc.get("pages_hint")}],
        "agent_guidance": "Hand citation URIs to the App for human PDF review.",
    }


def list_resources() -> list[dict[str, Any]]:
    resources = [
        {
            "uri": "demo://apps/claims-desk",
            "name": "Claims desk (MCP Apps UI)",
            "description": "Interactive claims reviewer UI served by the demo host",
            "mimeType": "text/html",
        }
    ]
    for doc in POLICIES["documents"]:
        resources.append(
            {
                "uri": doc["uri"],
                "name": doc["title"],
                "description": doc["description"],
                "mimeType": "application/pdf",
            }
        )
    return resources


def _load_bytes(uri: str) -> tuple[bytes, str]:
    if uri == "demo://apps/claims-desk":
        html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        return html.encode("utf-8"), "text/html"
    for doc in POLICIES["documents"]:
        if doc["uri"] == uri:
            path = FIXTURES / doc["file"]
            return path.read_bytes(), "application/pdf"
    raise ValueError(f"Unknown resource URI: {uri}")


def read_resource(uri: str) -> dict[str, Any]:
    data, mime = _load_bytes(uri)
    if len(data) > MAX_INLINE_BYTES:
        raise ValueError("Document too large for resources/read; use read_document_bytes")
    entry: dict[str, Any] = {"uri": uri, "mimeType": mime}
    if mime.startswith("text/"):
        entry["text"] = data.decode("utf-8")
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
        lib = [
            {"id": d["id"], "title": d["title"], "uri": d["uri"], "payer": d["payer"]}
            for d in POLICIES["documents"]
        ]
        return {"content": [{"type": "text", "text": json.dumps({"documents": lib}, indent=2)}]}

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
                "serverInfo": {"name": "mcp-claims-desk", "version": "0.2.0"},
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
