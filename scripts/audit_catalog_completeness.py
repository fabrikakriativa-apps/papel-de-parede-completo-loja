from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
SOURCE = ROOT / "_image_source"
REPORT = ROOT / "auditoria-completude.json"
VALID_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("&", " e ")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def norm_ref(value: str, vendor_slug: str = "") -> str:
    value = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    # Home Finish entries in the catalog historically use BH as a display prefix,
    # while source-library filenames use the supplier's numeric reference.
    if vendor_slug == "home-finish" and value.startswith("BH"):
        value = value[2:]
    return value


def parse_data() -> list[dict]:
    html = INDEX.read_text(encoding="utf-8")
    marker = "let DATA="
    start = html.index(marker) + len(marker)
    data, _ = json.JSONDecoder().raw_decode(html[start:])
    return data


def source_names() -> dict[tuple[str, str], dict]:
    names: dict[tuple[str, str], dict] = {}
    colecoes_dir = SOURCE / "dados" / "colecoes"
    if not colecoes_dir.exists():
        return names
    for p in colecoes_dir.glob("*.json"):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        vendor = slug(str(obj.get("fornecedor", "")))
        collection = slug(str(obj.get("slug") or obj.get("colecao", "")))
        if vendor and collection:
            names[(vendor, collection)] = {
                "fornecedor": obj.get("fornecedor") or vendor.replace("-", " ").title(),
                "colecao": obj.get("colecao") or collection.replace("-", " ").title(),
            }
    return names


def collection_key_from_item(item: dict) -> tuple[str, str]:
    # Prefer the local card path because it reflects the actual image-library folder.
    card = str(item.get("card", ""))
    m = re.search(r"(?:^|/)imagens/([^/]+)/([^/]+)/", card)
    if m:
        return slug(m.group(1)), slug(m.group(2))
    return slug(str(item.get("fornecedor", ""))), slug(str(item.get("colecao", "")))


def ref_from_item(item: dict, vendor_slug: str) -> str:
    # A local card filename is the strongest match to the source library.
    card = str(item.get("card", ""))
    if card and not card.startswith(("http://", "https://")):
        stem = Path(card.split("?", 1)[0]).stem
        if stem:
            return norm_ref(stem, vendor_slug)
    return norm_ref(str(item.get("ref", "")), vendor_slug)


def main() -> None:
    data = parse_data()
    labels = source_names()

    live_refs: dict[tuple[str, str], set[str]] = defaultdict(set)
    live_labels: dict[tuple[str, str], dict] = {}
    for item in data:
        key = collection_key_from_item(item)
        ref = ref_from_item(item, key[0])
        if ref:
            live_refs[key].add(ref)
        live_labels.setdefault(key, {
            "fornecedor": item.get("fornecedor") or key[0],
            "colecao": item.get("colecao") or key[1],
        })

    source_refs: dict[tuple[str, str], set[str]] = defaultdict(set)
    images_root = SOURCE / "imagens"
    if images_root.exists():
        for thumb_dir in images_root.glob("*/*/thumbnails"):
            if not thumb_dir.is_dir():
                continue
            vendor = slug(thumb_dir.parent.parent.name)
            collection = slug(thumb_dir.parent.name)
            key = (vendor, collection)
            for p in thumb_dir.iterdir():
                if p.is_file() and p.suffix.lower() in VALID_EXTS:
                    ref = norm_ref(p.stem, vendor)
                    if ref:
                        source_refs[key].add(ref)

    rows = []
    for key in sorted(set(source_refs) | set(live_refs)):
        src = source_refs.get(key, set())
        live = live_refs.get(key, set())
        missing = sorted(src - live)
        extras = sorted(live - src)
        label = labels.get(key) or live_labels.get(key) or {
            "fornecedor": key[0].replace("-", " ").title(),
            "colecao": key[1].replace("-", " ").title(),
        }
        rows.append({
            "fornecedor": label["fornecedor"],
            "colecao": label["colecao"],
            "vendor_slug": key[0],
            "collection_slug": key[1],
            "na_biblioteca": len(src),
            "no_catalogo": len(live),
            "faltando_no_catalogo": len(missing),
            "refs_faltando": missing,
            "extras_no_catalogo": len(extras),
            "refs_extras": extras,
        })

    rows.sort(key=lambda r: (-r["faltando_no_catalogo"], r["fornecedor"], r["colecao"]))
    with_missing = [r for r in rows if r["faltando_no_catalogo"] > 0]

    report = {
        "itens_catalogo": len(data),
        "colecoes_biblioteca": len(source_refs),
        "colecoes_catalogo": len(live_refs),
        "colecoes_com_itens_faltantes": len(with_missing),
        "total_referencias_faltantes": sum(r["faltando_no_catalogo"] for r in with_missing),
        "criterio": "Comparação entre referências únicas dos thumbnails da biblioteca-base e itens publicados por fornecedor/coleção. Só são marcadas como faltantes referências que existem fisicamente na biblioteca-base.",
        "colecoes": rows,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "itens_catalogo": report["itens_catalogo"],
        "colecoes_biblioteca": report["colecoes_biblioteca"],
        "colecoes_catalogo": report["colecoes_catalogo"],
        "colecoes_com_itens_faltantes": report["colecoes_com_itens_faltantes"],
        "total_referencias_faltantes": report["total_referencias_faltantes"],
        "top_faltas": [
            {"fornecedor": r["fornecedor"], "colecao": r["colecao"], "biblioteca": r["na_biblioteca"], "catalogo": r["no_catalogo"], "faltando": r["faltando_no_catalogo"]}
            for r in with_missing[:15]
        ],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
