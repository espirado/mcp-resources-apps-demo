# Claims desk — MCP Apps (personal)

Personal MCP + MCP Apps demo by [Andrew Espira](https://github.com/espirado).

**What it does:** resolve Medicare claim documentation for a CPT against **live CMS sources** (LCD pages + Claims Processing Manual PDF). The MCP tool returns structured requirements + `doc://` URIs; the App streams the fetched document for the reviewer. Optional live enrichment via `RCI_API_KEY` → prior-auth / claim-intelligence APIs.

## Quick start

```bash
python3 scripts/run_evidence.py   # live CMS fetch + chunk integrity
python3 scripts/serve_app.py      # → http://127.0.0.1:8765
python3 scripts/capture_screenshots.py
```

Optional:

```bash
export RCI_API_KEY=...
export RCI_API_URL=https://api-dev.rcintell.com
```

## Layout

| Path | Purpose |
|------|---------|
| `src/mcp_pdf_demo/server.py` | MCP JSON-RPC (tools + resources + chunked reads) |
| `src/mcp_pdf_demo/live.py` | CMS fetch/cache + optional RCI HTTP |
| `fixtures/catalog.json` | CPT → live CMS URL map |
| `app/` | Claims desk UI |
| `docs/blog-draft.md` | Technical story + screenshots |
| `scripts/serve_app.py` | Local Apps host (`POST /mcp`) |

## Blog

[`docs/blog-draft.md`](docs/blog-draft.md)

## License

MIT
