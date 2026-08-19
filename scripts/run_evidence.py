#!/usr/bin/env python3
"""Exercise claims-desk MCP + write evidence/SUMMARY.json."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mcp_pdf_demo.server import handle_message  # noqa: E402

EVIDENCE = ROOT / "evidence"
EVIDENCE.mkdir(exist_ok=True)


def rpc(method: str, params: dict | None = None, msg_id: int = 1) -> dict:
    resp = handle_message({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})
    assert resp and "error" not in resp, resp
    (EVIDENCE / f"{method.replace('/', '-')}.json").write_text(json.dumps(resp, indent=2))
    return resp["result"]


def main() -> None:
    init = rpc("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "evidence", "version": "0.2"},
    })
    tools = [t["name"] for t in rpc("tools/list", {}, 2)["tools"]]
    assert "review_claim_requirements" in tools
    assert "read_document_bytes" in tools

    claim = json.loads(
        rpc(
            "tools/call",
            {
                "name": "review_claim_requirements",
                "arguments": {"payer": "acme-health", "cpt": "27447"},
            },
            3,
        )["content"][0]["text"]
    )
    assert claim["citations"] and claim["citations"][0]["uri"].startswith("demo://")
    uri = claim["citations"][0]["uri"]

    pdf = rpc("resources/read", {"uri": uri}, 4)["contents"][0]
    full = base64.b64decode(pdf["blob"])
    assert full.startswith(b"%PDF")

    assembled = bytearray()
    offset = 0
    chunks = 0
    while True:
        part = json.loads(
            rpc(
                "tools/call",
                {"name": "read_document_bytes", "arguments": {"uri": uri, "offset": offset, "length": 256}},
                100 + chunks,
            )["content"][0]["text"]
        )
        assembled.extend(base64.b64decode(part["bytes"]))
        chunks += 1
        if not part["hasMore"]:
            break
        offset = part["nextOffset"]
    assert bytes(assembled) == full

    summary = {
        "server": init["serverInfo"],
        "protocolVersion": init["protocolVersion"],
        "tools": tools,
        "claim_status": claim["status"],
        "citation_uri": uri,
        "pdf_bytes": len(full),
        "chunk_count": chunks,
        "policy_returns_uri_not_bytes": True,
        "story": "claims_desk_payer_policy_pdfs",
    }
    (EVIDENCE / "SUMMARY.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
