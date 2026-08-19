# Claims paperwork is the hard part. MCP Apps can put the policy PDF next to the answer.

*Personal AAIF Ambassador contribution by [Andrew Espira](https://github.com/espirado).*

One of the hardest parts of medical billing isn’t “what’s the CPT?” — it’s everything around the code.

Payer medical policies, prior-auth grids, timely-filing rules, and documentation checklists live in **scattered PDFs**. A claims analyst (or an agent helping them) has to jump between portals, shared drives, and 40-page manuals just to decide whether a claim is ready to submit. The model can summarize a tool response. The human still needs to **see the source notice**.

That’s a perfect job for **MCP Apps**: keep structured claim guidance in tools, keep document bytes in Resources / app-only chunked reads, and render the policy PDF in a reviewer UI — without stuffing megabytes into the model context.

## The story this demo tells

```text
Claim scenario (payer + CPT)
        │
        ▼
MCP tool: review_claim_requirements
  → status, PA, timely filing, attachments
  → citation URIs only (no PDF bytes)
        │
        ▼
MCP App (claims desk)
  → read_document_bytes (chunked)
  → render source policy for the human
```

**Idle desk** — pick a payer and code, ask the MCP tool:

![Claims desk idle](screenshots/01-claims-desk-idle.png)

**After the tool call** — structured requirements on the left, source policy on the right:

![Claim result with policy document](screenshots/02-claim-result-and-pdf.png)

A second scenario (advanced imaging) shows the same pattern with a different payer manual:

![Imaging claim with policy document](screenshots/03-imaging-claim-pdf.png)

## Why not put the PDF in the tool result?

Because then you lose twice:

1. **Host limits** — large base64 payloads blow tool-response size caps.
2. **Context waste** — the model cannot “read” a scanned 30-page PA grid the way a reviewer can, and you still need a human to verify language before a claim goes out.

So the tool returns JSON a coding agent can reason over, plus `demo://policies/…` URIs. The App is where paperwork becomes visible.

## What the MCP server exposes

| Primitive | Name | Role |
|-----------|------|------|
| Tool | `review_claim_requirements` | Payer + CPT → PA / filing / attachments + citation URIs |
| Tool | `list_policy_library` | Catalog of policy PDFs |
| Tool (app-only) | `read_document_bytes` | Chunked base64 stream (`offset` / `hasMore`) |
| Resource | `demo://policies/…` | Payer policy PDFs |
| Resource | `demo://apps/claims-desk` | Apps UI shell |

`read_document_bytes` is marked app-only:

```json
"_meta": { "ui": { "visibility": ["app"] } }
```

Verified with `python3 scripts/run_evidence.py`: a real claim tool call returns URIs; the PDF reassembles across chunked reads byte-for-byte.

## Run the interactive App

```bash
python3 scripts/serve_app.py
# open http://127.0.0.1:8765
```

The browser talks to `POST /mcp` (a tiny host bridge standing in for an MCP Apps runtime). Choose **Acme Health / 27447**, click **Ask MCP tool**, then open a citation — the App streams the policy via `read_document_bytes` and shows it beside the structured result.

Stdio MCP server (for Cursor / Claude Desktop):

```json
{
  "mcpServers": {
    "claims-desk": {
      "command": "python3",
      "args": ["/absolute/path/to/mcp-resources-apps-demo/src/mcp_pdf_demo/server.py"]
    }
  }
}
```

## Honesty notes

- Protocol version: `2024-11-05`.
- Fixture payers/PDFs are **synthetic** — for teaching the pattern, not real coverage advice.
- The Apps host here is a local bridge + HTML UI (spike), not a full `@modelcontextprotocol/ext-apps` package.
- In production you’d add allowlisted fetches for real payer URLs, auth, and audit trails.

## Takeaways for MCP builders

- **Claims work is document work.** Agents that only return text still leave humans hunting PDFs.
- **Tools = decisions. Resources/Apps = paperwork.**
- **Citation URIs** are the handshake between model reasoning and human verification.
- **App-only chunking** is how you move real policy PDFs without breaking hosts or context windows.

If you’re an AAIF Ambassador on **Track B (MCP Apps)**, this is a weekend-sized pattern: one claims tool, a handful of policy resources, a desk UI that renders the PDF next to the answer.

## What’s next

Wire a real MCP Apps host bridge, swap fixtures for allowlisted public payer manuals, and write up a 2026-07-28 migration diary as a follow-on contribution.
