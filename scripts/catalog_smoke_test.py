from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-smoke-test.json"

CRITICAL_REFS = [
    {"fornecedor": "Home Finish", "colecao": "BIO Habitat", "ref": "101046"},
    {"fornecedor": "Home Finish", "colecao": "Memórias de Infância", "ref": "MI201010"},
    {"fornecedor": "Kantai", "colecao": "Poet Chart 5", "ref": "PT500706"},
    {"fornecedor": "Kantai", "colecao": "Aditare 3", "ref": "AD300001R"},
    {"fornecedor": "Wiler", "colecao": "Texture III", "ref": "TX-3010"},
    {"fornecedor": "Wiler", "colecao": "Texture III", "ref": "TX-3054"},
]

UI_MARKERS = [
    'id="q"',
    'id="vendor"',
    'id="collection"',
    'id="color"',
    'id="grid"',
    'id="count"',
    'function render()',
    'q.oninput=render',
    'vf.onchange',
    'cf.onchange=render',
]


def parse_data(html: str) -> list[dict]:
    marker = "let DATA="
    if marker not in html:
        raise RuntimeError("Bloco DATA não encontrado no index.html")
    start = html.index(marker) + len(marker)
    data, _ = json.JSONDecoder().raw_decode(html[start:])
    if not isinstance(data, list) or not data:
        raise RuntimeError("DATA vazio ou inválido")
    return data


def norm(value: object) -> str:
    return str(value or "").strip()


def local_path(value: str) -> Path | None:
    if not value or value.startswith(("http://", "https://")):
        return None
    return ROOT / value.split("?", 1)[0].split("#", 1)[0]


def main() -> None:
    html = INDEX.read_text(encoding="utf-8")
    data = parse_data(html)

    inventory = json.loads((ROOT / "auditoria-catalogo-atual.json").read_text(encoding="utf-8"))
    consolidated = json.loads((ROOT / "auditoria-catalogo-consolidada.json").read_text(encoding="utf-8"))

    failures: list[str] = []
    warnings: list[str] = []

    # UI wiring: validates the minimum controls used by the customer-facing catalog.
    missing_ui = [marker for marker in UI_MARKERS if marker not in html]
    if missing_ui:
        failures.append(f"Marcadores essenciais de UI ausentes: {missing_ui}")

    # Cross-report count consistency.
    expected_inventory = int(inventory.get("itens_catalogo") or 0)
    expected_consolidated = int(consolidated.get("itens_catalogo") or 0)
    if len(data) != expected_inventory:
        failures.append(f"DATA={len(data)} difere do inventário={expected_inventory}")
    if len(data) != expected_consolidated:
        failures.append(f"DATA={len(data)} difere do consolidado={expected_consolidated}")

    supplier_counts = Counter(norm(item.get("fornecedor")) for item in data)
    inventory_suppliers = {str(k): int(v) for k, v in (inventory.get("fornecedores") or {}).items()}
    if dict(sorted(supplier_counts.items())) != dict(sorted(inventory_suppliers.items())):
        failures.append(
            f"Totais por fornecedor divergentes: DATA={dict(supplier_counts)} inventário={inventory_suppliers}"
        )

    # Critical regression references: items that were specifically repaired/audited.
    critical_results = []
    for expected in CRITICAL_REFS:
        matches = [
            item for item in data
            if norm(item.get("fornecedor")) == expected["fornecedor"]
            and norm(item.get("colecao")) == expected["colecao"]
            and norm(item.get("ref")).upper() == expected["ref"].upper()
        ]
        critical_results.append({**expected, "ocorrencias": len(matches)})
        if len(matches) != 1:
            failures.append(
                f"Referência crítica {expected['fornecedor']} / {expected['colecao']} / {expected['ref']} "
                f"tem {len(matches)} ocorrência(s); esperado 1"
            )

    # Ensure locally referenced visual assets really exist, including zoom paths.
    missing_assets = []
    external_assets = {"card": 0, "zoom": 0}
    empty_cards = []
    for item in data:
        label = {
            "codigo": norm(item.get("codigo")),
            "fornecedor": norm(item.get("fornecedor")),
            "colecao": norm(item.get("colecao")),
            "ref": norm(item.get("ref")),
        }
        card = norm(item.get("card"))
        if not card:
            empty_cards.append(label)
        for field in ("card", "zoom"):
            value = norm(item.get(field))
            if value.startswith(("http://", "https://")):
                external_assets[field] += 1
                continue
            path = local_path(value)
            if path is not None and not path.is_file():
                missing_assets.append({**label, "campo": field, "caminho": value})

    if empty_cards:
        failures.append(f"Há {len(empty_cards)} item(ns) sem card")
    if missing_assets:
        failures.append(f"Há {len(missing_assets)} caminho(s) local(is) de imagem inexistente(s)")

    # Search regression: critical references must be searchable by their exact reference.
    search_failures = []
    for expected in CRITICAL_REFS:
        ref = expected["ref"]
        matches = [
            item for item in data
            if norm(item.get("fornecedor")) == expected["fornecedor"]
            and norm(item.get("colecao")) == expected["colecao"]
            and norm(item.get("ref")).upper() == ref.upper()
        ]
        if len(matches) == 1:
            search_blob = norm(matches[0].get("search")).casefold()
            if ref.casefold() not in search_blob:
                search_failures.append(ref)
    if search_failures:
        failures.append(f"Referências críticas não localizáveis pelo campo search: {search_failures}")

    report = {
        "status": "ok" if not failures else "falha",
        "itens_data": len(data),
        "itens_inventario": expected_inventory,
        "itens_consolidado": expected_consolidated,
        "fornecedores_data": dict(sorted(supplier_counts.items())),
        "ui_markers_ausentes": missing_ui,
        "referencias_criticas": critical_results,
        "referencias_criticas_search_falhou": search_failures,
        "cards_vazios": len(empty_cards),
        "assets_locais_faltantes": len(missing_assets),
        "assets_locais_faltantes_amostra": missing_assets[:30],
        "assets_externos": external_assets,
        "falhas": failures,
        "avisos": warnings,
        "criterio": "Smoke test do catálogo publicado: estrutura DATA, consistência com relatórios, controles de busca/filtro, referências críticas reparadas e existência dos assets locais de card/zoom. Não altera produtos nem imagens.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))

    if failures:
        raise SystemExit("; ".join(failures))


if __name__ == "__main__":
    main()
