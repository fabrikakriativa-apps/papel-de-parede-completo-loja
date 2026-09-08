from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-performance.json"
DATA_PATTERN = re.compile(r"(let DATA=)(\[.*?\])(;const )", re.S)
IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)


def patch_img(tag: str) -> str:
    lower = tag.lower()
    if "src=" not in lower:
        return tag
    attrs = []
    if "loading=" not in lower:
        attrs.append('loading="lazy"')
    if "decoding=" not in lower:
        attrs.append('decoding="async"')
    if not attrs:
        return tag
    if tag.endswith("/>"):
        return tag[:-2].rstrip() + " " + " ".join(attrs) + "/>"
    return tag[:-1].rstrip() + " " + " ".join(attrs) + ">"


def main() -> None:
    original = INDEX.read_text(encoding="utf-8")
    before_match = DATA_PATTERN.search(original)
    if not before_match:
        raise RuntimeError("Não encontrei o bloco DATA no index.html")
    data_before = before_match.group(2)

    tags_before = IMG_TAG.findall(original)
    patched = IMG_TAG.sub(lambda m: patch_img(m.group(0)), original)

    after_match = DATA_PATTERN.search(patched)
    if not after_match:
        raise RuntimeError("Otimização removeu ou corrompeu o bloco DATA")
    data_after = after_match.group(2)
    if data_before != data_after:
        raise RuntimeError("Otimização tentou alterar o DATA do catálogo; operação abortada")

    # Confirma também que o JSON continua válido antes de gravar.
    items = json.loads(data_after)
    if not isinstance(items, list) or not items:
        raise RuntimeError("DATA inválido após otimização")

    tags_after = IMG_TAG.findall(patched)
    src_tags = [tag for tag in tags_after if "src=" in tag.lower()]
    lazy_tags = [tag for tag in src_tags if "loading=" in tag.lower()]
    async_tags = [tag for tag in src_tags if "decoding=" in tag.lower()]
    modified = sum(1 for before, after in zip(tags_before, tags_after) if before != after)

    INDEX.write_text(patched, encoding="utf-8")
    report = {
        "itens_catalogo_preservados": len(items),
        "data_inalterado_byte_a_byte": True,
        "tags_img_encontradas": len(tags_after),
        "tags_img_com_src": len(src_tags),
        "tags_img_modificadas_nesta_execucao": modified,
        "tags_img_com_loading": len(lazy_tags),
        "tags_img_com_decoding": len(async_tags),
        "criterio": "Adiciona loading=lazy e decoding=async a tags img com src sem alterar o bloco DATA. A execução aborta se qualquer byte do DATA mudar.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
