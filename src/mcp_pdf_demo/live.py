"""Live document fetch + optional RCI API enrichment."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache" / "docs"
CACHE.mkdir(parents=True, exist_ok=True)


def _load_dotenv() -> None:
    """Load repo .env into os.environ if present (does not override existing)."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
    "mcp-claims-desk/0.3"
)

CATALOG = json.loads((ROOT / "fixtures" / "catalog.json").read_text(encoding="utf-8"))


def _http_get(url: str, timeout: float = 45.0) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        ctype = (resp.headers.get("Content-Type") or "application/octet-stream").split(";")[0].strip()
        return data, ctype


def html_to_text(html: bytes) -> str:
    text = html.decode("utf-8", errors="replace")
    # Drop CSS/JS before tag-stripping so excerpt never includes stylesheet bodies
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tag_text(html: str, element_id: str) -> str:
    m = re.search(
        rf'(?is)<(?:span|div|h[1-6]|label)[^>]*\bid=["\']{re.escape(element_id)}["\'][^>]*>(.*?)</(?:span|div|h[1-6]|label)>',
        html,
    )
    if not m:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"(?is)<[^>]+>", " ", m.group(1))).strip()


def _slice_until(html: str, start_marker: str, stop_markers: list[str]) -> str:
    start = html.find(start_marker)
    if start < 0:
        return ""
    # Back up to the opening '<' so we don't leak raw attributes into text nodes.
    tag_start = html.rfind("<", 0, start)
    if tag_start >= 0:
        start = tag_start
    end = len(html)
    for marker in stop_markers:
        idx = html.find(marker, start + len(start_marker))
        if idx >= 0:
            end = min(end, idx)
    return html[start:end]


def _clean_fragment(fragment: str) -> str:
    """Drop CMS chrome / licenses / forms from an HTML fragment."""
    text = fragment
    drop_patterns = (
        r"(?is)<script[^>]*>.*?</script>",
        r"(?is)<style[^>]*>.*?</style>",
        r"(?is)<noscript[^>]*>.*?</noscript>",
        r"(?is)<nav[^>]*>.*?</nav>",
        r"(?is)<iframe[^>]*>.*?</iframe>",
        r"(?is)<form[^>]*>.*?</form>",
        r"(?is)<!--.*?-->",
        r"(?is)<div[^>]*(?:modal|license|email|basket|subscribe)[^>]*>.*?</div>",
        r"(?is)<button\b[^>]*>.*?</button>",
        r"(?is)<input\b[^>]*/?>",
        r"(?is)<textarea\b[^>]*>.*?</textarea>",
        r"(?is)<select\b[^>]*>.*?</select>",
    )
    for pat in drop_patterns:
        text = re.sub(pat, "", text)
    text = re.sub(r'(?is)\son\w+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', "", text)
    text = re.sub(r'(?is)href\s*=\s*([\'"])\s*javascript:[^\'"]*\1', 'href="#"', text)
    # UI chrome phrases often left as naked text/links
    for phrase in (
        r"(?is)Expand All\s*\|\s*Collapse All",
        r"(?is)Email Document",
        r"(?is)Add to basket",
        r"(?is)Subscribe",
        r"(?is)Links in PDF documents are not guaranteed to work\.[^<]*",
        r"(?is)Please accept the License to see the codes\.",
        r"(?is)You are here",
        r"(?is)Read the LCD Disclaimer",
        r"(?is)Email this document to yourself or someone else.*",
    ):
        text = re.sub(phrase, "", text)
    # Collapse empty wrappers lightly
    text = re.sub(r"(?is)<(div|span)[^>]*>\s*</\1>", "", text)
    return text.strip()


def sanitize_lcd_html(html: bytes, *, title: str = "CMS source") -> str:
    """Extract reviewer-facing LCD sections; drop CMS chrome and license modals."""
    raw = html.decode("utf-8", errors="replace")

    lcd_id = _tag_text(raw, "lblLcdId") or "—"
    lcd_title = _tag_text(raw, "lblLcdTitle") or title
    effective = _tag_text(raw, "lblOriginalEffectiveDate") or _tag_text(raw, "lblRevisionEffectiveDate")
    revision = _tag_text(raw, "lblRevisionEffectiveDate")

    stop_after_guidance = [
        'id="h3BillCodesHeader"',
        'id="pnlCodingInformation"',
        'id="pnlProcessInformation"',
        'id="pnlRevisionHistoryInformation"',
        'id="pnlAssociatedDocuments"',
        "Email this document",
        "License For Use Of Current Procedural Terminology",
        "License Agreements",
    ]

    policy = _clean_fragment(
        _slice_until(
            raw,
            'id="h3CmsNationalCoveragePolicyHeader"',
            ['id="h3LcdGuidanceHeader"', *stop_after_guidance],
        )
    )
    guidance = _clean_fragment(
        _slice_until(raw, 'id="h3LcdGuidanceHeader"', stop_after_guidance)
    )
    docs = _clean_fragment(
        _slice_until(
            raw,
            "Documentation Requirements",
            [
                "Utilization Guidelines",
                'id="pnlRevisionHistoryInformation"',
                'id="pnlAssociatedDocuments"',
                "Email this document",
                "License For Use",
            ],
        )
    )

    # Fallback if CMS markup changes: keep a trimmed middle slice around Coverage Guidance
    if len(guidance) < 800:
        start = raw.lower().find("coverage indications")
        end = raw.lower().find("license for use")
        if start < 0:
            start = raw.lower().find("coverage guidance")
        if end < 0:
            end = raw.lower().find("email this document")
        if start >= 0 and end > start:
            guidance = _clean_fragment(raw[start:end])

    body_parts = [
        f"<h1>{lcd_title}</h1>",
        f'<p class="meta-line"><strong>LCD ID:</strong> {lcd_id}'
        + (f' · <strong>Effective:</strong> {effective}' if effective else "")
        + (f' · <strong>Revision:</strong> {revision}' if revision else "")
        + "</p>",
        '<p class="meta-line"><a href="https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdId=33618" target="_blank" rel="noopener">Open on CMS</a></p>',
    ]
    if policy:
        # Normalize CMS h3 header class into a normal heading
        policy = re.sub(
            r'(?is)<h3[^>]*id="h3CmsNationalCoveragePolicyHeader"[^>]*>\s*CMS National Coverage Policy\s*</h3>',
            "<h2>CMS National Coverage Policy</h2>",
            policy,
        )
        body_parts.append(f"<section>{policy}</section>")
    if guidance:
        guidance = re.sub(
            r'(?is)<h3[^>]*id="h3LcdGuidanceHeader"[^>]*>\s*Coverage Guidance\s*</h3>',
            "<h2>Coverage Guidance</h2>",
            guidance,
        )
        body_parts.append(f"<section>{guidance}</section>")
    if docs and "Documentation Requirements" in docs:
        body_parts.append(f"<section><h2>Documentation Requirements</h2>{docs}</section>")

    body = "\n".join(body_parts)
    # Prefer the real cms.gov URL from title context when present in page
    cms_link = re.search(r'(https://www\.cms\.gov/medicare-coverage-database/view/lcd\.aspx\?[^"\s]+)', raw)
    if cms_link:
        body = body.replace(
            'href="https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdId=33618"',
            f'href="{cms_link.group(1)}"',
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" />
<title>{lcd_title}</title>
<style>
  body {{
    margin: 0; padding: 1.25rem 1.4rem 2rem;
    font: 15px/1.55 Georgia, "Iowan Old Style", "Palatino Linotype", serif;
    color: #1c1917; background: #fff;
  }}
  h1,h2,h3,h4 {{ font-family: system-ui, -apple-system, sans-serif; line-height: 1.25; color: #1c1917; }}
  h1 {{ font-size: 1.35rem; margin: 0 0 0.5rem; }}
  h2, h3.document-view-section-header {{ font-size: 1.08rem; margin: 1.35rem 0 0.5rem; }}
  h3, .document-view-section-subheader {{ font-size: 0.98rem; margin: 1rem 0 0.35rem; font-weight: 700; }}
  p, .document-view-section-text {{ margin: 0.55rem 0; }}
  ul, ol {{ margin: 0.4rem 0 0.8rem; padding-left: 1.3rem; }}
  li {{ margin: 0.25rem 0; }}
  strong {{ font-weight: 700; }}
  a {{ color: #0f766e; }}
  .doc-banner {{
    font: 700 0.72rem/1 system-ui, sans-serif; letter-spacing: 0.06em; text-transform: uppercase;
    color: #57534e; margin-bottom: 0.65rem;
  }}
  .meta-line {{ font: 0.88rem/1.4 system-ui, sans-serif; color: #44403c; margin: 0.25rem 0 0.9rem; }}
  section {{ margin-top: 0.5rem; }}
</style></head><body>
<p class="doc-banner">Live CMS LCD · coverage body</p>
{body}
</body></html>"""


def fetch_source(source: dict[str, Any], *, force: bool = False) -> tuple[bytes, str, dict[str, Any]]:
    """Fetch a catalog source; cache on disk. Returns (bytes, mime, meta)."""
    sid = source["id"]
    kind = source.get("kind") or "html"
    cache_bin = CACHE / f"{sid}.bin"
    cache_meta = CACHE / f"{sid}.meta.json"
    if cache_bin.exists() and cache_meta.exists() and not force:
        meta = json.loads(cache_meta.read_text())
        return cache_bin.read_bytes(), meta["mimeType"], meta

    raw, ctype = _http_get(source["url"])
    if kind == "html" or "html" in ctype:
        page = sanitize_lcd_html(raw, title=source.get("title") or sid)
        payload = page.encode("utf-8")
        meta = {
            "id": sid,
            "title": source["title"],
            "url": source["url"],
            "mimeType": "text/html",
            "sourceKind": "html",
            "bytes": len(payload),
            "fetched": True,
        }
    else:
        payload = raw
        mime = ctype if ctype else "application/pdf"
        meta = {
            "id": sid,
            "title": source["title"],
            "url": source["url"],
            "mimeType": mime,
            "sourceKind": "pdf",
            "bytes": len(payload),
            "fetched": True,
        }

    cache_bin.write_bytes(payload)
    cache_meta.write_text(json.dumps(meta, indent=2))
    return payload, meta["mimeType"], meta


def find_scenario(payer: str, cpt: str) -> dict[str, Any] | None:
    payer_key = payer.strip().lower().replace(" ", "-")
    code = cpt.strip()
    for s in CATALOG["scenarios"]:
        if s["payer"] == payer_key and s["cpt"] == code:
            return s
    for s in CATALOG["scenarios"]:
        if s["cpt"] == code:
            return s
    return None


def list_all_sources() -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for s in CATALOG["scenarios"]:
        for src in s["sources"]:
            seen[src["id"]] = src
    return list(seen.values())


def source_by_uri(uri: str) -> dict[str, Any] | None:
    for src in list_all_sources():
        if src["uri"] == uri:
            return src
    return None


def _rci_headers() -> dict[str, str] | None:
    api_key = os.environ.get("RCI_API_KEY") or os.environ.get("X_API_KEY")
    if not api_key:
        return None
    return {"User-Agent": UA, "X-API-Key": api_key, "Accept": "application/json"}


def _rci_base() -> str:
    return (os.environ.get("RCI_API_URL") or "https://api-dev.rcintell.com").rstrip("/")


def rci_claim_intelligence(slug: str, code: str, service_category: str) -> dict[str, Any] | None:
    from urllib.parse import quote

    headers = _rci_headers()
    if not headers:
        return None
    url = (
        f"{_rci_base()}/v1/payers/{quote(slug)}/claim-intelligence"
        f"?code={quote(code)}"
        f"&service_category={quote(service_category)}"
    )
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {
            "error": f"RCI HTTP {exc.code}",
            "detail": exc.read().decode("utf-8", errors="replace")[:500],
        }
    except Exception as exc:
        return {"error": str(exc)}


def rci_prior_auth(slug: str, code: str, service_category: str) -> dict[str, Any] | None:
    headers = _rci_headers()
    if not headers:
        return None
    from urllib.parse import urlencode

    qs = urlencode({"payer_slug": slug, "code": code, "service_category": service_category})
    url = f"{_rci_base()}/v1/prior-auth/check?{qs}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def extract_lcd_highlights(text: str) -> dict[str, Any]:
    """Pull a few reviewer-facing fields from live LCD text."""
    lower = text.lower()
    attachments: list[str] = []
    if "conservative" in lower:
        attachments.append("conservative_care_notes")
    if "radiograph" in lower or "x-ray" in lower or "imaging" in lower:
        attachments.append("radiology_report")
    if "history" in lower and "physical" in lower:
        attachments.append("history_and_physical")
    if not attachments:
        attachments = ["clinical_notes"]

    prior_auth = "see_lcd"
    if "prior authorization" in lower or "prior auth" in lower:
        prior_auth = "check_lcd_and_mac"

    idx = lower.find("total knee")
    if idx < 0:
        idx = lower.find("medically necessary")
    if idx < 0:
        idx = 0
    excerpt = text[idx : idx + 600].strip()

    return {
        "prior_auth": prior_auth,
        "required_attachments": attachments,
        "source_excerpt": excerpt,
    }


def flatten_rci(pa: dict[str, Any] | None, intel: dict[str, Any] | None) -> dict[str, Any]:
    """Collapse prior-auth + claim-intelligence into reviewer-facing fields."""
    out: dict[str, Any] = {}
    pa = pa if isinstance(pa, dict) and "error" not in pa else None
    intel = (
        intel
        if isinstance(intel, dict) and "error" not in intel and intel.get("detail") != "Payer not found"
        else None
    )

    nested = (intel or {}).get("prior_auth") if intel else None
    if isinstance(nested, dict) and nested.get("determination"):
        pa = nested

    if pa and pa.get("determination") and pa.get("determination") != "unable_to_determine":
        out["prior_auth"] = pa["determination"]
        out["pa_required"] = bool(pa.get("pa_required"))
        out["pa_confidence"] = pa.get("confidence")
        out["pa_resolution_tier"] = pa.get("resolution_tier")
        matched = [t for t in (pa.get("rationale_chain") or []) if t.get("matched")]
        if matched:
            out["pa_matched_rule"] = matched[0].get("detail") or matched[0].get("tier_name")
        docs = [d for d in (pa.get("required_documents") or []) if d]
        if docs:
            out["required_attachments"] = docs
        if pa.get("standard_turnaround_days") is not None:
            out["pa_turnaround_days"] = pa["standard_turnaround_days"]
        if pa["determination"] == "auth_required":
            out["status"] = "prior_auth_required"
        elif pa["determination"] == "auth_not_required":
            out["status"] = "no_prior_auth"

    if intel:
        filing = intel.get("filing_rules") or []
        if isinstance(filing, list) and filing:
            days = filing[0].get("standard_days")
            if days is not None:
                out["timely_filing_days"] = days
        if intel.get("payer_name"):
            out["rci_payer_name"] = intel["payer_name"]
        if intel.get("payer_slug"):
            out["rci_payer_slug"] = intel["payer_slug"]
        appeals = intel.get("appeal_rules") or []
        if isinstance(appeals, list) and appeals:
            out["appeal_levels"] = len(appeals)
            out["first_appeal_deadline_days"] = appeals[0].get("deadline_days")

    return out
