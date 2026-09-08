from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-catalogo-atual.json"


def parse_data() -> list[dict]:
    html = INDEX.read_text(encoding="utf-8")
    marker = "let DATA="
    start = html.index(marker) + len(marker)
    data, _ = json.JSONDecoder().raw_decode(html[start:])
    if not isinstance(data, list) or not data:
        raise RuntimeError("DATA do catálogo está vazio ou inválido")
    return data


def norm(value: object) -> str:
    return str(value or "").strip()


def is_external(path: str) -> bool:
    return path.startswith(("http://", "https://"))


def main() -> None:
    data = parse_data()
    by_collection: dict[tuple[str, str], list[dict]] = defaultdict(list)
    supplier_counts: Counter[str] = Counter()
    codes: list[str] = []
    missing_local_cards: list[dict] = []
    external_cards = 0
    local_cards = 0

    for item in data:
        supplier = norm(item.get("fornecedor")) or "Sem fornecedor"
        collection = norm(item.get("colecao")) or "Sem coleção"
        by_collection[(supplier, collection)].append(item)
        supplier_counts[supplier] += 1

        code = norm(item.get("codigo"))
        if code:
            codes.append(code)

        card = norm(item.get("card"))
        if is_external(card):
            external_cards += 1
        elif card:
            local_cards += 1
            local_path = ROOT / card.split("?", 1)[0]
            if not local_path.is_file():
                missing_local_cards.append({
                    "codigo": code,
                    "fornecedor": supplier,
                    "colecao": collection,
                    "ref": norm(item.get("ref")),
                    "card": card,
                })

    duplicate_codes = sorted(code for code, count in Counter(codes).items() if count > 1)
    rows = []
    duplicate_refs_total = 0

    for (supplier, collection), items in sorted(by_collection.items()):
        refs = [norm(item.get("ref")) for item in items if norm(item.get("ref"))]
        ref_counts = Counter(refs)
        duplicate_refs = sorted(ref for ref, count in ref_counts.items() if count > 1)
        duplicate_refs_total += len(duplicate_refs)
        rows.append({
            "fornecedor": supplier,
            "colecao": collection,
            "itens": len(items),
            "referencias_unicas": len(set(refs)),
            "referencias_vazias": len(items) - len(refs),
            "refs_duplicadas": duplicate_refs,
        })

    report = {
        "itens_catalogo": len(data),
        "fornecedores": dict(sorted(supplier_counts.items())),
        "total_fornecedores": len(supplier_counts),
        "total_colecoes": len(rows),
        "imagens_card_locais": local_cards,
        "imagens_card_externas": external_cards,
        "imagens_card_locais_faltantes": len(missing_local_cards),
        "cards_locais_faltantes": missing_local_cards,
        "codigos_duplicados": duplicate_codes,
        "colecoes_com_refs_duplicadas": sum(1 for row in rows if row["refs_duplicadas"]),
        "total_refs_duplicadas": duplicate_refs_total,
        "colecoes": rows,
        "criterio": "Inventário do DATA atualmente publicado. Não usa a biblioteca-base como fonte de completude; serve para registrar o estado real do catálogo antes da comparação com fontes oficiais.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "itens_catalogo": report["itens_catalogo"],
        "total_fornecedores": report["total_fornecedores"],
        "total_colecoes": report["total_colecoes"],
        "imagens_card_locais_faltantes": report["imagens_card_locais_faltantes"],
        "codigos_duplicados": len(duplicate_codes),
        "total_refs_duplicadas": duplicate_refs_total,
    }
    print(json.dumps(summary, ensure_ascii=False))

    if missing_local_cards:
        raise SystemExit("Falha: há imagens locais referenciadas que não existem")
    if duplicate_codes:
        raise SystemExit("Falha: há códigos FK duplicados")
    if duplicate_refs_total:
        raise SystemExit("Falha: há referências duplicadas dentro de uma coleção")


if __name__ == "__main__":
    main()
