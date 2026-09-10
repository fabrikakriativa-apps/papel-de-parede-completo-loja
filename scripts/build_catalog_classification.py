from __future__ import annotations

import colorsys
import json
import unicodedata
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
OUT = ROOT / "classificacao" / "catalogo-classificacao.json"
REPORT = ROOT / "auditoria-classificacao.json"

INFANT_COLLECTIONS = {
    "bambine",
    "bosque da imaginacao",
    "era uma vez",
    "memorias de infancia",
    "natureza ludica",
    "passeio no campo",
}

COLOR_ORDER = [
    "Branco/Off-white", "Bege/Areia", "Greige", "Cinza", "Preto", "Marrom",
    "Verde", "Azul", "Rosa", "Roxo/Lilás", "Terracota/Laranja",
    "Amarelo/Dourado", "Vermelho/Vinho",
]
CHROMATIC = {
    "Verde", "Azul", "Rosa", "Roxo/Lilás", "Terracota/Laranja",
    "Amarelo/Dourado", "Vermelho/Vinho",
}


def parse_data() -> list[dict]:
    html = INDEX.read_text(encoding="utf-8")
    marker = "let DATA="
    start = html.index(marker) + len(marker)
    data, _ = json.JSONDecoder().raw_decode(html[start:])
    if not isinstance(data, list) or not data:
        raise RuntimeError("DATA do catálogo está vazio ou inválido")
    return data


def norm_text(value: object) -> str:
    text = str(value or "").strip().casefold()
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def norm(value: object) -> str:
    return str(value or "").strip()


def is_external(path: str) -> bool:
    return path.startswith(("http://", "https://"))


def rgb_family(r: int, g: int, b: int) -> str:
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    mx = max(rf, gf, bf)
    mn = min(rf, gf, bf)
    delta = mx - mn
    lum = 0.2126 * rf + 0.7152 * gf + 0.0722 * bf
    sat = 0.0 if mx == 0 else delta / mx
    hue = colorsys.rgb_to_hsv(rf, gf, bf)[0] * 360.0 if delta > 1e-9 else 0.0

    if lum < 0.18:
        return "Preto"
    if sat < 0.055:
        return "Branco/Off-white" if lum >= 0.86 else "Cinza"

    # Pastéis cromáticos precisam ser identificados antes dos neutros. Na versão
    # anterior, rosa/azul/verde muito claros podiam cair em cinza ou greige.
    if sat < 0.18:
        if lum >= 0.93 and sat < 0.08:
            return "Branco/Off-white"
        if 305 <= hue < 360 or 0 <= hue < 8:
            return "Rosa" if lum >= 0.52 else "Vermelho/Vinho"
        if 255 <= hue < 305:
            return "Roxo/Lilás"
        if 170 <= hue < 255:
            return "Azul"
        if 72 <= hue < 170:
            return "Verde"

        # Neutros quentes ficam separados de cinza.
        if 8 <= hue <= 70:
            if lum >= 0.88 and sat < 0.10:
                return "Branco/Off-white"
            if lum >= 0.70:
                return "Greige" if sat < 0.11 else "Bege/Areia"
            if lum >= 0.42:
                return "Greige" if sat < 0.10 else "Marrom"
            return "Marrom"
        return "Cinza"

    if 8 <= hue < 45:
        if lum < 0.48 and sat < 0.65:
            return "Marrom"
        return "Terracota/Laranja"
    if 45 <= hue < 72:
        return "Amarelo/Dourado"
    if 72 <= hue < 170:
        return "Verde"
    if 170 <= hue < 255:
        return "Azul"
    if 255 <= hue < 305:
        return "Roxo/Lilás"
    if 305 <= hue < 345:
        return "Rosa"
    if hue >= 345 or hue < 8:
        # Vermelhos muito claros e suaves funcionam comercialmente como rosa.
        return "Rosa" if lum >= 0.62 and sat < 0.65 else "Vermelho/Vinho"
    return "Vermelho/Vinho"


def rank_family_counts(counts: Counter[str]) -> list[tuple[str, float]]:
    total = sum(counts.values())
    if total <= 0:
        return []
    return sorted(
        ((name, amount / total) for name, amount in counts.items()),
        key=lambda x: (-x[1], COLOR_ORDER.index(x[0])),
    )


def prepare_image(path: Path) -> Image.Image:
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
    width, height = image.size
    left = int(width * 0.08)
    top = int(height * 0.08)
    right = max(left + 1, int(width * 0.92))
    bottom = max(top + 1, int(height * 0.92))
    image = image.crop((left, top, right, bottom))
    image.thumbnail((180, 180), Image.Resampling.LANCZOS)
    return image


def pixel_method(image: Image.Image) -> tuple[Counter[str], list[float]]:
    counts: Counter[str] = Counter()
    luminances: list[float] = []
    for r, g, b in image.getdata():
        counts[rgb_family(r, g, b)] += 1
        luminances.append((0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0)
    return counts, luminances


def palette_method(image: Image.Image) -> Counter[str]:
    quant = image.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = quant.getpalette()
    if palette is None:
        raise RuntimeError("Paleta quantizada ausente")
    counts: Counter[str] = Counter()
    for amount, palette_index in quant.getcolors(maxcolors=256) or []:
        offset = palette_index * 3
        r, g, b = palette[offset:offset + 3]
        counts[rgb_family(r, g, b)] += amount
    return counts


def analyze_colors(path: Path) -> dict:
    image = prepare_image(path)
    pixel_counts, luminances = pixel_method(image)
    palette_counts = palette_method(image)
    pixel_rank = rank_family_counts(pixel_counts)
    palette_rank = rank_family_counts(palette_counts)
    if not pixel_rank or not palette_rank:
        raise RuntimeError(f"Imagem sem pixels analisáveis: {path}")

    pixel_map = dict(pixel_rank)
    palette_map = dict(palette_rank)
    primary_pixel = pixel_rank[0][0]
    primary_palette = palette_rank[0][0]
    primary_agreement = primary_pixel == primary_palette

    accepted = []
    if primary_agreement:
        candidates = []
        for name in COLOR_ORDER:
            p1 = pixel_map.get(name, 0.0)
            p2 = palette_map.get(name, 0.0)
            if name == primary_pixel:
                relevant = True
            elif name in CHROMATIC:
                # Cor de destaque é útil ao arquiteto mesmo ocupando área menor;
                # ainda exige confirmação independente nos dois métodos.
                relevant = p1 >= 0.06 and p2 >= 0.05
            else:
                relevant = p1 >= 0.12 and p2 >= 0.10
            if relevant:
                candidates.append((name, (p1 + p2) / 2.0, p1, p2))
        candidates.sort(key=lambda x: (-x[1], COLOR_ORDER.index(x[0])))
        for name, avg, p1, p2 in candidates[:3]:
            accepted.append({
                "nome": name,
                "participacao_media": round(avg, 4),
                "participacao_pixels": round(p1, 4),
                "participacao_paleta": round(p2, 4),
                "papel": "principal" if name == primary_pixel else "destaque",
                "metodo": "consenso_pixels_paleta_v3",
            })

    luminances.sort()
    median_lum = luminances[len(luminances) // 2]
    if median_lum >= 0.72:
        tone = "Claro"
    elif median_lum >= 0.42:
        tone = "Médio"
    else:
        tone = "Escuro"

    if primary_agreement and accepted:
        primary_share = accepted[0]["participacao_media"]
        confidence = 0.98 if primary_share >= 0.45 else 0.95 if primary_share >= 0.30 else 0.92
        status = "validado_consenso"
    else:
        confidence = None
        status = "revisao_automatica"

    chromatic_relevant = [
        row for row in accepted
        if row["nome"] in CHROMATIC and row["participacao_media"] >= 0.055
    ]

    return {
        "status": status,
        "cores": accepted,
        "confianca": confidence,
        "multicolorido": len(chromatic_relevant) >= 3 if accepted else None,
        "tonalidade": tone,
        "luminancia_mediana": round(median_lum, 4),
        "consenso": {
            "cor_principal_pixels": primary_pixel,
            "cor_principal_paleta": primary_palette,
            "acordo_principal": primary_agreement,
            "ranking_pixels": [{"nome": n, "participacao": round(v, 4)} for n, v in pixel_rank[:4]],
            "ranking_paleta": [{"nome": n, "participacao": round(v, 4)} for n, v in palette_rank[:4]],
        },
        "metodo": "consenso_objetivo_cor_v3",
    }


def main() -> None:
    data = parse_data()
    OUT.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    infant_count = 0
    colors_consensus = 0
    colors_review = 0
    colors_external = 0
    colors_error = 0
    color_errors = []
    collection_profile_counts: Counter[str] = Counter()
    primary_counts: Counter[str] = Counter()
    tone_counts: Counter[str] = Counter()
    review_by_collection: Counter[str] = Counter()

    for item in data:
        codigo = norm(item.get("codigo"))
        ref = norm(item.get("ref"))
        supplier = norm(item.get("fornecedor"))
        collection = norm(item.get("colecao"))
        card = norm(item.get("card"))

        infant = norm_text(collection) in INFANT_COLLECTIONS
        if infant:
            infant_count += 1
            collection_profile_counts[collection] += 1
            profile = {
                "tags": ["Infantil"],
                "confianca": 1.0,
                "metodo": "regra_colecao",
                "proveniencia": f"Coleção integralmente infantil: {collection}",
            }
        else:
            profile = {
                "tags": [],
                "confianca": None,
                "metodo": "nao_inferido",
                "proveniencia": "Nenhum perfil inferido visualmente nesta etapa.",
            }

        if is_external(card):
            colors_external += 1
            color = {
                "status": "pendente_asset_externo",
                "cores": [],
                "confianca": None,
                "multicolorido": None,
                "tonalidade": None,
                "metodo": "nao_classificado",
            }
        else:
            local = ROOT / card.split("?", 1)[0]
            try:
                if not local.is_file():
                    raise FileNotFoundError(local)
                color = analyze_colors(local)
                tone_counts[color["tonalidade"]] += 1
                if color["status"] == "validado_consenso":
                    colors_consensus += 1
                    primary_counts[color["cores"][0]["nome"]] += 1
                else:
                    colors_review += 1
                    review_by_collection[collection] += 1
            except Exception as exc:
                colors_error += 1
                color_errors.append({"codigo": codigo, "ref": ref, "card": card, "erro": str(exc)})
                color = {
                    "status": "erro",
                    "cores": [],
                    "confianca": None,
                    "multicolorido": None,
                    "tonalidade": None,
                    "metodo": "nao_classificado",
                    "erro": str(exc),
                }

        rows.append({
            "codigo": codigo,
            "ref": ref,
            "fornecedor": supplier,
            "colecao": collection,
            "perfil": profile,
            "cor": color,
            "estilo": {
                "status": "aguardando_calibracao_visual",
                "tags": [],
                "metodo": "nao_publicado",
                "taxonomia_prevista": [
                    "Liso", "Textura", "Floral", "Botânico/Folhagem", "Geométrico",
                    "Listrado", "Xadrez", "Abstrato", "Clássico", "Temático"
                ],
            },
            "publicavel": False,
        })

    if len(rows) != len(data):
        raise RuntimeError("Quantidade da classificação diverge do catálogo")
    if infant_count != 280:
        raise RuntimeError(f"Esperados 280 itens infantis pelas seis coleções; encontrado {infant_count}")
    if colors_error:
        raise RuntimeError(f"Falha ao analisar {colors_error} imagens locais; amostra: {color_errors[:5]}")

    payload = {
        "schema_version": 3,
        "status": "staging_nao_publicado",
        "itens_catalogo": len(data),
        "regras": {
            "perfil_infantil_colecoes": sorted(INFANT_COLLECTIONS),
            "perfil_infantil_confianca": 1.0,
            "cor": "Cor principal exige consenso entre pixels e paleta quantizada. Pastéis cromáticos são preservados antes dos neutros; cores cromáticas de destaque exigem presença em ambos os métodos.",
            "estilo": "Não publicado até calibração de classificador visual com taxonomia fechada.",
        },
        "itens": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    local_total = colors_consensus + colors_review
    report = {
        "status": "ok",
        "camada_publicada_no_catalogo": False,
        "itens_catalogo": len(data),
        "itens_classificacao": len(rows),
        "perfil_infantil": {
            "itens": infant_count,
            "colecoes": dict(sorted(collection_profile_counts.items())),
            "metodo": "regra_colecao",
            "confianca": 1.0,
        },
        "cor": {
            "assets_locais_analisados": local_total,
            "validados_por_consenso": colors_consensus,
            "revisao_automatica": colors_review,
            "taxa_consenso": round(colors_consensus / local_total, 4) if local_total else 0.0,
            "pendentes_asset_externo": colors_external,
            "erros": colors_error,
            "cores_primarias_validadas": dict(primary_counts.most_common()),
            "tonalidades": dict(tone_counts.most_common()),
            "revisoes_por_colecao": dict(review_by_collection.most_common()),
            "metodo": "consenso_objetivo_cor_v3",
        },
        "estilo": {
            "status": "nao_publicado",
            "motivo": "Aguardando calibração visual; nenhuma tag de estilo é inferida livremente.",
        },
        "seguranca": "Este processo não altera index.html, filtros, produtos, códigos, imagens ou a URL publicada.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
