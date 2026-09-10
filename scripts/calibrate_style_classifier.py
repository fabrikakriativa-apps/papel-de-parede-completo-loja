from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import torch
from PIL import Image, ImageOps
from transformers import CLIPModel, CLIPProcessor

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
OUT = ROOT / "classificacao" / "amostra-estilo-clip.json"
REPORT = ROOT / "auditoria-estilo-calibracao.json"
MODEL_ID = "openai/clip-vit-base-patch32"
SAMPLE_PER_COLLECTION = 6

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
    return data


def is_external(path: str) -> bool:
    return path.startswith(("http://", "https://"))


def select_sample(data: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in data:
        card = str(item.get("card") or "").strip()
        if not card or is_external(card):
            continue
        path = ROOT / card.split("?", 1)[0]
        if not path.is_file():
            continue
        key = (str(item.get("fornecedor") or ""), str(item.get("colecao") or ""))
        groups[key].append(item)

    selected = []
    for key in sorted(groups):
        # Deduplica imagens repetidas dentro do book para não calibrar em cópias do mesmo asset.
        unique = []
        seen_cards = set()
        for item in sorted(groups[key], key=lambda x: str(x.get("codigo") or "")):
            card = str(item.get("card") or "")
            if card in seen_cards:
                continue
            seen_cards.add(card)
            unique.append(item)
        if not unique:
            continue
        n = min(SAMPLE_PER_COLLECTION, len(unique))
        if n == 1:
            indices = [0]
        else:
            indices = sorted({round(i * (len(unique) - 1) / (n - 1)) for i in range(n)})
        selected.extend(unique[i] for i in indices)
    return selected


def load_views(path: Path) -> list[Image.Image]:
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
    w, h = image.size
    side = min(w, h)
    full = ImageOps.fit(image, (224, 224), method=Image.Resampling.LANCZOS)
    center80 = image.crop((
        int(w * 0.10), int(h * 0.10), max(int(w * 0.90), int(w * 0.10) + 1), max(int(h * 0.90), int(h * 0.10) + 1)
    ))
    center80 = ImageOps.fit(center80, (224, 224), method=Image.Resampling.LANCZOS)
    center60 = image.crop((
        int(w * 0.20), int(h * 0.20), max(int(w * 0.80), int(w * 0.20) + 1), max(int(h * 0.80), int(h * 0.20) + 1)
    ))
    center60 = ImageOps.fit(center60, (224, 224), method=Image.Resampling.LANCZOS)
    return [full, center80, center60]


def main() -> None:
    torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
    data = parse_data()
    sample = select_sample(data)
    if len(sample) < 100:
        raise RuntimeError(f"Amostra pequena demais: {len(sample)}")

    styles = list(STYLE_PROMPTS)
    prompts = [prompt for style in styles for prompt in STYLE_PROMPTS[style]]
    prompt_style_index = [styles.index(style) for style in styles for _ in STYLE_PROMPTS[style]]

    processor = CLIPProcessor.from_pretrained(MODEL_ID)
    model = CLIPModel.from_pretrained(MODEL_ID)
    model.eval()

    text_inputs = processor(text=prompts, return_tensors="pt", padding=True)
    with torch.no_grad():
        text_features = model.get_text_features(**text_inputs)
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)

    rows = []
    stable_count = 0
    strong_count = 0
    label_counts = Counter()
    collection_stability: Counter[str] = Counter()
    collection_total: Counter[str] = Counter()
    margins = []

    for pos, item in enumerate(sample, start=1):
        card = str(item.get("card") or "")
        path = ROOT / card.split("?", 1)[0]
        views = load_views(path)
        image_inputs = processor(images=views, return_tensors="pt")
        with torch.no_grad():
            image_features = model.get_image_features(**image_inputs)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            similarities = image_features @ text_features.T

        # Média dos três prompts de cada estilo, para cada enquadramento.
        view_style_scores = []
        for view_idx in range(similarities.shape[0]):
            scores = []
            for style_idx, style in enumerate(styles):
                cols = [i for i, idx in enumerate(prompt_style_index) if idx == style_idx]
                score = similarities[view_idx, cols].mean().item()
                scores.append((style, score))
            scores.sort(key=lambda x: -x[1])
            view_style_scores.append(scores)

        tops = [scores[0][0] for scores in view_style_scores]
        stable = len(set(tops)) == 1

        avg_scores = []
        for style in styles:
            vals = []
            for scores in view_style_scores:
                vals.append(dict(scores)[style])
            avg_scores.append((style, sum(vals) / len(vals), min(vals), max(vals)))
        avg_scores.sort(key=lambda x: -x[1])
        margin = avg_scores[0][1] - avg_scores[1][1]
        margins.append(margin)

        # Ainda é calibração: candidato forte exige 3/3 views e margem conservadora.
        strong = stable and margin >= 0.010
        candidate = avg_scores[0][0] if strong else None
        collection = str(item.get("colecao") or "")
        collection_total[collection] += 1
        if stable:
            stable_count += 1
            collection_stability[collection] += 1
        if strong:
            strong_count += 1
            label_counts[candidate] += 1

        rows.append({
            "codigo": item.get("codigo"),
            "ref": item.get("ref"),
            "fornecedor": item.get("fornecedor"),
            "colecao": collection,
            "card": card,
            "views_top1": tops,
            "estavel_3_de_3": stable,
            "margem_top1_top2": round(margin, 5),
            "candidato_forte": candidate,
            "ranking_medio": [
                {"estilo": style, "score": round(avg, 5), "min_view": round(mn, 5), "max_view": round(mx, 5)}
                for style, avg, mn, mx in avg_scores[:5]
            ],
        })
        if pos % 20 == 0:
            print(f"processados {pos}/{len(sample)}")

    margins_sorted = sorted(margins)
    def percentile(q: float) -> float:
        if not margins_sorted:
            return 0.0
        idx = min(len(margins_sorted) - 1, round((len(margins_sorted) - 1) * q))
        return round(margins_sorted[idx], 5)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "status": "calibracao_nao_publicada",
        "model": MODEL_ID,
        "amostra": len(sample),
        "views_por_imagem": 3,
        "taxonomia": styles,
        "itens": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "status": "ok",
        "publicado_no_catalogo": False,
        "modelo": MODEL_ID,
        "itens_amostra": len(sample),
        "colecoes_amostradas": len(collection_total),
        "estaveis_3_de_3": stable_count,
        "taxa_estabilidade": round(stable_count / len(sample), 4),
        "candidatos_fortes_margem_0_010": strong_count,
        "taxa_candidatos_fortes": round(strong_count / len(sample), 4),
        "candidatos_por_estilo": dict(label_counts.most_common()),
        "margem_distribuicao": {
            "p25": percentile(0.25),
            "p50": percentile(0.50),
            "p75": percentile(0.75),
            "p90": percentile(0.90),
        },
        "estabilidade_por_colecao": {
            collection: {
                "estaveis": collection_stability[collection],
                "amostra": collection_total[collection],
                "taxa": round(collection_stability[collection] / collection_total[collection], 3),
            }
            for collection in sorted(collection_total)
        },
        "criterio": "Calibração apenas: 3 enquadramentos por imagem e 3 prompts por classe. Nenhuma tag é gravada no catálogo ou na classificação principal nesta etapa.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
