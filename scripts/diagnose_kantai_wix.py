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
BROAD_RE = re.compile(r"\bAD[A-Z0-9-]{5,14}\b", re.I)


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
                        entry["body_excerpt"] = body[:24000]
            except Exception as exc:
                entry["body_error"] = f"{type(exc).__name__}: {exc}"
            network.append(entry)

        page.on("response", inspect_response)
        await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(8000)

        for _ in range(28):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(600)

        body_text = await page.locator("body").inner_text()
        refs_dom = sorted(set(x.upper() for x in REF_RE.findall(body_text)))
        broad_tokens = sorted(set(x.upper() for x in BROAD_RE.findall(body_text)))

        # For each exact reference text element, walk upward until an ancestor with an image is found.
        cards = await page.evaluate("""
        () => {
          const re = /^AD3\\d{5}R$/i;
          const all = [...document.querySelectorAll('body *')];
          const out = [];
          const seen = new Set();
          for (const el of all) {
            const text = (el.textContent || '').trim();
            if (!re.test(text)) continue;
            if ([...el.children].some(c => re.test((c.textContent || '').trim()))) continue;
            let cur = el;
            let holder = null;
            for (let i=0; i<7 && cur; i++, cur=cur.parentElement) {
              const imgs = cur.querySelectorAll ? cur.querySelectorAll('img') : [];
              if (imgs && imgs.length) { holder = cur; break; }
            }
            if (!holder) continue;
            const imgs = [...holder.querySelectorAll('img')].map(img => ({
              src: img.currentSrc || img.src || '',
              alt: img.alt || '',
              title: img.title || '',
              width: img.naturalWidth || 0,
              height: img.naturalHeight || 0
            }));
            const key = text.toUpperCase();
            if (seen.has(key)) continue;
            seen.add(key);
            out.push({
              ref: key,
              tag: el.tagName,
              holder_tag: holder.tagName,
              holder_class: holder.className || '',
              holder_text: (holder.innerText || '').trim().slice(0,500),
              imgs,
              holder_html: holder.outerHTML.slice(0,5000)
            });
          }
          return out;
        }
        """)

        # All image metadata whose URL/alt/title hints at Aditare or AD3, useful for spotting unmatched items.
        ad_images = await page.locator('img').evaluate_all("""
        imgs => imgs.map((img, i) => ({
          i,
          src: img.currentSrc || img.src || '',
          alt: img.alt || '',
          title: img.title || '',
          width: img.naturalWidth || 0,
          height: img.naturalHeight || 0
        })).filter(x => /adit|ad3|ADIT|AD3/.test((x.src+' '+x.alt+' '+x.title)))
        """)

        html = await page.content()
        refs_html = sorted(set(x.upper() for x in REF_RE.findall(html)))
        broad_html = sorted(set(x.upper() for x in BROAD_RE.findall(html)))
        await browser.close()

    focused_network = [x for x in network if x.get("refs") or x["resource_type"] in {"xhr", "fetch"}]
    report = {
        "url": URL,
        "refs_dom_count": len(refs_dom),
        "refs_dom": refs_dom,
        "refs_html_count": len(refs_html),
        "refs_html": refs_html,
        "refs_network_count": len(refs_network),
        "refs_network": sorted(refs_network),
        "broad_tokens_dom": broad_tokens,
        "broad_tokens_html": broad_html,
        "cards_count": len(cards),
        "cards": cards,
        "ad_images_count": len(ad_images),
        "ad_images": ad_images,
        "network": focused_network[:160],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "refs_dom_count": len(refs_dom),
        "refs_network_count": len(refs_network),
        "broad_tokens_dom": broad_tokens,
        "cards_count": len(cards),
        "ad_images_count": len(ad_images),
    }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
