from __future__ import annotations

import html as html_lib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-homefinish-oficial.json"
BASE = "https://www.homefinish.com.br/colecoes/papeis-de-parede/"
PAGE_PARAM = "e-page-23ca821"

COLLECTIONS = {
    "BIO Habitat": "bio-habitat",
    "Biomas": "biomas",
    "Bosque da Imaginação": "bosque-da-imaginacao",
    "Botânica": "botanica",
    "Doce Estilo": "doce-estilo",
    "Era Uma Vez": "era-uma-vez",
    "Flora": "flora",
    "HF Texture III": "hf-textures-3",
    "Memórias de Infância": "memorias-de-infancia",
    "Natureza Lúdica": "natureza-ludica",
    "Passeio no Campo": "passeio-no-campo",
    "Provence": "provence",
    "Tartan": "tartan",
}

PRODUCT_RE = re.compile(r"/papel-de-parede/papel-de-parede-([a-zA-Z0-9_-]+)/?", re.I)


def parse_data() -> list[dict]:
    text = INDEX.read_text(encoding="utf-8")
    marker = "let DATA="
    start = text.index(marker) + len(marker)
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    return data


def norm(value: object, collection: str) -> str:
    s = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if collection == "BIO Habitat" and s.startswith("BH"):
        s = s[2:]
    return s


def fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; FabrikaKriativaCatalogAudit/1.0)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} em {url}")
        return resp.read().decode("utf-8", errors="replace")


def refs_from_page(source: str) -> set[str]:
    # Remove a seção de recomendações para não misturar outras coleções.
    upper = html_lib.unescape(source).upper()
    cut_candidates = [
        upper.find("TALVEZ VOCÊ TAMBÉM GOSTE"),
        upper.find("TALVEZ VOCÊ POSSA GOSTAR"),
    ]
    cut_candidates = [p for p in cut_candidates if p >= 0]
    if cut_candidates:
        source = source[:min(cut_candidates)]
    return {urllib.parse.unquote(m.group(1)).upper() for m in PRODUCT_RE.finditer(source)}


def crawl(slug: str) -> tuple[set[str], list[dict]]:
    all_refs: set[str] = set()
    pages: list[dict] = []
    for page in range(1, 25):
        url = BASE + slug + "/"
        if page > 1:
            url += "?" + urllib.parse.urlencode({PAGE_PARAM: page})
        source = fetch(url)
        refs = refs_from_page(source)
        new_refs = refs - all_refs
        pages.append({"pagina": page, "url": url, "refs_encontradas": len(refs), "novas": len(new_refs)})
        if page == 1 and not refs:
            raise RuntimeError(f"Nenhuma referência encontrada na página oficial {url}")
        if page > 1 and not new_refs:
            break
        all_refs.update(refs)
    return all_refs, pages


def main() -> None:
    data = parse_data()
    results = []
    total_missing = 0
    total_extras = 0

    for collection, slug in COLLECTIONS.items():
        official_refs, pages = crawl(slug)
        catalog_raw = {
            str(x.get("ref") or "").strip()
            for x in data
            if x.get("fornecedor") == "Home Finish" and x.get("colecao") == collection and str(x.get("ref") or "").strip()
        }
        official_norm = {norm(r, collection): r for r in official_refs if norm(r, collection)}
        catalog_norm = {norm(r, collection): r for r in catalog_raw if norm(r, collection)}
        missing_keys = sorted(set(official_norm) - set(catalog_norm))
        extra_keys = sorted(set(catalog_norm) - set(official_norm))
        missing = [official_norm[k] for k in missing_keys]
        extras = [catalog_norm[k] for k in extra_keys]
        total_missing += len(missing)
        total_extras += len(extras)
        results.append({
            "colecao": collection,
            "url_oficial": BASE + slug + "/",
            "oficial": len(official_refs),
            "catalogo": len(catalog_raw),
            "faltantes": missing,
            "extras_no_catalogo": extras,
            "paginas": pages,
        })

    report = {
        "fonte": "Home Finish — páginas oficiais das coleções",
        "fornecedor_catalogo": "Home Finish",
        "colecoes_auditadas": len(results),
        "total_oficial": sum(r["oficial"] for r in results),
        "total_catalogo": sum(r["catalogo"] for r in results),
        "total_faltantes": total_missing,
        "total_extras_no_catalogo": total_extras,
        "colecoes": results,
        "criterio": "Compara referências publicadas nas páginas oficiais da Home Finish, percorrendo a paginação, com as referências do DATA atual. Não usa a biblioteca local como fonte de completude.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "colecoes": len(results),
        "total_oficial": report["total_oficial"],
        "total_catalogo": report["total_catalogo"],
        "total_faltantes": total_missing,
        "total_extras": total_extras,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
