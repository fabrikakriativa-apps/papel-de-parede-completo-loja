from __future__ import annotations

import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "diagnostico-wiler-vtex.json"

# Para descobrir a API basta uma página representativa. Depois o auditor usa
# a mesma API para todas as coleções, evitando cinco navegações lentas.
COLLECTION = "Bambine"
URL = "https://www.wiler.com.br/papel-de-parede/wiler-k?map=category-1%2Cbrand"
INTEREST = re.compile(r"(?:catalog|search|graphql|facets|products|vtex|api/io|_v/api)", re.I)


def slim_json(value, depth=0):
    if depth > 4:
        return "[depth]"
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:60]:
            if re.search(r"product|item|record|total|count|facet|search|query|href|link|id|name|reference", str(k), re.I):
                out[k] = slim_json(v, depth + 1)
        return out or {k: slim_json(v, depth + 1) for k, v in list(value.items())[:8]}
    if isinstance(value, list):
        return [slim_json(v, depth + 1) for v in value[:5]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="pt-BR",
            viewport={"width": 1440, "height": 1000},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        )
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
        response = page.goto(URL, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(5000)
        for _ in range(2):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1000)

        text = page.locator("body").inner_text(timeout=8000)
        body_refs = sorted(set(re.findall(r"\b(?:BA\d{4}|TA\d{3,6}(?:-\d{1,3})?|TX-?\d{3,6}|TX3-?\d{2,6}|TR-?\d{3,6}|YS-?\d{5,9})\b", text, re.I)))
        count_matches = re.findall(r"(\d{1,4})\s+Produtos?\s+Encontrados?", text, re.I)
        result = {
            "pagina_representativa": COLLECTION,
            "url_solicitada": URL,
            "url_final": page.url,
            "http": response.status if response else None,
            "titulo": page.title(),
            "contagens_visiveis": [int(x) for x in count_matches],
            "refs_visiveis": body_refs[:100],
            "refs_visiveis_count": len(body_refs),
            "respostas_interessantes": captured[:120],
        }
        browser.close()

    REPORT.write_text(json.dumps({
        "fonte": "Wiler oficial — navegador + diagnóstico de rede",
        "criterio": "Usa uma vitrine oficial representativa para descobrir a API pública usada pelo próprio site. Não altera o catálogo.",
        "resultado": result,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "capturas": len(result["respostas_interessantes"]),
        "refs_visiveis": result["refs_visiveis_count"],
        "contagens": result["contagens_visiveis"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
