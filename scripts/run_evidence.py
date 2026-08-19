#!/usr/bin/env python3
"""Exercise live CMS fetch path + write evidence/SUMMARY.json."""
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
    (EVIDENCE / f"{method.replace('/', '-')}.json").write_text(json.dumps(resp, indent=2)[:20000])
    return resp["result"]


def main() -> None:
    init = rpc("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "evidence", "version": "0.3"},
    })
    claim = json.loads(
        rpc(
            "tools/call",
            {"name": "review_claim_requirements", "arguments": {"payer": "medicare", "cpt": "70553"}},
            2,
        )["content"][0]["text"]
    )
    assert claim["data_plane"]["cms_fetch"] is True
    assert claim["citations"]
    uri = claim["citations"][0]["uri"]
    assert uri.startswith("doc://")
    assert claim.get("prior_auth") == "auth_not_required"
    assert claim.get("pa_required") is False
    assert claim.get("timely_filing_days") == 365
    assert claim.get("data_plane", {}).get("rci_enriched") is True

    dme = json.loads(
        rpc(
            "tools/call",
            {"name": "review_claim_requirements", "arguments": {"payer": "medicare", "cpt": "E0601"}},
            3,
        )["content"][0]["text"]
    )
    assert dme.get("prior_auth") == "auth_required"
    assert dme.get("pa_required") is True
    assert "Certificate of Medical Necessity" in (dme.get("required_attachments") or [])

    doc = rpc("resources/read", {"uri": uri}, 4)["contents"][0]
    if "text" in doc:
        body = doc["text"].encode()
    else:
        body = base64.b64decode(doc["blob"])
    assert len(body) > 1000

    assembled = bytearray()
    offset = 0
    chunks = 0
    while True:
        part = json.loads(
            rpc(
                "tools/call",
                {"name": "read_document_bytes", "arguments": {"uri": uri, "offset": offset, "length": 4096}},
                100 + chunks,
            )["content"][0]["text"]
        )
        assembled.extend(base64.b64decode(part["bytes"]))
        chunks += 1
        if not part["hasMore"]:
            break
        offset = part["nextOffset"]
    assert bytes(assembled) == body

    summary = {
        "server": init["serverInfo"],
        "claim_status": claim["status"],
        "prior_auth": claim.get("prior_auth"),
        "pa_required": claim.get("pa_required"),
        "pa_confidence": claim.get("pa_confidence"),
        "timely_filing_days": claim.get("timely_filing_days"),
        "dme_prior_auth": dme.get("prior_auth"),
        "primary_source": claim["data_plane"]["primary_source"],
        "citation_uri": uri,
        "fetched_bytes": len(body),
        "chunk_count": chunks,
        "cms_live_fetch": True,
        "rci_enriched": bool(claim.get("data_plane", {}).get("rci_enriched")),
        "rci_payer_slug": claim.get("data_plane", {}).get("rci_payer_slug"),
        "returns_uri_not_bytes": True,
    }
    (EVIDENCE / "SUMMARY.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
