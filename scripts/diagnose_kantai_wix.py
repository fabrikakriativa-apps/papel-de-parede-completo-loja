from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "diagnostico-kantai.json"
URL = "https://www.kantai.com.br/aditare3"
REF_RE = re.compile(r"\bAD3\d{5}R\b", re.I)


async def collect_visible(page):
    body = await page.locator("body").inner_text()
    refs = sorted(set(x.upper() for x in REF_RE.findall(body)))
    imgs = await page.locator("img").evaluate_all("els => els.map(i => ({alt:i.alt||'', src:i.currentSrc||i.src||''}))")
    matches = []
    for img in imgs:
        m = REF_RE.search((img.get('alt') or '') + ' ' + (img.get('src') or ''))
        if m:
            matches.append({"ref": m.group(0).upper(), "alt": img.get("alt"), "src": img.get("src")})
    return refs, matches


async def main():
    pages = []
    all_refs = set()
    all_images = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1400})
        await page.goto(URL, wait_until="networkidle", timeout=90000)
        await page.wait_for_timeout(3000)

        for page_no in range(1, 10):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.72)")
            await page.wait_for_timeout(1200)
            refs, images = await collect_visible(page)
            all_refs.update(refs)
            for im in images:
                all_images[im["ref"]] = im
            pages.append({"page": page_no, "refs": refs, "refs_count": len(refs), "image_refs": sorted({x['ref'] for x in images})})

            candidates = page.get_by_role("button", name=re.compile("Mais páginas de Nossos Produtos", re.I))
            if await candidates.count() == 0:
                # fallback: identify buttons containing an aria-label with 'Nossos Produtos'
                candidates = page.locator('button[aria-label*="Nossos Produtos"]')
            if await candidates.count() == 0:
                break

            btn = candidates.last
            disabled = await btn.get_attribute("disabled")
            aria_disabled = await btn.get_attribute("aria-disabled")
            if disabled is not None or aria_disabled == "true":
                break

            before = set(refs)
            try:
                await btn.scroll_into_view_if_needed()
                await btn.click(timeout=10000)
                await page.wait_for_timeout(1800)
            except Exception:
                break

            after_refs, _ = await collect_visible(page)
            if set(after_refs) == before:
                # give Wix one extra moment; if still unchanged, stop.
                await page.wait_for_timeout(1800)
                after_refs, _ = await collect_visible(page)
                if set(after_refs) == before:
                    break

        controls = await page.locator("button").evaluate_all("els => els.map(e => ({text:(e.innerText||'').trim(), aria:e.getAttribute('aria-label'), disabled:e.disabled, ariaDisabled:e.getAttribute('aria-disabled')})).filter(x => /next|página|produtos/i.test((x.text||'')+' '+(x.aria||'')))")
        await browser.close()

    report = {
        "url": URL,
        "pages_visited": len(pages),
        "pages": pages,
        "all_refs_count": len(all_refs),
        "all_refs": sorted(all_refs),
        "images_with_ref_count": len(all_images),
        "images_with_ref": [all_images[k] for k in sorted(all_images)],
        "pagination_controls": controls,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"pages_visited": len(pages), "all_refs_count": len(all_refs)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
