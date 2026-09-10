from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import torch
from PIL import Image, ImageOps
from transformers import CLIPModel, CLIPProcessor

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
OUT = ROOT / "classificacao" / "catalogo-estilo.json"
REPORT = ROOT / "auditoria-estilo-classificacao.json"
MODEL_ID = "openai/clip-vit-base-patch32"
BATCH_IMAGES = 16
SEED_MARGIN = 0.012
VERY_STRONG_MARGIN = 0.035
K_NEIGHBORS = 5

STYLE_PROMPTS = {
    "Liso": [
        "a plain solid color wallpaper with no visible pattern",
        "a smooth uniform wallpaper surface without motifs",
        "a minimal plain wallpaper sample with an even color",
    ],
    "Textura": [
        "a wallpaper with subtle material texture like linen fabric plaster or fibers",
        "a textured wallpaper surface imitating fabric stone plaster or woven fibers",
        "a wallpaper sample whose main feature is surface texture rather than a printed motif",
    ],
    "Floral": [
        "a floral wallpaper pattern with flowers as the main motif",
        "a decorative wallpaper covered with flower blossoms",
        "a wallpaper design dominated by flowers and floral arrangements",
    ],
    "Botânico/Folhagem": [
        "a botanical foliage wallpaper with leaves and branches as the main motif",
        "a wallpaper pattern dominated by leaves plants branches or tropical foliage",
        "a botanical wallpaper design focused on greenery and leaf shapes",
    ],
    "Geométrico": [
        "a geometric wallpaper pattern with repeated shapes lines circles or polygons",
        "a wallpaper design dominated by regular geometric forms",
        "a repeating geometric wall covering pattern",
    ],
    "Listrado": [
        "a striped wallpaper with repeating vertical horizontal or diagonal stripes",
        "a wallpaper design dominated by parallel stripes",
        "a repeating stripe wall covering pattern",
    ],
    "Xadrez": [
        "a plaid or checkered wallpaper pattern with crossing bands or squares",
        "a tartan check wallpaper design",
        "a wallpaper dominated by a plaid or checker pattern",
    ],
    "Abstrato": [
        "an abstract wallpaper pattern with irregular artistic shapes and forms",
        "a non figurative abstract wall covering design",
        "an expressive abstract wallpaper without a literal repeated object",
    ],
    "Clássico": [
        "a classic ornamental wallpaper with damask arabesque medallion or traditional motifs",
        "a traditional elegant wallpaper with ornate symmetrical decoration",
        "a classic decorative wall covering with damask or arabesque ornament",
    ],
    "Temático": [
        "a figurative themed wallpaper with animals objects buildings landscapes maps or illustrations",
        "a wallpaper telling a visual theme or scene with recognizable figures or objects",
        "an illustrated themed wall covering with recognizable subjects",
    ],
}


def parse_data() -> list[dict]:
    text = INDEX.read_text(encoding="utf-8")
    marker = "let DATA="
    start = text.index(marker) + len(marker)
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(data, list) or not data:
        raise RuntimeError("DATA vazio ou inválido")
    return data


def external(path: str) -> bool:
    return path.startswith(("http://", "https://"))


def load_views(path: Path) -> list[Image.Image]:
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
    w, h = image.size
    full = ImageOps.fit(image, (224, 224), method=Image.Resampling.LANCZOS)
    crops = [full]
    for margin in (0.10, 0.20):
        crop = image.crop((
            int(w * margin), int(h * margin),
            max(int(w * (1 - margin)), int(w * margin) + 1),
            max(int(h * (1 - margin)), int(h * margin) + 1),
        ))
        crops.append(ImageOps.fit(crop, (224, 224), method=Image.Resampling.LANCZOS))
    return crops


def build_text_features(model: CLIPModel, processor: CLIPProcessor, styles: list[str]) -> tuple[torch.Tensor, list[int]]:
    prompts = [p for style in styles for p in STYLE_PROMPTS[style]]
    style_index = [styles.index(style) for style in styles for _ in STYLE_PROMPTS[style]]
    inputs = processor(text=prompts, return_tensors="pt", padding=True)
    with torch.inference_mode():
        features = model.get_text_features(**inputs)
        features = features / features.norm(dim=-1, keepdim=True)
    return features, style_index


def score_views(similarities: torch.Tensor, styles: list[str], prompt_style_index: list[int]) -> tuple[list[str], list[tuple[str, float]], float]:
    per_view = []
    for view_idx in range(similarities.shape[0]):
        scores = []
        for style_idx, style in enumerate(styles):
            cols = [i for i, idx in enumerate(prompt_style_index) if idx == style_idx]
            scores.append((style, similarities[view_idx, cols].mean().item()))
        scores.sort(key=lambda x: -x[1])
        per_view.append(scores)

    tops = [scores[0][0] for scores in per_view]
    averages = []
    for style in styles:
        vals = [dict(scores)[style] for scores in per_view]
        averages.append((style, sum(vals) / len(vals)))
    averages.sort(key=lambda x: -x[1])
    margin = averages[0][1] - averages[1][1]
    return tops, averages, margin


def main() -> None:
    torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
    data = parse_data()
    styles = list(STYLE_PROMPTS)

    # Uma inferência por arquivo visual único; referências que compartilham asset
    # recebem necessariamente a mesma leitura visual.
    path_to_items: dict[str, list[dict]] = defaultdict(list)
    external_items = []
    for item in data:
        card = str(item.get("card") or "").strip()
        if not card or external(card):
            external_items.append(item)
            continue
        path = ROOT / card.split("?", 1)[0]
        if not path.is_file():
            raise RuntimeError(f"Asset local ausente: {card}")
        path_to_items[card].append(item)

    unique_cards = sorted(path_to_items)
    processor = CLIPProcessor.from_pretrained(MODEL_ID)
    model = CLIPModel.from_pretrained(MODEL_ID)
    model.eval()
    text_features, prompt_style_index = build_text_features(model, processor, styles)

    visual_rows = {}
    embedding_rows = []
    card_order = []

    for start in range(0, len(unique_cards), BATCH_IMAGES):
        cards = unique_cards[start:start + BATCH_IMAGES]
        images = []
        for card in cards:
            images.extend(load_views(ROOT / card.split("?", 1)[0]))
        inputs = processor(images=images, return_tensors="pt")
        with torch.inference_mode():
            features = model.get_image_features(**inputs)
            features = features / features.norm(dim=-1, keepdim=True)
            similarities = features @ text_features.T

        for offset, card in enumerate(cards):
            sl = slice(offset * 3, offset * 3 + 3)
            view_features = features[sl]
            view_sims = similarities[sl]
            tops, avg_scores, margin = score_views(view_sims, styles, prompt_style_index)
            stable = len(set(tops)) == 1
            direct = avg_scores[0][0]
            avg_embedding = view_features.mean(dim=0)
            avg_embedding = avg_embedding / avg_embedding.norm()
            visual_rows[card] = {
                "tops": tops,
                "stable": stable,
                "direct": direct,
                "margin": margin,
                "ranking": avg_scores,
            }
            embedding_rows.append(avg_embedding.cpu())
            card_order.append(card)
        print(f"processados {min(start + len(cards), len(unique_cards))}/{len(unique_cards)} assets únicos")

    embeddings = torch.stack(embedding_rows)
    seeds = [
        i for i, card in enumerate(card_order)
        if visual_rows[card]["stable"] and visual_rows[card]["margin"] >= SEED_MARGIN
    ]
    if len(seeds) < 100:
        raise RuntimeError(f"Poucas sementes fortes para consenso de vizinhança: {len(seeds)}")

    seed_matrix = embeddings[seeds]
    seed_labels = [visual_rows[card_order[i]]["direct"] for i in seeds]

    accepted_cards = 0
    rejected_cards = 0
    very_strong_without_neighbor = 0
    style_counts_assets = Counter()
    neighbor_agreement_distribution = Counter()

    for idx, card in enumerate(card_order):
        visual = visual_rows[card]
        direct_strong = visual["stable"] and visual["margin"] >= SEED_MARGIN
        sims = embeddings[idx] @ seed_matrix.T
        topn = torch.topk(sims, k=min(K_NEIGHBORS + 1, len(seeds))).indices.tolist()

        neighbor_labels = []
        neighbor_sims = []
        for seed_pos in topn:
            seed_global = seeds[seed_pos]
            if seed_global == idx:
                continue
            neighbor_labels.append(seed_labels[seed_pos])
            neighbor_sims.append(float(sims[seed_pos]))
            if len(neighbor_labels) == K_NEIGHBORS:
                break

        votes = Counter(neighbor_labels)
        neighbor_label, neighbor_votes = votes.most_common(1)[0] if votes else (None, 0)
        agreement = neighbor_votes / len(neighbor_labels) if neighbor_labels else 0.0
        neighbor_agreement_distribution[f"{neighbor_votes}/{len(neighbor_labels)}"] += 1

        direct = visual["direct"]
        accepted = False
        reason = ""
        if direct_strong and neighbor_label == direct and agreement >= 0.60:
            accepted = True
            reason = "direto_forte_e_vizinhos_concordam"
        elif visual["stable"] and visual["margin"] >= VERY_STRONG_MARGIN:
            accepted = True
            reason = "direto_muito_forte"
            very_strong_without_neighbor += 1
        else:
            reason = "evidencia_insuficiente"

        tags = []
        confidence = None
        if accepted:
            tags = [direct]
            if direct in {"Xadrez", "Listrado"}:
                tags.append("Geométrico")
            elif direct == "Geométrico":
                tags = ["Geométrico"]
            if reason == "direto_muito_forte":
                confidence = 0.96
            elif agreement >= 0.80 and visual["margin"] >= 0.020:
                confidence = 0.98
            elif agreement >= 0.80:
                confidence = 0.96
            else:
                confidence = 0.93
            accepted_cards += 1
            style_counts_assets.update(tags)
        else:
            rejected_cards += 1

        visual.update({
            "status": "validado_consenso" if accepted else "nao_classificado",
            "tags": tags,
            "confianca": confidence,
            "motivo": reason,
            "vizinhos": {
                "k": len(neighbor_labels),
                "rotulos": neighbor_labels,
                "similaridades": [round(x, 4) for x in neighbor_sims],
                "majoritario": neighbor_label,
                "votos_majoritario": neighbor_votes,
                "acordo": round(agreement, 3),
            },
        })

    items_out = []
    style_counts_items = Counter()
    by_collection = defaultdict(lambda: {"total": 0, "classificados": 0, "tags": Counter()})

    for item in data:
        card = str(item.get("card") or "").strip()
        collection = str(item.get("colecao") or "")
        by_collection[collection]["total"] += 1
        if not card or external(card):
            style = {
                "status": "pendente_asset_externo",
                "tags": [],
                "confianca": None,
                "metodo": "nao_classificado",
            }
        else:
            visual = visual_rows[card]
            tags = visual["tags"]
            if tags:
                by_collection[collection]["classificados"] += 1
                by_collection[collection]["tags"].update(tags)
                style_counts_items.update(tags)
            style = {
                "status": visual["status"],
                "tags": tags,
                "confianca": visual["confianca"],
                "metodo": "clip_3_views_knn_consensus_v1",
                "evidencia": {
                    "top1_por_view": visual["tops"],
                    "margem_top1_top2": round(visual["margin"], 5),
                    "top3_medio": [
                        {"estilo": name, "score": round(score, 5)}
                        for name, score in visual["ranking"][:3]
                    ],
                    "vizinhos": visual["vizinhos"],
                    "motivo": visual["motivo"],
                },
            }

        items_out.append({
            "codigo": item.get("codigo"),
            "ref": item.get("ref"),
            "fornecedor": item.get("fornecedor"),
            "colecao": collection,
            "estilo": style,
        })

    anchors = {}
    anchor_rules = {
        "Tartan": {"Xadrez", "Geométrico"},
        "HF Texture III": {"Textura", "Liso"},
        "Texture II": {"Textura", "Liso"},
        "Texture III": {"Textura", "Liso"},
        "Tramas": {"Textura", "Liso", "Listrado", "Xadrez", "Geométrico"},
        "Flora": {"Floral", "Botânico/Folhagem", "Liso", "Textura"},
    }
    for collection, allowed in anchor_rules.items():
        rows = [row for row in items_out if row["colecao"] == collection and row["estilo"]["tags"]]
        compatible = sum(1 for row in rows if row["estilo"]["tags"][0] in allowed)
        anchors[collection] = {
            "classificados": len(rows),
            "compativeis": compatible,
            "taxa_compativel": round(compatible / len(rows), 3) if rows else None,
            "aceitos": sorted(allowed),
        }

    OUT.write_text(json.dumps({
        "schema_version": 1,
        "status": "staging_nao_publicado",
        "modelo": MODEL_ID,
        "metodo": "clip_3_views_knn_consensus_v1",
        "regras": {
            "semente": f"3/3 views iguais e margem >= {SEED_MARGIN}",
            "aceite": "predição direta forte + pelo menos 60% dos 5 vizinhos fortes com o mesmo rótulo; ou margem visual muito forte >= 0.035",
            "hierarquia": "Xadrez e Listrado adicionam também Geométrico",
        },
        "itens": items_out,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    collections_report = {}
    for collection, stats in sorted(by_collection.items()):
        total = stats["total"]
        classified = stats["classificados"]
        collections_report[collection] = {
            "total": total,
            "classificados": classified,
            "taxa": round(classified / total, 3) if total else 0,
            "tags": dict(stats["tags"].most_common()),
        }

    REPORT.write_text(json.dumps({
        "status": "ok",
        "publicado_no_catalogo": False,
        "itens_catalogo": len(data),
        "assets_unicos_locais": len(unique_cards),
        "itens_asset_externo": len(external_items),
        "sementes_fortes": len(seeds),
        "assets_estilo_validado": accepted_cards,
        "assets_nao_classificados": rejected_cards,
        "taxa_assets_validada": round(accepted_cards / len(unique_cards), 4),
        "aceites_por_margem_muito_forte": very_strong_without_neighbor,
        "tags_por_asset": dict(style_counts_assets.most_common()),
        "tags_por_item": dict(style_counts_items.most_common()),
        "acordo_vizinhos": dict(neighbor_agreement_distribution.most_common()),
        "colecoes": collections_report,
        "ancoras": anchors,
        "criterio": "Classificação conservadora: nenhuma tag é publicada no catálogo. Itens sem consenso permanecem sem estilo em vez de receber rótulo forçado.",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "assets_unicos_locais": len(unique_cards),
        "sementes": len(seeds),
        "validados": accepted_cards,
        "nao_classificados": rejected_cards,
        "tags": dict(style_counts_assets.most_common()),
        "ancoras": anchors,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
