from __future__ import annotations

import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "diagnostico-wiler-oficial.json"
BASE = "https://www.wiler-k.com.br/"

# Coleções que existem no DATA publicado hoje.
# A rota VTEX de coleção usa /papel-de-parede/<slug>?map=category-1,colecoes.
CANDIDATES = {
    "Bambine": ["papel-de-parede/bambine?map=category-1%2Ccolecoes"],
    "Tacto": ["papel-de-parede/tacto?map=category-1%2Ccolecoes"],
    "Texture II": ["papel-de-parede/texture-ii?map=category-1%2Ccolecoes"],
    "Texture III": ["papel-de-parede/texture-iii?map=category-1%2Ccolecoes"],
    "Tramas": ["papel-de-parede/tramas?map=category-1%2Ccolecoes"],
}


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
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
    tasks = [(collection, BASE + slug) for collection, slugs in CANDIDATES.items() for slug in slugs]
    grouped = {collection: [] for collection in CANDIDATES}
    with ThreadPoolExecutor(max_workers=5) as pool:
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
        "fonte": "Wiler-K — site oficial",
        "dominio_oficial": BASE,
        "colecoes_catalogo_atual": list(CANDIDATES),
        "resultado": out,
        "criterio": "Sondagem das rotas públicas oficiais de coleção da Wiler-K. Não altera o catálogo.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Diagnóstico Wiler-K concluído")


if __name__ == "__main__":
    main()
