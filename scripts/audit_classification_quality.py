from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "classificacao" / "catalogo-classificacao.json"
REPORT = ROOT / "auditoria-classificacao-qualidade.json"


def main() -> None:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    items = payload.get("itens") or []
    if len(items) != 1212:
        raise RuntimeError(f"Esperados 1212 itens, encontrado {len(items)}")

    any_color = Counter()
    secondary_color = Counter()
    tag_count = Counter()
    status_count = Counter()
    tone_count = Counter()
    examples_by_color: dict[str, list[dict]] = defaultdict(list)
    review_examples = []

    for item in items:
        color = item.get("cor") or {}
        status = str(color.get("status") or "")
        status_count[status] += 1
        tone = color.get("tonalidade")
        if tone:
            tone_count[str(tone)] += 1
        tags = color.get("cores") or []
        tag_count[len(tags)] += 1
        for idx, tag in enumerate(tags):
            name = str(tag.get("nome") or "")
            if not name:
                continue
            any_color[name] += 1
            if idx > 0:
                secondary_color[name] += 1
            row = {
                "codigo": item.get("codigo"),
                "ref": item.get("ref"),
                "fornecedor": item.get("fornecedor"),
                "colecao": item.get("colecao"),
                "posicao": idx + 1,
                "participacao_media": tag.get("participacao_media"),
            }
            examples_by_color[name].append(row)

        if status == "revisao_automatica":
            consensus = color.get("consenso") or {}
            review_examples.append({
                "codigo": item.get("codigo"),
                "ref": item.get("ref"),
                "fornecedor": item.get("fornecedor"),
                "colecao": item.get("colecao"),
                "pixels": consensus.get("cor_principal_pixels"),
                "paleta": consensus.get("cor_principal_paleta"),
                "ranking_pixels": consensus.get("ranking_pixels"),
                "ranking_paleta": consensus.get("ranking_paleta"),
            })

    # Exemplos mais fortes por família, úteis para auditoria sem alterar classificação.
    compact_examples = {}
    for name, rows in examples_by_color.items():
        rows.sort(key=lambda x: (x["posicao"], -(x["participacao_media"] or 0), str(x["codigo"])))
        compact_examples[name] = rows[:8]

    report = {
        "status": "ok",
        "itens": len(items),
        "status_cor": dict(status_count.most_common()),
        "quantidade_tags_cor_por_item": {str(k): v for k, v in sorted(tag_count.items())},
        "familias_em_qualquer_posicao": dict(any_color.most_common()),
        "familias_como_secundaria_ou_terciaria": dict(secondary_color.most_common()),
        "tonalidades": dict(tone_count.most_common()),
        "exemplos_fortes_por_familia": compact_examples,
        "amostra_revisao_automatica": review_examples[:30],
        "criterio": "Auditoria de cobertura das tags de cor já calculadas. Não altera classificação nem catálogo.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "familias_em_qualquer_posicao": report["familias_em_qualquer_posicao"],
        "quantidade_tags_cor_por_item": report["quantidade_tags_cor_por_item"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
