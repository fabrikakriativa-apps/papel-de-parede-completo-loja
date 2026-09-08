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


def extract_gallery_objects(obj):
    found = []
    if isinstance(obj, dict):
        if isinstance(obj.get("gallery"), dict) and isinstance(obj["gallery"].get("items"), list):
            found.append(obj["gallery"])
        for v in obj.values():
            found.extend(extract_gallery_objects(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(extract_gallery_objects(v))
    return found


async def main():
    refs_network = set()
    gallery_responses = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1200})

        async def inspect_response(response):
            req = response.request
            rtype = req.resource_type
            if rtype not in {"xhr", "fetch", "document"}:
                return
            try:
                headers = await response.all_headers()
                ctype = headers.get("content-type", "")
                if "json" not in ctype and rtype not in {"xhr", "fetch"}:
                    return
                body = await response.text()
            except Exception:
                return

            refs = sorted(set(x.upper() for x in REF_RE.findall(body)))
            refs_network.update(refs)

            try:
                parsed = json.loads(body)
            except Exception:
                return

            for gallery in extract_gallery_objects(parsed):
                items = []
                for it in gallery.get("items", []):
                    if not isinstance(it, dict):
                        continue
                    items.append({
                        "id": it.get("id"),
                        "name": it.get("name"),
                        "title": it.get("title"),
                        "mediaUrl": it.get("mediaUrl"),
                        "orderIndex": it.get("orderIndex"),
                        "dataType": it.get("dataType"),
                    })
                gallery_responses.append({
                    "response_url": response.url,
                    "gallery_id": gallery.get("id"),
                    "totalItemsCount": gallery.get("totalItemsCount"),
                    "items_count": len(items),
                    "items": items,
                })

        page.on("response", inspect_response)
        await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(8000)
        for _ in range(28):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(600)

        body_text = await page.locator("body").inner_text()
        refs_dom = sorted(set(x.upper() for x in REF_RE.findall(body_text)))
        html = await page.content()
        refs_html = sorted(set(x.upper() for x in REF_RE.findall(html)))
        await browser.close()

    # Merge gallery items by stable id/media/name across all public responses.
    merged = {}
    totals = []
    for response in gallery_responses:
        if response.get("totalItemsCount") is not None:
            totals.append(response["totalItemsCount"])
        for item in response["items"]:
            key = item.get("id") or item.get("mediaUrl") or item.get("name") or item.get("title")
            if key:
                merged[key] = item

    gallery_items = sorted(
        merged.values(),
        key=lambda x: (x.get("orderIndex") is None, x.get("orderIndex") or 0, x.get("name") or "")
    )
    matching = [x for x in gallery_items if REF_RE.search((x.get("title") or "") + " " + (x.get("name") or ""))]
    nonmatching = [x for x in gallery_items if x not in matching]

    report = {
        "url": URL,
        "refs_dom_count": len(refs_dom),
        "refs_dom": refs_dom,
        "refs_html_count": len(refs_html),
        "refs_html": refs_html,
        "refs_network_count": len(refs_network),
        "refs_network": sorted(refs_network),
        "gallery_total_reported": max(totals) if totals else None,
        "gallery_response_count": len(gallery_responses),
        "gallery_responses": gallery_responses,
        "gallery_items_merged_count": len(gallery_items),
        "gallery_items_merged": gallery_items,
        "gallery_matching_ref_count": len(matching),
        "gallery_nonmatching_count": len(nonmatching),
        "gallery_nonmatching": nonmatching,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "refs_dom_count": len(refs_dom),
        "refs_network_count": len(refs_network),
        "gallery_total_reported": report["gallery_total_reported"],
        "gallery_items_merged_count": len(gallery_items),
        "gallery_matching_ref_count": len(matching),
        "gallery_nonmatching": [x.get("name") or x.get("title") for x in nonmatching],
    }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
