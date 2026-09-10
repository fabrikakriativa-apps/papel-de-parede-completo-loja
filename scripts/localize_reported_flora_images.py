from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-flora-imagens-localizadas.json"

TARGETS = {
    "FK-0371": {
        "ref": "84384",
        "url": "https://www.homefinish.com.br/wp-content/uploads/2025/06/84384-papel-parede-home-finish-flora.jpg",
        "local": "imagens/home-finish/flora/thumbnails/84384.jpg",
    },
    "FK-0380": {
        "ref": "84858",
        "url": "https://homefinish.com.br/wp-content/uploads/2025/06/84858-papel-parede-home-finish-flora.jpg",
        "local": "imagens/home-finish/flora/thumbnails/84858.jpg",
    },
}


def parse_data(text: str) -> list[dict]:
    marker = "let DATA="
    start = text.index(marker) + len(marker)
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    return data


def download_image(url: str) -> tuple[bytes, dict]:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": "https://www.homefinish.com.br/",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(req, timeout=45) as response:
        payload = response.read(12 * 1024 * 1024 + 1)
        content_type = response.headers.get("Content-Type", "")
    if len(payload) > 12 * 1024 * 1024:
        raise RuntimeError(f"Imagem excede 12 MB: {url}")
    if len(payload) < 10_000:
        raise RuntimeError(f"Download pequeno demais ({len(payload)} bytes), possível placeholder: {url}")
    if "image" not in content_type.lower():
        raise RuntimeError(f"Content-Type não é imagem: {content_type!r} - {url}")

    with Image.open(io.BytesIO(payload)) as im:
        im.verify()
    with Image.open(io.BytesIO(payload)) as im:
        width, height = im.size
        fmt = (im.format or "").upper()
        if width < 400 or height < 400:
            raise RuntimeError(f"Dimensões pequenas demais {width}x{height}: {url}")
        rgb = im.convert("RGB").resize((64, 64))
        stat = ImageStat.Stat(rgb)
        spread = sum(stat.stddev)
        if spread < 8:
            raise RuntimeError(f"Imagem quase uniforme/placeholder (desvio {spread:.2f}): {url}")

    return payload, {
        "bytes": len(payload),
        "width": width,
        "height": height,
        "format": fmt,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "pixel_stddev_sum": round(spread, 2),
        "content_type": content_type,
    }


def main() -> None:
    original_text = INDEX.read_text(encoding="utf-8")
    data = parse_data(original_text)

    downloaded: dict[str, tuple[bytes, dict]] = {}
    rows = []

    # Baixa e valida tudo antes de alterar qualquer arquivo.
    for codigo, target in TARGETS.items():
        matches = [x for x in data if str(x.get("codigo") or "") == codigo]
        if len(matches) != 1:
            raise RuntimeError(f"{codigo}: esperado 1 item, encontrado {len(matches)}")
        item = matches[0]
        expected = {"fornecedor": "Home Finish", "colecao": "Flora", "ref": target["ref"]}
        for field, value in expected.items():
            if str(item.get(field) or "") != value:
                raise RuntimeError(f"{codigo}: {field}={item.get(field)!r}, esperado {value!r}")

        payload, meta = download_image(target["url"])
        downloaded[codigo] = (payload, meta)
        rows.append({
            "codigo": codigo,
            "ref": target["ref"],
            "fonte_oficial": target["url"],
            "arquivo_local": target["local"],
            **meta,
        })

    # Grava somente depois que os dois downloads foram validados.
    text = original_text
    written_paths: list[Path] = []
    try:
        for codigo, target in TARGETS.items():
            payload, _ = downloaded[codigo]
            dest = ROOT / target["local"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(payload)
            written_paths.append(dest)

            item = next(x for x in data if str(x.get("codigo") or "") == codigo)
            current_card = str(item.get("card") or "")
            current_zoom = str(item.get("zoom") or "")
            if current_card != current_zoom:
                raise RuntimeError(f"{codigo}: card e zoom divergentes")

            old_json = json.dumps(current_card, ensure_ascii=False)
            new_json = json.dumps(target["local"], ensure_ascii=False)
            occurrences = text.count(old_json)
            if current_card != target["local"]:
                if occurrences != 2:
                    raise RuntimeError(f"{codigo}: esperado caminho atual 2x, encontrado {occurrences}")
                text = text.replace(old_json, new_json)

        INDEX.write_text(text, encoding="utf-8")

        final_data = parse_data(text)
        for codigo, target in TARGETS.items():
            item = next(x for x in final_data if str(x.get("codigo") or "") == codigo)
            if item.get("card") != target["local"] or item.get("zoom") != target["local"]:
                raise RuntimeError(f"{codigo}: card/zoom não ficaram locais")
            dest = ROOT / target["local"]
            with Image.open(dest) as im:
                im.verify()

    except Exception:
        INDEX.write_text(original_text, encoding="utf-8")
        raise

    report = {
        "status": "ok",
        "escopo": "Localização definitiva das duas imagens Flora que continuavam sem carregar no catálogo publicado",
        "itens": rows,
        "resultado": {
            "itens_localizados": 2,
            "dependencia_externa_removida_dos_itens": True,
            "card_e_zoom_locais": True,
        },
        "criterio": (
            "Somente FK-0371/84384 e FK-0380/84858 foram tratados. Os bytes foram baixados diretamente "
            "dos JPGs oficiais da Home Finish, validados como imagem real e gravados no repositório; depois card e zoom "
            "foram alterados para os caminhos locais. Nenhum outro produto foi reserializado."
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
