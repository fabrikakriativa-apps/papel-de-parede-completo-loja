from __future__ import annotations

import html as html_lib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-wiler-oficial.json"
BASE = "https://www.wiler-k.com.br/papel-de-parede/"

COLLECTIONS = {
    "Bambine": "bambine",
    "Tacto": "tacto",
    "Texture II": "texture-ii",
    "Texture III": "texture-iii",
    "Tramas": "tramas",
}

COUNT_RE = re.compile(r"([0-9]{1,4})\s+Produtos?\s+Encontrados?", re.I)
LINK_RE = re.compile(r'href=["\']([^"\']+/p(?:\?[^"\']*)?)["\']', re.I)
# Aceita os formatos usados hoje pelas cinco coleções do catálogo.
REF_PATTERNS = {
    "Bambine": re.compile(r"\b(BA\d{4})\b", re.I),
    "Tacto": re.compile(r"\b(TA\d{3,6}(?:-\d{1,3})?)\b", re.I),
    "Texture II": re.compile(r"\b(TX-?\d{3,6})\b", re.I),
    "Texture III": re.compile(r"\b(TX3-?\d{2,6}|TX-?3\d{2,6})\b", re.I),
    "Tramas": re.compile(r"\b(TR-?\d{3,6}|YS-?\d{5,9})\b", re.I),
}


def parse_data() -> list[dict]:
    text = INDEX.read_text(encoding="utf-8")
    marker = "let DATA="
    start = text.index(marker) + len(marker)
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    return data


def norm(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def fetch(url: str) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} em {url}")
        return resp.read().decode("utf-8", errors="replace"), resp.geturl()


def collection_url(slug: str, page: int | None = None) -> str:
    params = {"map": "category-1,colecoes"}
    if page and page > 1:
        params["page"] = str(page)
    return BASE + slug + "?" + urllib.parse.urlencode(params)


def refs_from_source(source: str, collection: str) -> set[str]:
    source = html_lib.unescape(source)
    pattern = REF_PATTERNS[collection]
    refs = {m.group(1).upper() for m in pattern.finditer(source)}
    return refs


def crawl(collection: str, slug: str) -> dict:
    first_url = collection_url(slug)
    source, final_url = fetch(first_url)
    mc = COUNT_RE.search(source)
    official_count = int(mc.group(1)) if mc else None
    if official_count is None:
        raise RuntimeError(f"A página oficial não informou 'Produtos Encontrados': {final_url}")

    all_refs: set[str] = set()
    pages: list[dict] = []
    # A vitrine VTEX normalmente expõe dezenas de itens por página. Percorremos
    # até a página deixar de acrescentar referências; teto alto para não truncar.
    for page in range(1, 60):
        url = collection_url(slug, page)
        body, resolved = fetch(url)
        refs = refs_from_source(body, collection)
        new = refs - all_refs
        pages.append({
            "pagina": page,
            "url": url,
            "url_final": resolved,
            "refs_encontradas": len(refs),
            "novas": len(new),
        })
        if page == 1 and not refs:
            # Contagem oficial ainda é útil; a ausência de refs impede comparar
            # referência a referência, mas nunca vira falso 'completo'.
            break
        if page > 1 and not new:
            break
        all_refs.update(refs)
        if official_count and len(all_refs) >= official_count:
            break

    return {
        "url_oficial": first_url,
        "url_final": final_url,
        "oficial_total": official_count,
        "refs_oficiais_extraidas": sorted(all_refs),
        "paginas": pages,
    }


def main() -> None:
    data = parse_data()
    results = []
    errors = []

    for collection, slug in COLLECTIONS.items():
        catalog_refs = {
            str(x.get("ref") or "").strip()
            for x in data
            if x.get("fornecedor") == "Wiler" and x.get("colecao") == collection and str(x.get("ref") or "").strip()
        }
        try:
            official = crawl(collection, slug)
        except Exception as exc:
            errors.append({
                "colecao": collection,
                "url_oficial": collection_url(slug),
                "erro": f"{type(exc).__name__}: {exc}",
            })
            results.append({
                "colecao": collection,
                "url_oficial": collection_url(slug),
                "oficial_total": None,
                "catalogo": len(catalog_refs),
                "diferenca_contagem": None,
                "faltantes_confirmados": [],
                "extras_confirmados": [],
                "refs_oficiais_extraidas": 0,
                "status": "erro_coleta",
            })
            continue

        official_refs = official["refs_oficiais_extraidas"]
        official_norm = {norm(r): r for r in official_refs if norm(r)}
        catalog_norm = {norm(r): r for r in catalog_refs if norm(r)}
        missing_keys = sorted(set(official_norm) - set(catalog_norm))
        extra_keys = sorted(set(catalog_norm) - set(official_norm))
        missing = [official_norm[k] for k in missing_keys]
        extras = [catalog_norm[k] for k in extra_keys]

        # Se não conseguimos extrair todas as refs, não classificamos itens do
        # catálogo como extras: a contagem oficial continua sendo a verdade para
        # detectar coleção incompleta sem gerar falso positivo por parsing.
        refs_complete = len(official_refs) >= official["oficial_total"]
        if not refs_complete:
            extras = []

        results.append({
            "colecao": collection,
            "url_oficial": official["url_oficial"],
            "url_final": official["url_final"],
            "oficial_total": official["oficial_total"],
            "catalogo": len(catalog_refs),
            "diferenca_contagem": official["oficial_total"] - len(catalog_refs),
            "faltantes_confirmados": missing,
            "extras_confirmados": extras,
            "refs_oficiais_extraidas": len(official_refs),
            "refs_oficiais_completas": refs_complete,
            "paginas": official["paginas"],
            "status": "ok" if official["oficial_total"] == len(catalog_refs) else "divergencia_contagem",
        })

    valid = [r for r in results if r["oficial_total"] is not None]
    report = {
        "fonte": "Wiler-K — páginas oficiais de coleção",
        "dominio_oficial": "https://www.wiler-k.com.br/",
        "fornecedor_catalogo": "Wiler",
        "colecoes_configuradas": len(results),
        "colecoes_auditadas_com_sucesso": len(valid),
        "erros_coleta": errors,
        "total_oficial": sum(r["oficial_total"] for r in valid),
        "total_catalogo": sum(r["catalogo"] for r in results),
        "saldo_contagem": sum((r["oficial_total"] or 0) - r["catalogo"] for r in results if r["oficial_total"] is not None),
        "colecoes_com_divergencia": [r["colecao"] for r in valid if r["oficial_total"] != r["catalogo"]],
        "colecoes": results,
        "criterio": "A contagem vem exclusivamente da vitrine oficial Wiler-K filtrada por coleção. A comparação referência a referência só é considerada completa quando o parser recupera ao menos o total oficial; falhas nunca são tratadas como zero.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "colecoes_ok": len(valid),
        "erros": len(errors),
        "total_oficial": report["total_oficial"],
        "total_catalogo": report["total_catalogo"],
        "saldo_contagem": report["saldo_contagem"],
        "divergencias": report["colecoes_com_divergencia"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
