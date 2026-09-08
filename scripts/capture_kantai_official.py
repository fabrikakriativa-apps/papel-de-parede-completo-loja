from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "auditoria-kantai-oficial.json"

COLLECTIONS = [
    {
        "name": "Aditare 3",
        "slug": "aditare-3",
        "url": "https://www.kantai.com.br/aditare3",
        "expected": 81,
        "ref_re": r"^AD3\d{5}R$",
    },
    {
        "name": "Criativo 3",
        "slug": "criativo-3",
        "url": "https://www.kantai.com.br/criativo3",
        "expected": 89,
        "ref_re": r"^CR\d{6}R$",
    },
    {
        "name": "Poet Chart 5",
        "slug": "poet-chart-5",
        "url": "https://www.kantai.com.br/poetchart5",
        "expected": 78,
        "ref_re": r"^PT\d{6}$",
    },
    {
        "name": "Space IX",
        "slug": "space-ix",
        "url": "https://www.kantai.com.br/space9",
        "expected": 83,
        "ref_re": r"^9S\d{6}$",
    },
]


def gallery_from_payload(obj):
    if isinstance(obj, dict):
        g = obj.get("gallery")
        if isinstance(g, dict) and isinstance(g.get("items"), list):
            yield g
        for v in obj.values():
            yield from gallery_from_payload(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from gallery_from_payload(v)


def ref_from_item(item: dict) -> str:
    for key in ("title", "name"):
        value = str(item.get(key) or "").strip()
        value = re.sub(r"\.(?:jpe?g|png|webp)$", "", value, flags=re.I).strip()
        if value:
            return value.upper()
    return ""


def with_offset(url: str, offset: int, limit: int = 25) -> str:
    parsed = urlparse(url)
    q = parse_qs(parsed.query, keep_blank_values=True)
    q["offset"] = [str(offset)]
    q["limit"] = [str(limit)]
    flat = []
    for k, vals in q.items():
        for v in vals:
            flat.append((k, v))
    return urlunparse(parsed._replace(query=urlencode(flat)))


async def capture_collection(context, cfg: dict) -> dict:
    page = await context.new_page()
    candidates = []

    async def inspect(response):
        if "/pro-gallery-webapp/v1/galleries/" not in response.url:
            return
        try:
            payload = await response.json()
        except Exception:
            return
        for gallery in gallery_from_payload(payload):
            candidates.append({
                "url": response.url,
                "id": gallery.get("id"),
                "total": gallery.get("totalItemsCount"),
                "items": gallery.get("items", []),
            })

    page.on("response", inspect)
    await page.goto(cfg["url"], wait_until="domcontentloaded", timeout=90000)
    await page.wait_for_timeout(7000)
    for _ in range(18):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(500)

    # Give async response handlers a final chance to finish.
    await page.wait_for_timeout(1500)

    matching_candidates = [c for c in candidates if c.get("total") == cfg["expected"]]
    if not matching_candidates:
        # Fall back to the gallery with the largest declared total.
        matching_candidates = sorted(candidates, key=lambda x: x.get("total") or 0, reverse=True)
    if not matching_candidates:
        await page.close()
        return {**cfg, "status": "gallery_not_found", "candidates": []}

    seed = matching_candidates[0]
    seed_url = seed["url"]
    declared_total = int(seed.get("total") or cfg["expected"])

    pages = []
    merged: dict[str, dict] = {}
    for offset in range(0, declared_total, 25):
        url = with_offset(seed_url, offset, 25)
        resp = await context.request.get(url, timeout=90000)
        page_info = {"offset": offset, "url": url, "status": resp.status, "items_count": 0}
        if not resp.ok:
            page_info["error"] = f"HTTP {resp.status}"
            pages.append(page_info)
            continue
        try:
            payload = await resp.json()
        except Exception as exc:
            page_info["error"] = f"json: {type(exc).__name__}: {exc}"
            pages.append(page_info)
            continue

        galleries = list(gallery_from_payload(payload))
        if not galleries:
            page_info["error"] = "gallery_missing_in_payload"
            pages.append(page_info)
            continue
        gallery = galleries[0]
        items = gallery.get("items", [])
        page_info["items_count"] = len(items)
        page_info["totalItemsCount"] = gallery.get("totalItemsCount")
        pages.append(page_info)

        for item in items:
            ref = ref_from_item(item)
            key = str(item.get("id") or item.get("mediaUrl") or ref)
            merged[key] = {
                "id": item.get("id"),
                "ref": ref,
                "name": item.get("name"),
                "title": item.get("title"),
                "mediaUrl": item.get("mediaUrl"),
                "orderIndex": item.get("orderIndex"),
                "dataType": item.get("dataType"),
            }

    await page.close()

    items = sorted(
        merged.values(),
        key=lambda x: (x.get("orderIndex") is None, x.get("orderIndex") or 0, x.get("ref") or ""),
    )
    ref_re = re.compile(cfg["ref_re"], re.I)
    valid = [x for x in items if ref_re.fullmatch(x.get("ref") or "")]
    invalid = [x for x in items if x not in valid]
    unique_refs = sorted({x["ref"] for x in valid})

    return {
        "name": cfg["name"],
        "slug": cfg["slug"],
        "url": cfg["url"],
        "expected": cfg["expected"],
        "gallery_id": seed.get("id"),
        "declared_total": declared_total,
        "pages": pages,
        "captured_items": len(items),
        "valid_reference_items": len(valid),
        "unique_references": len(unique_refs),
        "invalid_items": invalid,
        "status": "ok" if len(items) == declared_total and len(valid) == declared_total else "review",
        "items": items,
    }


async def main():
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 1200})
        for cfg in COLLECTIONS:
            print(f"Capturing {cfg['name']}...")
            result = await capture_collection(context, cfg)
            results.append(result)
            print(json.dumps({
                "name": result.get("name"),
                "expected": result.get("expected"),
                "declared_total": result.get("declared_total"),
                "captured_items": result.get("captured_items"),
                "valid_reference_items": result.get("valid_reference_items"),
                "status": result.get("status"),
            }, ensure_ascii=False))
        await browser.close()

    report = {
        "source": "Kantai official public website / Wix public gallery API",
        "collections": results,
        "summary": [
            {
                "name": r.get("name"),
                "expected": r.get("expected"),
                "declared_total": r.get("declared_total"),
                "captured_items": r.get("captured_items"),
                "valid_reference_items": r.get("valid_reference_items"),
                "invalid_items": len(r.get("invalid_items", [])),
                "status": r.get("status"),
            }
            for r in results
        ],
        "all_ok": all(r.get("status") == "ok" for r in results),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"all_ok": report["all_ok"], "summary": report["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
