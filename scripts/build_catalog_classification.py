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
    "Branco/Off-white",
    "Bege/Areia",
    "Greige",
    "Cinza",
    "Preto",
    "Marrom",
    "Verde",
    "Azul",
    "Rosa",
    "Roxo/Lilás",
    "Terracota/Laranja",
    "Amarelo/Dourado",
    "Vermelho/Vinho",
]


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

    # Neutros primeiro. Isso impede que pequenas variações de RGB transformem
    # cinzas, off-whites e greiges em cores cromáticas artificiais.
    if lum < 0.18:
        return "Preto"
    if sat < 0.055:
        return "Branco/Off-white" if lum >= 0.86 else "Cinza"

    # Neutros quentes: off-white, greige, bege e marrom.
    warm = (hue >= 15 or hue <= 5) and hue <= 70
    if sat < 0.18:
        if lum >= 0.90:
            return "Branco/Off-white"
        if warm:
            if lum >= 0.70:
                return "Greige" if sat < 0.11 else "Bege/Areia"
            if lum >= 0.42:
                return "Greige" if sat < 0.10 else "Marrom"
            return "Marrom"
        return "Cinza"

    if 15 <= hue < 45:
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
    return "Vermelho/Vinho"


def analyze_colors(path: Path) -> dict:
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")

    width, height = image.size
    # O miolo reduz influência de bordas, margens e fundos de exportação.
    left = int(width * 0.08)
    top = int(height * 0.08)
    right = max(left + 1, int(width * 0.92))
    bottom = max(top + 1, int(height * 0.92))
    image = image.crop((left, top, right, bottom))
    image.thumbnail((180, 180), Image.Resampling.LANCZOS)

    counts: Counter[str] = Counter()
    luminances: list[float] = []
    for r, g, b in image.getdata():
        counts[rgb_family(r, g, b)] += 1
        luminances.append((0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0)

    total = sum(counts.values())
    if total == 0:
        raise RuntimeError(f"Imagem sem pixels analisáveis: {path}")

    ranked = sorted(counts.items(), key=lambda x: (-x[1], COLOR_ORDER.index(x[0])))
    selected = []
    for name, amount in ranked:
        share = amount / total
        # Não publicamos ruído cromático. A principal sempre entra; as demais
        # precisam representar ao menos 12% da área analisada.
        if not selected or share >= 0.12:
            selected.append({
                "nome": name,
                "participacao": round(share, 4),
                "metodo": "pixel_rule_v1",
            })
        if len(selected) == 3:
            break

    chromatic = {"Verde", "Azul", "Rosa", "Roxo/Lilás", "Terracota/Laranja", "Amarelo/Dourado", "Vermelho/Vinho"}
    chromatic_relevant = [row for row in selected if row["nome"] in chromatic and row["participacao"] >= 0.15]
    multicolor = len(chromatic_relevant) >= 3

    luminances.sort()
    median_lum = luminances[len(luminances) // 2]
    if median_lum >= 0.72:
        tone = "Claro"
    elif median_lum >= 0.42:
        tone = "Médio"
    else:
        tone = "Escuro"

    return {
        "status": "classificado",
        "cores": selected,
        "multicolorido": multicolor,
        "tonalidade": tone,
        "luminancia_mediana": round(median_lum, 4),
        "metodo": "analise_objetiva_pixels_v1",
    }


def main() -> None:
    data = parse_data()
    OUT.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    infant_count = 0
    colors_ok = 0
    colors_external = 0
    colors_error = 0
    color_errors = []
    collection_profile_counts: Counter[str] = Counter()

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
                colors_ok += 1
            except Exception as exc:
                colors_error += 1
                color_errors.append({"codigo": codigo, "ref": ref, "card": card, "erro": str(exc)})
                color = {
                    "status": "erro",
                    "cores": [],
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
        "schema_version": 1,
        "status": "staging_nao_publicado",
        "itens_catalogo": len(data),
        "regras": {
            "perfil_infantil_colecoes": sorted(INFANT_COLLECTIONS),
            "perfil_infantil_confianca": 1.0,
            "cor": "Famílias calculadas por pixels do miolo da imagem; até 3 cores, secundárias apenas com >=12% de participação.",
            "estilo": "Não publicado até calibração de classificador visual com taxonomia fechada.",
        },
        "itens": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
            "classificados_por_pixels": colors_ok,
            "pendentes_asset_externo": colors_external,
            "erros": colors_error,
            "metodo": "analise_objetiva_pixels_v1",
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
