from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "diagnostico-homefinish-endpoints.json"
BASE = "https://www.homefinish.com.br"

ENDPOINTS = [
    "/robots.txt",
    "/wp-sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap.xml",
    "/wp-json/",
    "/wp-json/wp/v2/types",
    "/feed/",
]


def get(path: str) -> dict:
    url = BASE + path
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Accept": "application/xml,text/xml,application/json,text/plain,text/html,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read(2_000_000)
            text = raw.decode("utf-8", errors="replace")
            urls = re.findall(r"https?://[^<\s\"']+", text)
            product_urls = sorted({u.rstrip("/)"] for u in urls if "/papel-de-parede/" in u})
            collection_urls = sorted({u.rstrip("/)"] for u in urls if "/colecoes/papeis-de-parede/" in u})
            return {
                "path": path,
                "url": url,
                "status": resp.status,
                "url_final": resp.geturl(),
                "content_type": resp.headers.get("content-type", ""),
                "bytes_lidos": len(raw),
                "urls_encontradas": len(urls),
                "urls_produto": product_urls[:30],
                "urls_produto_count": len(product_urls),
                "urls_colecao": collection_urls[:30],
                "urls_colecao_count": len(collection_urls),
                "preview": re.sub(r"\s+", " ", text[:700]).strip(),
                "erro": None,
            }
    except Exception as exc:
        return {
            "path": path,
            "url": url,
            "status": None,
            "erro": f"{type(exc).__name__}: {exc}",
        }


def main() -> None:
    results = [get(path) for path in ENDPOINTS]
    REPORT.write_text(json.dumps({
        "fonte": "Home Finish — endpoints públicos oficiais",
        "objetivo": "Descobrir uma fonte oficial estruturada para auditar todas as referências sem depender das páginas HTML bloqueadas no runner.",
        "resultado": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": sum(1 for r in results if r.get("status") == 200),
        "falhas": sum(1 for r in results if r.get("status") != 200),
        "endpoints": [{"path": r["path"], "status": r.get("status"), "produtos": r.get("urls_produto_count", 0)} for r in results],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
