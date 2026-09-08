from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "diagnostico-wiler-vtex.json"

PAGES = {
    "Bambine": "https://www.wiler.com.br/papel-de-parede/bambine?map=category-1%2Ccolecoes",
    "Tacto": "https://www.wiler.com.br/papel-de-parede/tacto?map=category-1%2Ccolecoes",
    "Texture II": "https://www.wiler.com.br/papel-de-parede/texture-ii?map=category-1%2Ccolecoes",
    "Texture III": "https://www.wiler.com.br/papel-de-parede/texture-iii?map=category-1%2Ccolecoes",
    "Tramas": "https://www.wiler.com.br/papel-de-parede/tramas?map=category-1%2Ccolecoes",
}

INTEREST = re.compile(r"(?:catalog|search|graphql|facets|products|vtex|api/io|_v/api)", re.I)


def slim_json(value, depth=0):
    if depth > 4:
        return "[depth]"
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:50]:
            if re.search(r"product|item|record|total|count|facet|search|query|href|link|id|name|reference", str(k), re.I):
                out[k] = slim_json(v, depth + 1)
        return out or {k: slim_json(v, depth + 1) for k, v in list(value.items())[:8]}
    if isinstance(value, list):
        return [slim_json(v, depth + 1) for v in value[:5]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def main() -> None:
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="pt-BR",
            viewport={"width": 1440, "height": 1000},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        )

        for collection, url in PAGES.items():
            page = context.new_page()
            captured = []
            seen = set()

            def on_response(response):
                rurl = response.url
                if rurl in seen or not INTEREST.search(rurl):
                    return
                seen.add(rurl)
                entry = {
                    "url": rurl,
                    "status": response.status,
                    "content_type": response.headers.get("content-type", ""),
                }
                if "json" in entry["content_type"].lower():
                    try:
                        entry["json_preview"] = slim_json(response.json())
                    except Exception as exc:
                        entry["json_error"] = f"{type(exc).__name__}: {exc}"
                captured.append(entry)

            page.on("response", on_response)
            response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(7000)
            # Força lazy/infinite content a disparar as chamadas de busca.
            for _ in range(4):
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(1200)

            text = page.locator("body").inner_text(timeout=10000)
            body_refs = sorted(set(re.findall(r"\b(?:BA\d{4}|TA\d{3,6}(?:-\d{1,3})?|TX-?\d{3,6}|TX3-?\d{2,6}|TR-?\d{3,6}|YS-?\d{5,9})\b", text, re.I)))
            count_matches = re.findall(r"(\d{1,4})\s+Produtos?\s+Encontrados?", text, re.I)
            results.append({
                "colecao": collection,
                "url_solicitada": url,
                "url_final": page.url,
                "http": response.status if response else None,
                "titulo": page.title(),
                "contagens_visiveis": [int(x) for x in count_matches],
                "refs_visiveis": body_refs[:100],
                "refs_visiveis_count": len(body_refs),
                "respostas_interessantes": captured[:80],
            })
            page.close()

        browser.close()

    REPORT.write_text(json.dumps({
        "fonte": "Wiler oficial — navegador + diagnóstico de rede",
        "criterio": "Observa as chamadas públicas que a própria vitrine oficial faz para carregar produtos. Não altera o catálogo.",
        "resultado": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "colecoes": len(results),
        "capturas": sum(len(x["respostas_interessantes"]) for x in results),
        "refs_visiveis": sum(x["refs_visiveis_count"] for x in results),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
