from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "classificacao" / "amostra-estilo-clip.json"
REPORT = ROOT / "auditoria-estilo-qualidade.json"

ANCHORS = {
    "Tartan": {"aceitos": {"Xadrez"}, "descricao": "book de padrão tartan/xadrez"},
    "HF Texture III": {"aceitos": {"Textura", "Liso"}, "descricao": "book explicitamente de textura"},
    "Texture II": {"aceitos": {"Textura", "Liso"}, "descricao": "book explicitamente de textura"},
    "Texture III": {"aceitos": {"Textura", "Liso"}, "descricao": "book explicitamente de textura"},
    "Tramas": {"aceitos": {"Textura", "Liso"}, "descricao": "book de tramas/texturas"},
    "Flora": {"aceitos": {"Floral", "Botânico/Folhagem", "Liso", "Textura"}, "descricao": "book Flora; floral/botânico, com possíveis coordenados lisos/texturizados"},
}


def main() -> None:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    items = payload.get("itens") or []
    if not items:
        raise RuntimeError("Amostra de estilo vazia")

    by_collection: dict[str, Counter[str]] = defaultdict(Counter)
    total_by_collection: Counter[str] = Counter()
    stable_by_collection: Counter[str] = Counter()
    strong_by_collection: Counter[str] = Counter()
    top1_all_by_collection: dict[str, Counter[str]] = defaultdict(Counter)

    for item in items:
        collection = str(item.get("colecao") or "")
        total_by_collection[collection] += 1
        if item.get("estavel_3_de_3"):
            stable_by_collection[collection] += 1
        tops = item.get("views_top1") or []
        if tops:
            top1_all_by_collection[collection][str(tops[0])] += 1
        candidate = item.get("candidato_forte")
        if candidate:
            strong_by_collection[collection] += 1
            by_collection[collection][str(candidate)] += 1

    collections = {}
    for collection in sorted(total_by_collection):
        total = total_by_collection[collection]
        collections[collection] = {
            "amostra": total,
            "estaveis": stable_by_collection[collection],
            "fortes": strong_by_collection[collection],
            "candidatos_fortes": dict(by_collection[collection].most_common()),
            "top1_primeira_view": dict(top1_all_by_collection[collection].most_common()),
        }

    anchor_results = {}
    for collection, rule in ANCHORS.items():
        total = total_by_collection.get(collection, 0)
        strong = strong_by_collection.get(collection, 0)
        accepted_strong = sum(by_collection[collection][tag] for tag in rule["aceitos"])
        anchor_results[collection] = {
            "descricao": rule["descricao"],
            "amostra": total,
            "candidatos_fortes": strong,
            "fortes_compativeis": accepted_strong,
            "taxa_compativel_sobre_fortes": round(accepted_strong / strong, 3) if strong else None,
            "tags_aceitas": sorted(rule["aceitos"]),
            "distribuicao": dict(by_collection[collection].most_common()),
        }

    report = {
        "status": "ok",
        "itens_amostra": len(items),
        "colecoes": collections,
        "ancoras": anchor_results,
        "conclusao_metodologica": (
            "Esta auditoria serve para detectar viés do classificador top-1. A próxima versão deve tratar estilos como tags independentes/multirrótulo, "
            "porque categorias como Floral/Botânico e Xadrez/Geométrico podem coexistir."
        ),
        "publicado_no_catalogo": False,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(anchor_results, ensure_ascii=False))


if __name__ == "__main__":
    main()
