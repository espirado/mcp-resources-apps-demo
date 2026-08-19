# Claims desk — MCP Apps demo (personal)

Personal MCP + MCP Apps demo by [Andrew Espira](https://github.com/espirado) for an [AAIF Ambassador](https://github.com/aaif/ambassadors) contribution.

**Problem:** medical billing is drowning in scattered payer policy PDFs.  
**Pattern:** MCP tools return claim requirements + citation URIs; an MCP App streams and shows the source PDF for the human reviewer — without putting document bytes in the model context.

## Quick start

```bash
# Protocol evidence (no browser)
python3 scripts/run_evidence.py

# Interactive claims desk UI
python3 scripts/serve_app.py
# → http://127.0.0.1:8765

# Screenshots for the blog
python3 scripts/capture_screenshots.py
```

## Blog draft

See [`docs/blog-draft.md`](docs/blog-draft.md) (includes screenshots).

## Layout

| Path | Purpose |
|------|---------|
| `src/mcp_pdf_demo/server.py` | MCP JSON-RPC (tools + resources + chunked reads) |
| `app/` | Claims desk MCP App UI |
| `fixtures/` | Synthetic payer policy PDFs |
| `docs/screenshots/` | Blog screenshots |
| `scripts/serve_app.py` | Local Apps host bridge (`POST /mcp`) |

## Honesty

Synthetic payers/PDFs for education only. Protocol `2024-11-05`. Apps host is a local spike.

## License

MIT
