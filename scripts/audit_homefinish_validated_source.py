from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
SOURCE_DIR = ROOT / "_catalog_source" / "dados" / "home-finish-urls"
REPORT = ROOT / "auditoria-homefinish-fonte-validada.json"


def parse_catalog() -> list[dict]:
    text = INDEX.read_text(encoding="utf-8")
    start = text.index("let DATA=") + len("let DATA=")
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(data, list):
        raise RuntimeError("DATA do catálogo inválido")
    return data


def collection_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("&", " e ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalize_ref(collection: object, value: object) -> str:
    ref = str(value or "").strip().upper().replace(" ", "")
    if collection_key(collection) == "bio habitat" and ref.startswith("BH") and ref[2:].isdigit():
        ref = ref[2:]
    return ref


def load_validated_source() -> tuple[dict[str, set[str]], dict[tuple[str, str], str], dict[str, str]]:
    if not SOURCE_DIR.is_dir():
        raise RuntimeError(f"Base-fonte não encontrada: {SOURCE_DIR}")

    grouped: dict[str, set[str]] = defaultdict(set)
    urls: dict[tuple[str, str], str] = {}
    display_names: dict[str, str] = {}
    part_files = sorted(SOURCE_DIR.glob("part-*.json"))
    if not part_files:
        raise RuntimeError("Nenhuma parte Home Finish validada encontrada")

    for path in part_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("items", {})
        if not isinstance(items, dict):
            raise RuntimeError(f"Formato inesperado em {path}")
        for item in items.values():
            collection = str(item.get("collection") or "").strip()
            ref = normalize_ref(collection, item.get("ref"))
            url = str(item.get("url") or "").strip()
            if not collection or not ref:
                continue
            key = collection_key(collection)
            display_names.setdefault(key, collection)
            grouped[key].add(ref)
            if url:
                urls[(key, ref)] = url

    return grouped, urls, display_names


def main() -> None:
    source, urls, source_names = load_validated_source()
    catalog: dict[str, set[str]] = defaultdict(set)
    catalog_names: dict[str, str] = {}
    duplicate_pairs: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    for item in parse_catalog():
        if str(item.get("fornecedor") or "").strip() != "Home Finish":
            continue
        collection = str(item.get("colecao") or "").strip()
        ref = normalize_ref(collection, item.get("ref"))
        if not collection or not ref:
            continue
        key = collection_key(collection)
        catalog_names.setdefault(key, collection)
        pair = (key, ref)
        if pair in seen_pairs:
            duplicate_pairs.append({"colecao": collection, "ref": ref})
        seen_pairs.add(pair)
        catalog[key].add(ref)

    rows = []
    total_missing = 0
    total_extra = 0
    all_keys = sorted(set(source) | set(catalog))
    for key in all_keys:
        source_refs = source.get(key, set())
        catalog_refs = catalog.get(key, set())
        missing = sorted(source_refs - catalog_refs)
        extra = sorted(catalog_refs - source_refs)
        total_missing += len(missing)
        total_extra += len(extra)
        collection = catalog_names.get(key) or source_names.get(key) or key
        rows.append({
            "colecao": collection,
            "fonte_validada": len(source_refs),
            "catalogo": len(catalog_refs),
            "faltando_no_catalogo": missing,
            "extras_no_catalogo": extra,
            "urls_faltantes": {ref: urls.get((key, ref), "") for ref in missing},
            "status": "ok" if not missing and not extra else "divergente",
        })

    report = {
        "fonte": "Snapshot validado de URLs oficiais Home Finish armazenado no repositório-fonte",
        "fonte_repositorio": "fabrikakriativa-apps/catalogos-papel-de-parede/dados/home-finish-urls/part-*.json",
        "dominio_fonte": "homefinish.com.br",
        "total_fonte_validada": sum(len(v) for v in source.values()),
        "total_catalogo_home_finish": sum(len(v) for v in catalog.values()),
        "colecoes_fonte": len(source),
        "colecoes_catalogo": len(catalog),
        "total_faltando_no_catalogo": total_missing,
        "total_extras_no_catalogo": total_extra,
        "duplicatas_catalogo": duplicate_pairs,
        "status": "ok" if total_missing == 0 and total_extra == 0 and not duplicate_pairs else "divergente",
        "colecoes": rows,
        "criterio": "Compara referências por coleção contra o snapshot validado de URLs do domínio oficial Home Finish. Para BIO Habitat, o prefixo BH do catálogo é normalizado apenas para a comparação com a numeração usada no snapshot.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "total_fonte_validada": report["total_fonte_validada"],
        "total_catalogo_home_finish": report["total_catalogo_home_finish"],
        "total_faltando_no_catalogo": total_missing,
        "total_extras_no_catalogo": total_extra,
        "duplicatas_catalogo": len(duplicate_pairs),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
