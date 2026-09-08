from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-wiler-browser.json"
BASE = "https://www.wiler.com.br/papel-de-parede/"

COLLECTIONS = {
    "Bambine": "bambine",
    "Tacto": "tacto",
    "Texture II": "texture-ii",
    "Texture III": "texture-iii",
    "Tramas": "tramas",
}

REF_PATTERNS = {
    "Bambine": re.compile(r"\b(BA-?\d{3,6})\b", re.I),
    "Tacto": re.compile(r"\b(TA-?\d{3,6}(?:-\d{1,3})?)\b", re.I),
    "Texture II": re.compile(r"\b(TX-?2\d{3,5})\b", re.I),
    "Texture III": re.compile(r"\b(TX-?3\d{3,5}|TX3-?\d{2,6})\b", re.I),
    "Tramas": re.compile(r"\b(TR-?\d{3,6}|YS-?\d{5,9})\b", re.I),
}
COUNT_RE = re.compile(r"(\d{1,4})\s+Produtos?\s+Encontrados?", re.I)


def parse_data() -> list[dict]:
    text = INDEX.read_text(encoding="utf-8")
    start = text.index("let DATA=") + len("let DATA=")
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    return data


def norm(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def url_for(slug: str, page_number: int) -> str:
    params = {"map": "category-1,colecoes"}
    if page_number > 1:
        params["page"] = page_number
    return BASE + slug + "?" + urlencode(params)


def extract_refs(text: str, hrefs: list[str], collection: str) -> set[str]:
    source = text + "\n" + "\n".join(hrefs)
    return {m.group(1).upper() for m in REF_PATTERNS[collection].finditer(source)}


def main() -> None:
    data = parse_data()
    output = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="pt-BR",
            viewport={"width": 1440, "height": 1200},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        for collection, slug in COLLECTIONS.items():
            catalog_refs = {
                str(x.get("ref") or "").strip()
                for x in data
                if x.get("fornecedor") == "Wiler"
                and x.get("colecao") == collection
                and str(x.get("ref") or "").strip()
            }
            official_total = None
            official_refs: set[str] = set()
            pages = []
            error = None

            try:
                for page_number in range(1, 15):
                    url = url_for(slug, page_number)
                    response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(5500)
                    # Algumas vitrines só montam todos os cards após entrar no viewport.
                    for _ in range(4):
                        page.mouse.wheel(0, 2200)
                        page.wait_for_timeout(500)

                    body = page.locator("body").inner_text(timeout=10000)
                    hrefs = page.locator("a").evaluate_all("els => els.map(a => a.href || '')")
                    refs = extract_refs(body, hrefs, collection)
                    before = len(official_refs)
                    official_refs.update(refs)
                    new_count = len(official_refs) - before

                    counts = [int(x) for x in COUNT_RE.findall(body)]
                    if page_number == 1 and counts:
                        # Ignora zeros de componentes auxiliares e usa a maior contagem visível.
                        official_total = max(counts)

                    pages.append({
                        "pagina": page_number,
                        "url": url,
                        "url_final": page.url,
                        "http": response.status if response else None,
                        "refs_na_pagina": len(refs),
                        "novas_refs": new_count,
                        "total_acumulado": len(official_refs),
                        "contagens_visiveis": counts,
                    })

                    if official_total and len(official_refs) >= official_total:
                        break
                    if page_number > 1 and new_count == 0:
                        break
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            off_norm = {norm(r): r for r in official_refs if norm(r)}
            cat_norm = {norm(r): r for r in catalog_refs if norm(r)}
            missing = [off_norm[k] for k in sorted(set(off_norm) - set(cat_norm))]
            not_active = [cat_norm[k] for k in sorted(set(cat_norm) - set(off_norm))]
            extraction_complete = bool(official_total) and len(official_refs) >= official_total

            output.append({
                "colecao": collection,
                "url_oficial": url_for(slug, 1),
                "oficial_ativos_total": official_total,
                "catalogo_total": len(catalog_refs),
                "refs_ativas_extraidas": len(official_refs),
                "extracao_ativa_completa": extraction_complete,
                "faltantes_ativos_confirmados": missing,
                "catalogo_nao_encontrado_na_vitrine_ativa": not_active if extraction_complete else [],
                "observacao_catalogo_nao_ativo": "Itens não encontrados na vitrine ativa NÃO são candidatos automáticos a remoção; podem ser referências históricas/válidas do book.",
                "refs_ativas": sorted(official_refs),
                "paginas": pages,
                "erro": error,
                "status": "ok" if extraction_complete else ("parcial" if official_refs else "erro"),
            })

        browser.close()

    report = {
        "fonte": "Wiler — vitrine oficial pública em navegador real",
        "dominio_oficial": "https://www.wiler.com.br/",
        "criterio": "Percorre a paginação renderizada das cinco coleções. A vitrine ativa é usada para detectar referências ativas faltantes no catálogo. Referências do catálogo ausentes na vitrine não são removidas automaticamente.",
        "colecoes": output,
        "resumo": {
            "catalogo_total_wiler": sum(x["catalogo_total"] for x in output),
            "ativos_oficiais_somados": sum(x["oficial_ativos_total"] or 0 for x in output),
            "refs_ativas_extraidas": sum(x["refs_ativas_extraidas"] for x in output),
            "faltantes_ativos_confirmados": sum(len(x["faltantes_ativos_confirmados"]) for x in output),
            "colecoes_extracao_completa": sum(1 for x in output if x["extracao_ativa_completa"]),
            "colecoes_parciais_ou_erro": [x["colecao"] for x in output if not x["extracao_ativa_completa"]],
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["resumo"], ensure_ascii=False))


if __name__ == "__main__":
    main()
