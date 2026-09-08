from __future__ import annotations

import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "diagnostico-wiler-oficial.json"
BASE = "https://www.wiler.com.br/"

CANDIDATES = {
    "Harmony III": ["harmony-iii-5", "harmony-iii", "colecao/harmony-iii"],
    "Nickal": ["nickal", "colecao/nickal", "nickal-5"],
    "Pure Nature": ["pure-nature", "colecao/pure-nature", "pure-nature-5"],
    "Pure Nature II": ["pure-nature-ii", "colecao/pure-nature-ii", "pure-nature-ii-5"],
    "Wallstreet": ["wallstreet", "wall-street", "colecao/wallstreet", "wallstreet-5"],
}


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=7) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            title = ""
            mt = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
            if mt:
                title = re.sub(r"\s+", " ", mt.group(1)).strip()
            mc = re.search(r"([0-9]{1,4})\s+Produtos?\s+Encontrados?", body, re.I)
            return {
                "url": url,
                "status": resp.status,
                "url_final": resp.geturl(),
                "titulo": title,
                "produtos_encontrados": int(mc.group(1)) if mc else None,
                "corpo_lower": body.lower(),
                "erro": None,
            }
    except Exception as exc:
        return {
            "url": url,
            "status": 0,
            "url_final": url,
            "titulo": "",
            "produtos_encontrados": None,
            "corpo_lower": "",
            "erro": f"{type(exc).__name__}: {exc}",
        }


def main() -> None:
    tasks = []
    for collection, slugs in CANDIDATES.items():
        for slug in slugs:
            tasks.append((collection, BASE + slug))

    grouped = {collection: [] for collection in CANDIDATES}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(get, url): (collection, url) for collection, url in tasks}
        for future in as_completed(futures):
            collection, _ = futures[future]
            r = future.result()
            body_lower = r.pop("corpo_lower")
            r["contem_nome_colecao"] = collection.lower() in body_lower if r["status"] else False
            grouped[collection].append(r)

    out = []
    for collection in CANDIDATES:
        order = {BASE + slug: i for i, slug in enumerate(CANDIDATES[collection])}
        probes = sorted(grouped[collection], key=lambda r: order[r["url"]])
        out.append({"colecao": collection, "tentativas": probes})

    REPORT.write_text(json.dumps({
        "fonte": "site oficial Wiler",
        "resultado": out,
        "criterio": "Sondagem concorrente de rotas públicas oficiais para localizar a fonte adequada de cada coleção. Não altera o catálogo.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Diagnóstico Wiler concluído")


if __name__ == "__main__":
    main()
