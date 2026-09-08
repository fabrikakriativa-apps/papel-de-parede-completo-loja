from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path
from playwright.sync_api import sync_playwright

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

REF_TEXT_RE = re.compile(r"^[A-Z]{0,6}(?:-?[A-Z]{0,3})?-?\d{2,9}[A-Z]?$", re.I)
REF_SLUG_RE = re.compile(r"(?:^|-)([A-Z]{1,6}-?\d{2,9}[A-Z]?|\d{3,9}[A-Z]?)$", re.I)


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


def extract_ref(text: str, href: str) -> str | None:
    text = re.sub(r"\s+", " ", text or "").strip()
    if text and len(text) <= 24 and REF_TEXT_RE.fullmatch(text):
        return text.upper().replace(" ", "")
    path = urllib.parse.urlparse(href or "").path.rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    slug = re.sub(r"^papel-de-parede-", "", slug, flags=re.I)
    m = REF_SLUG_RE.search(slug)
    return m.group(1).upper() if m else None


def refs_from_page(page) -> set[str]:
    rows = page.evaluate("""
        () => {
          const heads = [...document.querySelectorAll('h1,h2,h3,h4')];
          const stop = heads.find(h => /TALVEZ.*GOST/i.test((h.textContent || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g,'')));
          return [...document.querySelectorAll('a[href*="/papel-de-parede/papel-de-parede-"]')]
            .filter(a => !stop || (a.compareDocumentPosition(stop) & Node.DOCUMENT_POSITION_FOLLOWING))
            .map(a => ({text:(a.textContent || '').trim(), href:a.href}));
        }
    """)
    refs = set()
    for row in rows:
        ref = extract_ref(row.get("text", ""), row.get("href", ""))
        if ref:
            refs.add(ref)
    return refs


def crawl(page, slug: str) -> tuple[set[str], list[dict]]:
    all_refs: set[str] = set()
    pages = []
    for number in range(1, 25):
        url = BASE + slug + "/"
        if number > 1:
            url += "?" + urllib.parse.urlencode({PAGE_PARAM: number})
        response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        status = response.status if response else None
        title = page.title()
        refs = refs_from_page(page) if status == 200 else set()
        new_refs = refs - all_refs
        pages.append({
            "pagina": number,
            "url": url,
            "http": status,
            "titulo": title,
            "refs_encontradas": len(refs),
            "novas": len(new_refs),
        })
        if number == 1 and (status != 200 or not refs):
            raise RuntimeError(f"Página oficial não auditável: HTTP {status}, {len(refs)} refs, título={title!r}")
        if number > 1 and not new_refs:
            break
        all_refs.update(refs)
    return all_refs, pages


def main() -> None:
    data = parse_data()
    results = []
    errors = []
    total_missing = 0
    total_extras = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="pt-BR",
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in {"image", "font", "media"} else route.continue_())

        for collection, slug in COLLECTIONS.items():
            catalog_raw = {
                str(x.get("ref") or "").strip()
                for x in data
                if x.get("fornecedor") == "Home Finish" and x.get("colecao") == collection and str(x.get("ref") or "").strip()
            }
            try:
                official_refs, pages = crawl(page, slug)
            except Exception as exc:
                errors.append({"colecao": collection, "url_oficial": BASE + slug + "/", "erro": f"{type(exc).__name__}: {exc}"})
                results.append({
                    "colecao": collection,
                    "url_oficial": BASE + slug + "/",
                    "oficial": None,
                    "catalogo": len(catalog_raw),
                    "faltantes": [],
                    "extras_no_catalogo": [],
                    "paginas": [],
                    "status": "erro_coleta",
                })
                continue

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
                "status": "ok",
            })

        browser.close()

    valid = [r for r in results if r["oficial"] is not None]
    report = {
        "fonte": "Home Finish — páginas oficiais das coleções lidas em navegador real",
        "fornecedor_catalogo": "Home Finish",
        "colecoes_configuradas": len(results),
        "colecoes_auditadas_com_sucesso": len(valid),
        "erros_coleta": errors,
        "total_oficial_parcial": sum(r["oficial"] for r in valid),
        "total_catalogo": sum(r["catalogo"] for r in results),
        "total_faltantes_confirmados": total_missing,
        "total_extras_confirmados": total_extras,
        "colecoes": results,
        "criterio": "Navega pelas páginas oficiais e paginação pública da Home Finish em Chromium. Falhas de acesso nunca são tratadas como zero itens e o script apenas audita; não altera o catálogo.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "colecoes_ok": len(valid),
        "erros": len(errors),
        "total_oficial_parcial": report["total_oficial_parcial"],
        "total_catalogo": report["total_catalogo"],
        "faltantes_confirmados": total_missing,
        "extras_confirmados": total_extras,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
