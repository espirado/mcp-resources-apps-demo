# The claim isn’t hard. The paperwork is.
### How MCP Apps put live CMS policy next to the answer — without feeding it to the model

*Personal write-up by [Andrew Espira](https://github.com/espirado). Demo: [mcp-resources-apps-demo](https://github.com/espirado/mcp-resources-apps-demo).*

---

It’s Monday morning in a hospital billing office.

On the screen: a knee replacement ready to drop. CPT **27447**. Payer: Medicare. Somewhere in the Medicare Coverage Database there is an LCD that says whether the chart supports medical necessity — conservative care notes, imaging evidence, the whole checklist reviewers argue about when a claim comes back.

That hunt is the job.

Coding the line item takes minutes. **Finding and rereading the source policy** takes the rest of the morning. Miss the documentation language and the claim comes back. Miss timely filing and it may never get paid. This is one of the hardest parts of medical billing: not the code tables, but the **scattered manuals, LCDs, and PA rules** humans still have to verify with their own eyes.

Agents are good at structured answers. They are bad roommates for 40-page PDFs and CMS HTML. Stuff a policy into a tool result as base64 and you hit host size limits, burn the context window, and still leave a reviewer squinting at encoded bytes.

**MCP Apps** are how you split that work cleanly:

- the **agent / tool** returns *what to do* (PA determination, attachments, filing window) plus **citation URIs**
- the **App** fetches and **renders the live source** for the human
- the **model never has to eat the paperwork**

I built a personal **claims desk** to make that concrete — wired to live `cms.gov` fetches and optional RCI prior-auth / claim-intelligence enrichment.

## Scene 1 — The desk before the answer

The App opens on an empty claims desk. You pick a payer and a CPT, then call a single MCP tool. The copy on the page is the design intent out loud: JSON for the agent path, documents for the reviewer path.

![Claims desk idle — choose payer and CPT, then ask the MCP tool](screenshots/01-claims-desk-idle.png)

This is the moment most “AI for RCM” demos skip. They return a paragraph of advice and hope the analyst trusts it. Real claims work doesn’t work that way. Advice without the policy page open is how denials happen.

## Scene 2 — A real claim: TKA against LCD L33618

Scenario: **Medicare Fee-For-Service**, CPT **27447** (total knee arthroplasty).

The MCP tool `review_claim_requirements` comes back with structured guidance — prior-auth determination from live RCI (`medicare_ffs`), timely filing **365 days**, attachments pulled from the LCD coverage language, and **`doc://cms/...` URIs** that map to real CMS URLs.

Then the App — not the model — opens the source via app-only `read_document_bytes` (chunked). On the right you see the **live LCD coverage body**: indications, limitations, medical necessity — not the MCD page chrome, license modals, or email forms.

![Structured claim requirements beside live LCD L33618](screenshots/02-medicare-tka-lcd.png)

That split is the whole product idea:

| Left panel (tool / agent) | Right panel (MCP App) |
|---------------------------|------------------------|
| Machine-readable requirements | Human-readable source of truth |
| Safe to reason over | Safe to verify against |
| No document bytes | LCD / PDF streamed in chunks |

The teal chip on the document pane (`read_document_bytes · … · hasMore=true`) is intentional. It shows the App pulling paperwork through the protocol instead of pretending the model “read” the file.

## Scene 3 — Same CPT family, different paperwork

Swap to an MRI (**70553**). On Medicare FFS the category rule matches: **prior auth not required**, confidence **0.75**, filing still **365 days**. The App opens the Claims Processing Manual Chapter 12 PDF — actual pages, streamed beside the answer.

![Medicare MRI — no PA, claims manual open](screenshots/03-medicare-mri-no-pa.png)

Flip the same MRI to **UnitedHealthcare**. Same CPT, different payer rules: **prior auth required**, clinical notes + order, **90-day** filing window. The choreography does not change — only the determination and the attachments do.

![UHC MRI — PA required](screenshots/05-uhc-mri-pa-required.png)

One more beat: **CPAP / E0601** on Medicare. Now the DME category fires — **auth required**, Certificate of Medical Necessity + physician order, ten-day turnaround. Still the same desk.

![Medicare DME — PA required](screenshots/04-medicare-dme-pa-required.png)

Billing teams don’t have one PDF problem. They have **hundreds**, per payer, per year, with effective dates that move. The protocol pattern has to survive that volume: always return handles, always render on demand, always keep bytes out of the prompt.

## What MCP is doing under the desk

```text
Analyst picks payer + CPT
        │
        ▼
tools/call  review_claim_requirements
        │     HTTPS GET cms.gov (LCD coverage body / manual PDF)
        │     optional RCI prior-auth + claim-intelligence
        │     returns JSON + doc:// URIs
        │     (no document bytes)
        ▼
App UI (claims desk)
        │
        ├─ show status / PA / attachments / filing
        │
        └─ tools/call  read_document_bytes   ← app-only
                 chunked base64
                 └─ render LCD HTML or PDF pages beside the answer
```

Resources still matter: `resources/list` and `resources/read` expose the policy library and the Apps shell. For large manuals, the App prefers **chunked** `read_document_bytes` marked with:

```json
"_meta": { "ui": { "visibility": ["app"] } }
```

so hosts know those payloads are for the UI, not the assistant transcript.

I verified the path with a small evidence runner: the claim tool returns URIs only; reassembling chunks matches `resources/read` byte-for-byte against the live fetch.

## Why an App — not just another tool

- **Tools** alone give you a chatbot with opinions about PA.
- **Resources** alone give you a file browser.
- **Apps** give you a **workstation**: answer + paperwork in one place, with the human still in the loop.

If you build agents for any document-heavy domain — insurance, compliance, procurement, clinical admin — the same story applies. The model proposes. The App shows the exhibit. The person decides.

## Try it

```bash
git clone https://github.com/espirado/mcp-resources-apps-demo
cd mcp-resources-apps-demo
python3 scripts/serve_app.py
# open http://127.0.0.1:8765

# optional live enrichment
# export RCI_API_KEY=...
# export RCI_API_URL=https://api-dev.rcintell.com
```

Pick **Medicare / 27447**, click **Ask MCP tool**, open the LCD citation. Watch the coverage body land next to the structured result. Then try **70553**, **E0601**, and UHC — same desk, different paperwork.

## What I want other builders to steal

1. **Don’t put PDFs in tool results.** Return citation URIs.
2. **Put paperwork in the App.** That’s what reviewers actually need.
3. **Chunk large documents** with an app-only tool when hosts have size limits.
4. **Fetch real sources.** Synthetic fixtures teach the pattern; live LCDs and manuals prove it.
5. **Tell a domain story.** MCP Apps land harder when the UI solves a job people already hate — like hunting payer policy before a claim goes out.

The claim was never the hard part. The paperwork was. MCP Apps are how we stop asking the model to swallow it.
