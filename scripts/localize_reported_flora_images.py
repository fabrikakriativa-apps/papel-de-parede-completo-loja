from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-flora-imagens-localizadas.json"

TARGETS = {
    "FK-0371": {
        "ref": "84384",
        "local": "imagens/home-finish/flora/thumbnails/84384.jpg",
        "source_kind": "validated_alias",
        "source_local": "imagens/home-finish/flora/thumbnails/84391.jpg",
        "source_alias_peer": "84391",
    },
    "FK-0380": {
        "ref": "84858",
        "local": "imagens/home-finish/flora/thumbnails/84858.jpg",
        "source_kind": "validated_original",
        "source_library": "imagens/home-finish/flora/originals/84858.jpg",
    },
}


def parse_data(text: str) -> list[dict]:
    marker = "let DATA="
    start = text.index(marker) + len(marker)
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    return data


def validate_image(path: Path, min_bytes: int = 5_000) -> dict:
    payload = path.read_bytes()
    if len(payload) < min_bytes:
        raise RuntimeError(f"{path}: imagem pequena demais ({len(payload)} bytes)")
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        width, height = im.size
        fmt = (im.format or "").upper()
        if width < 400 or height < 400:
            raise RuntimeError(f"{path}: dimensões pequenas demais {width}x{height}")
        rgb = im.convert("RGB").resize((64, 64))
        spread = sum(ImageStat.Stat(rgb).stddev)
    return {
        "bytes": len(payload),
        "width": width,
        "height": height,
        "format": fmt,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "pixel_stddev_sum": round(spread, 2),
    }


def load_validated_map(source_root: Path) -> dict:
    part = source_root / "dados/home-finish-urls/part-03.json"
    if not part.exists():
        raise RuntimeError(f"Biblioteca-fonte ausente: {part}")
    return json.loads(part.read_text(encoding="utf-8"))["items"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    args = parser.parse_args()
    source_root = Path(args.source_root).resolve()

    validated = load_validated_map(source_root)

    a84384 = validated.get("Flora|84384")
    a84391 = validated.get("Flora|84391")
    if not a84384 or not a84391 or a84384.get("url") != "i224" or a84391.get("url") != "i224":
        raise RuntimeError("Fonte validada não confirma o alias compartilhado i224 para 84384/84391")

    a84858 = validated.get("Flora|84858")
    if not a84858 or a84858.get("url") != "i229":
        raise RuntimeError("Fonte validada não confirma Flora|84858 como i229")

    original_text = INDEX.read_text(encoding="utf-8")
    data = parse_data(original_text)

    for codigo, target in TARGETS.items():
        matches = [x for x in data if str(x.get("codigo") or "") == codigo]
        if len(matches) != 1:
            raise RuntimeError(f"{codigo}: esperado 1 item, encontrado {len(matches)}")
        item = matches[0]
        expected = {"fornecedor": "Home Finish", "colecao": "Flora", "ref": target["ref"]}
        for field, value in expected.items():
            if str(item.get(field) or "") != value:
                raise RuntimeError(f"{codigo}: {field}={item.get(field)!r}, esperado {value!r}")

    source_84384 = ROOT / TARGETS["FK-0371"]["source_local"]
    source_84858 = source_root / TARGETS["FK-0380"]["source_library"]

    meta_84384 = validate_image(source_84384)
    meta_84858 = validate_image(source_84858)

    text = original_text
    rows = []

    try:
        copies = {
            "FK-0371": (source_84384, meta_84384),
            "FK-0380": (source_84858, meta_84858),
        }

        for codigo, target in TARGETS.items():
            src, meta = copies[codigo]
            dest = ROOT / target["local"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            dest_meta = validate_image(dest)
            if dest_meta["sha256"] != meta["sha256"]:
                raise RuntimeError(f"{codigo}: checksum divergiu após cópia")

            item = next(x for x in data if str(x.get("codigo") or "") == codigo)
            current_card = str(item.get("card") or "")
            current_zoom = str(item.get("zoom") or "")
            if current_card != current_zoom:
                raise RuntimeError(f"{codigo}: card e zoom divergentes")

            old_json = json.dumps(current_card, ensure_ascii=False)
            new_json = json.dumps(target["local"], ensure_ascii=False)
            if current_card != target["local"]:
                occurrences = text.count(old_json)
                if occurrences != 2:
                    raise RuntimeError(f"{codigo}: esperado caminho atual 2x, encontrado {occurrences}")
                text = text.replace(old_json, new_json)

            row = {
                "codigo": codigo,
                "ref": target["ref"],
                "arquivo_local": target["local"],
                "origem": target["source_kind"],
                **dest_meta,
            }
            if codigo == "FK-0371":
                row["proveniencia"] = (
                    "Biblioteca validada: Flora|84384 e Flora|84391 usam o mesmo asset i224; "
                    "foi reutilizado o arquivo local íntegro da referência 84391."
                )
            else:
                row["proveniencia"] = (
                    "Arquivo original preservado na biblioteca-fonte "
                    "catalogos-papel-de-parede/imagens/home-finish/flora/originals/84858.jpg. "
                    "A baixa variação de pixels é esperada porque o produto oficial é off-white."
                )
            rows.append(row)

        INDEX.write_text(text, encoding="utf-8")

        final_data = parse_data(text)
        for codigo, target in TARGETS.items():
            item = next(x for x in final_data if str(x.get("codigo") or "") == codigo)
            if item.get("card") != target["local"] or item.get("zoom") != target["local"]:
                raise RuntimeError(f"{codigo}: card/zoom não ficaram locais")

    except Exception:
        INDEX.write_text(original_text, encoding="utf-8")
        raise

    report = {
        "status": "ok",
        "escopo": "Correção definitiva de FK-0371/84384 e FK-0380/84858 sem hotlink externo",
        "itens": rows,
        "resultado": {
            "itens_localizados": 2,
            "dependencia_externa_removida_dos_itens": True,
            "card_e_zoom_locais": True,
        },
        "criterio": (
            "Foram usadas apenas fontes já validadas da biblioteca de fornecimento da Fábrika. "
            "84384 foi recuperada a partir do asset compartilhado i224 confirmado com 84391; "
            "84858 foi recuperada do original preservado no repositório-fonte. Papéis claros/off-white "
            "não são rejeitados por baixa variação visual quando o arquivo e a proveniência são válidos."
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
