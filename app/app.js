const MCP = "/mcp";
let rpcId = 1;

async function mcp(method, params = {}) {
  const res = await fetch(MCP, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: rpcId++, method, params }),
  });
  const body = await res.json();
  if (body.error) throw new Error(body.error.message || JSON.stringify(body.error));
  return body.result;
}

async function callTool(name, args) {
  const result = await mcp("tools/call", { name, arguments: args });
  const text = result.content?.[0]?.text || "{}";
  return JSON.parse(text);
}

/** App-only bridge: pull entire document via chunked read_document_bytes */
async function readDocumentBytes(uri, onProgress) {
  const chunks = [];
  let offset = 0;
  let total = null;
  let mimeType = "application/pdf";
  while (true) {
    const part = await callTool("read_document_bytes", {
      uri,
      offset,
      length: 16 * 1024,
    });
    mimeType = part.mimeType || mimeType;
    total = part.totalSize;
    const bin = atob(part.bytes);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    chunks.push(arr);
    if (onProgress) onProgress(offset + part.length, total);
    if (!part.hasMore) break;
    offset = part.nextOffset;
  }
  const size = chunks.reduce((n, c) => n + c.length, 0);
  const out = new Uint8Array(size);
  let o = 0;
  for (const c of chunks) {
    out.set(c, o);
    o += c.length;
  }
  return new Blob([out], { type: mimeType });
}

window.__mcpReadDocumentBytes = readDocumentBytes;

function setFlow(text) {
  document.getElementById("flowState").textContent = text;
}

function renderResult(data) {
  document.getElementById("emptyResult").classList.add("hidden");
  document.getElementById("resultCard").classList.remove("hidden");
  const badge = document.getElementById("statusBadge");
  badge.textContent = data.status;
  badge.classList.toggle("ok", data.status === "no_prior_auth" || data.status === "allowed");
  badge.classList.toggle("warn", data.status === "prior_auth_required");
  document.getElementById("procedureLabel").textContent = data.procedure || "";

  const meta = document.getElementById("metaList");
  meta.innerHTML = "";
  const rows = [
    ["Payer", data.payer],
    ["CPT", data.cpt],
    ["Prior auth", data.prior_auth],
    ["PA required", data.pa_required === true ? "yes" : data.pa_required === false ? "no" : "—"],
    ["PA confidence", data.pa_confidence != null ? data.pa_confidence : "—"],
    ["Matched rule", data.pa_matched_rule || "—"],
    ["Timely filing", data.timely_filing_days != null ? `${data.timely_filing_days} days` : "—"],
    ["Appeal L1", data.first_appeal_deadline_days != null ? `${data.first_appeal_deadline_days} days` : "—"],
    ["CMS source", data.data_plane?.primary_source || "—"],
    ["Fetched bytes", data.data_plane?.cached_bytes ?? "—"],
  ];
  for (const [k, v] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = v ?? "—";
    meta.append(dt, dd);
  }

  const att = document.getElementById("attachments");
  att.innerHTML = "";
  for (const a of data.required_attachments || []) {
    const li = document.createElement("li");
    li.textContent = a;
    att.append(li);
  }

  const cites = document.getElementById("citations");
  cites.innerHTML = "";
  for (const c of data.citations || []) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "linkish";
    btn.textContent = c.title;
    btn.addEventListener("click", () => openPdf(c.uri, c.title));
    li.append(btn);
    if (c.pages_hint) {
      const span = document.createElement("span");
      span.textContent = ` — ${c.pages_hint}`;
      span.style.color = "#57534e";
      span.style.fontSize = "0.85em";
      li.append(span);
    }
    cites.append(li);
  }

  document.getElementById("reviewerNotes").textContent = data.reviewer_notes || "";
}

async function openPdf(uri, title) {
  const status = document.getElementById("docStatus");
  const chunkMeta = document.getElementById("chunkMeta");
  const frame = document.getElementById("pdfFrame");
  setFlow("Fetching live source…");
  status.textContent = `Streaming ${title || uri}…`;
  try {
    const blob = await readDocumentBytes(uri, (loaded, total) => {
      chunkMeta.textContent = `${loaded.toLocaleString()} / ${total.toLocaleString()} bytes`;
      status.textContent = `Streaming ${title || uri}… ${Math.round((100 * loaded) / total)}%`;
    });
    const mime = blob.type || "";
    if (mime.startsWith("text/html")) {
      const html = await blob.text();
      frame.removeAttribute("src");
      frame.srcdoc = html;
    } else if (mime.startsWith("text/")) {
      const text = await blob.text();
      frame.removeAttribute("src");
      frame.srcdoc = `<pre style="white-space:pre-wrap;font:14px/1.45 Georgia,serif;padding:1rem;margin:0;background:#fff;color:#1c1917">${
        text.replace(/&/g,"&amp;").replace(/</g,"&lt;").slice(0, 50000)
      }</pre>`;
    } else if (mime.includes("pdf") || mime === "application/octet-stream") {
      // Headless / iframe PDF plugins are unreliable — show rasterized pages.
      const preview = await fetch(`/preview/pdf?uri=${encodeURIComponent(uri)}&pages=2`).then((r) => {
        if (!r.ok) throw new Error(`preview failed: ${r.status}`);
        return r.json();
      });
      const pages = (preview.pages || [])
        .map(
          (p) =>
            `<figure style="margin:0 0 1rem"><figcaption style="font:700 0.72rem system-ui;color:#78716c;margin:0 0 .35rem">Page ${p.page}</figcaption>` +
            `<img alt="page ${p.page}" style="width:100%;border:1px solid #e7e5e4" src="data:image/png;base64,${p.bytes}" /></figure>`
        )
        .join("");
      frame.removeAttribute("src");
      frame.srcdoc = `<!DOCTYPE html><html><body style="margin:0;padding:1rem;background:#fff;font-family:Georgia,serif">
        <div style="font-weight:700;margin-bottom:.75rem">${(title || uri).replace(/</g,"&lt;")}</div>
        ${pages}
      </body></html>`;
    } else {
      const url = URL.createObjectURL(blob);
      frame.removeAttribute("srcdoc");
      frame.src = url;
    }
    status.textContent = `Open: ${title || uri} (${blob.size.toLocaleString()} bytes · ${blob.type || "bytes"})`;
    setFlow("Source open for reviewer");
  } catch (err) {
    status.textContent = String(err.message || err);
    setFlow("Error");
  }
}

document.getElementById("claimForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payer = document.getElementById("payer").value;
  const cpt = document.getElementById("cpt").value;
  const btn = document.getElementById("runBtn");
  btn.disabled = true;
  setFlow("Calling MCP tool…");
  try {
    await mcp("initialize", {
      protocolVersion: "2024-11-05",
      capabilities: {},
      clientInfo: { name: "claims-desk-app", version: "0.2" },
    });
    const data = await callTool("review_claim_requirements", { payer, cpt });
    renderResult(data);
    setFlow("Tool result ready — open a citation");
    // Auto-open first citation for demo/screenshots
    if (data.citations?.[0]) {
      await openPdf(data.citations[0].uri, data.citations[0].title);
    }
  } catch (err) {
    setFlow("Error");
    alert(err.message || String(err));
  } finally {
    btn.disabled = false;
  }
});

// Auto-demo for screenshots: /?demo=1&payer=acme-health&cpt=27447
(async function bootDemo() {
  const params = new URLSearchParams(location.search);
  if (params.get("demo") !== "1") return;
  const payer = params.get("payer") || "acme-health";
  const cpt = params.get("cpt") || "27447";
  document.getElementById("payer").value = payer;
  const cptEl = document.getElementById("cpt");
  if ([...cptEl.options].some((o) => o.value === cpt)) cptEl.value = cpt;
  await new Promise((r) => setTimeout(r, 400));
  document.getElementById("claimForm").requestSubmit();
})();

// Warm initialize on load
mcp("initialize", {
  protocolVersion: "2024-11-05",
  capabilities: {},
  clientInfo: { name: "claims-desk-app", version: "0.2" },
}).then(() => {
  if (!new URLSearchParams(location.search).get("demo")) setFlow("MCP connected");
}).catch(() => setFlow("MCP unreachable"));
