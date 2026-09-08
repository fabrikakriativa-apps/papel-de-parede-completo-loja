from __future__ import annotations

import json
import re
import urllib.request
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


def get(url: str) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, resp.geturl(), body
    except Exception as exc:
        return 0, url, f"{type(exc).__name__}: {exc}"


def main() -> None:
    out = []
    for collection, slugs in CANDIDATES.items():
        probes = []
        for slug in slugs:
            url = BASE + slug
            status, final_url, body = get(url)
            title = ""
            count = None
            if status:
                mt = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
                if mt:
                    title = re.sub(r"\s+", " ", mt.group(1)).strip()
                mc = re.search(r"([0-9]{1,4})\s+Produtos?\s+Encontrados?", body, re.I)
                if mc:
                    count = int(mc.group(1))
            probes.append({
                "url": url,
                "status": status,
                "url_final": final_url,
                "titulo": title,
                "produtos_encontrados": count,
                "contem_nome_colecao": collection.lower() in body.lower() if status else False,
                "erro": None if status else body[:500],
            })
        out.append({"colecao": collection, "tentativas": probes})

    REPORT.write_text(json.dumps({
        "fonte": "site oficial Wiler",
        "resultado": out,
        "criterio": "Sondagem de rotas públicas oficiais para localizar a fonte adequada de cada coleção. Não altera o catálogo.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Diagnóstico Wiler concluído")


if __name__ == "__main__":
    main()
