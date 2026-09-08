from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "diagnostico-kantai.json"
URL = "https://www.kantai.com.br/aditare3"
REF_RE = re.compile(r"\bAD3\d{6}R\b", re.I)


async def main():
    network = []
    refs_network = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1200})

        async def inspect_response(response):
            req = response.request
            url = response.url
            rtype = req.resource_type
            if rtype not in {"xhr", "fetch", "document", "script"}:
                return
            try:
                ctype = (await response.all_headers()).get("content-type", "")
            except Exception:
                ctype = ""
            interesting = any(token in url.lower() for token in (
                "wix", "data", "query", "collection", "dataset", "cloud", "_api"
            )) or rtype in {"xhr", "fetch"}
            if not interesting:
                return
            entry = {
                "url": url[:1000],
                "method": req.method,
                "resource_type": rtype,
                "content_type": ctype,
                "post_data": (req.post_data or "")[:12000],
                "status": response.status,
            }
            try:
                if "json" in ctype or "text" in ctype or rtype in {"xhr", "fetch"}:
                    body = await response.text()
                    refs = sorted(set(x.upper() for x in REF_RE.findall(body)))
                    if refs:
                        refs_network.update(refs)
                        entry["refs"] = refs
                        entry["body_excerpt"] = body[:16000]
            except Exception as exc:
                entry["body_error"] = f"{type(exc).__name__}: {exc}"
            network.append(entry)

        page.on("response", inspect_response)
        await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(8000)

        for _ in range(20):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(700)

        body_text = await page.locator("body").inner_text()
        refs_dom = sorted(set(x.upper() for x in REF_RE.findall(body_text)))

        controls = await page.locator("button, a, [role=button]").evaluate_all(
            "els => els.map((e, i) => ({i, tag:e.tagName, text:(e.innerText||e.getAttribute('aria-label')||'').trim().slice(0,200), aria:e.getAttribute('aria-label'), href:e.href||null, disabled:e.disabled||e.getAttribute('aria-disabled')})).filter(x => x.text || x.aria)"
        )
        likely_pagination = [
            x for x in controls
            if any(t in ((x.get("text") or "") + " " + (x.get("aria") or "")).lower()
                   for t in ("mais", "próx", "proxim", "next", "carregar", "ver mais", "mostrar", "page", "página", "pagina"))
        ]

        html = await page.content()
        refs_html = sorted(set(x.upper() for x in REF_RE.findall(html)))

        await browser.close()

    # Keep network output focused: responses containing refs or data/query-like calls.
    focused_network = [
        x for x in network
        if x.get("refs") or x["resource_type"] in {"xhr", "fetch"}
    ]
    report = {
        "url": URL,
        "refs_dom_count": len(refs_dom),
        "refs_dom": refs_dom,
        "refs_html_count": len(refs_html),
        "refs_html": refs_html,
        "refs_network_count": len(refs_network),
        "refs_network": sorted(refs_network),
        "likely_pagination_controls": likely_pagination[:100],
        "network": focused_network[:120],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("refs_dom_count", "refs_html_count", "refs_network_count", "likely_pagination_controls")}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
