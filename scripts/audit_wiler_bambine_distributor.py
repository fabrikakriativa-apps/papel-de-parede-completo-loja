from __future__ import annotations

import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-wiler-bambine-distribuidor.json"
SOURCE = "https://www.imperiopapeldeparede.com.br/produtos/categoria/papel-de-parede-bambine"
REF_RE = re.compile(r"\bBA\d{4}\b", re.I)
COUNT_RE = re.compile(r"\b(\d+)\s+produtos\b", re.I)


def parse_data() -> list[dict]:
    text = INDEX.read_text(encoding="utf-8")
    start = text.index("let DATA=") + len("let DATA=")
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    return data


def main() -> None:
    catalog = parse_data()
    catalog_refs = {
        str(x.get("ref") or "").strip().upper()
        for x in catalog
        if x.get("fornecedor") == "Wiler" and x.get("colecao") == "Bambine" and x.get("ref")
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            locale="pt-BR",
            viewport={"width": 1440, "height": 1200},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        )
        response = page.goto(SOURCE, wait_until="domcontentloaded", timeout=30000)
        if not response or response.status != 200:
            raise RuntimeError(f"Fonte distribuidora indisponível: HTTP {response.status if response else None}")
        page.wait_for_timeout(2500)
        body = page.locator("body").inner_text(timeout=10000)
        browser.close()

    counts = [int(x) for x in COUNT_RE.findall(body)]
    reported = max(counts) if counts else None
    refs = {m.group(0).upper() for m in REF_RE.finditer(body)}
    has_book = "CAT7174" in body.upper()

    expected = {f"BA{i:04d}" for i in range(1, 51)}
    missing_source = sorted(expected - refs)
    unexpected_source = sorted(refs - expected)
    missing_catalog = sorted(refs - catalog_refs)
    extra_catalog = sorted(catalog_refs - refs)

    status = "ok"
    reasons = []
    if reported != 51:
        status = "inconclusivo"
        reasons.append(f"fonte reportou {reported!r} produtos, esperado 51")
    if not has_book:
        status = "inconclusivo"
        reasons.append("mostruário CAT7174 não localizado")
    if refs != expected:
        status = "inconclusivo"
        reasons.append(f"grade não expôs exatamente BA0001-BA0050; faltam={missing_source}, inesperadas={unexpected_source}")
    if status == "ok" and catalog_refs != expected:
        status = "divergencia_catalogo"
        reasons.append(f"catálogo diverge do conjunto oficial; faltam={sorted(expected-catalog_refs)}, extras={sorted(catalog_refs-expected)}")

    report = {
        "fonte": SOURCE,
        "fonte_tipo": "Distribuidor/importador — cadeia de fornecimento",
        "fornecedor": "Wiler",
        "colecao": "Bambine",
        "produtos_reportados": reported,
        "mostruario": "CAT7174" if has_book else None,
        "papeis_oficiais_extraidos": len(refs),
        "refs_oficiais": sorted(refs),
        "catalogo_total": len(catalog_refs),
        "faltantes_no_catalogo": missing_catalog,
        "extras_no_catalogo": extra_catalog,
        "status": status,
        "motivos": reasons,
        "criterio": "A coleção só fecha quando a fonte distribuidora reporta 51 produtos, o mostruário CAT7174 está presente e a grade expõe exatamente as 50 referências BA0001 a BA0050. Nenhuma alteração no catálogo é feita por este auditor.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))

    if status != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
