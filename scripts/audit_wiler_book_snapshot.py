from __future__ import annotations

import base64
import gzip
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
SOURCE = ROOT / "_catalog_source" / "dados" / "colecoes"
REPORT = ROOT / "auditoria-wiler-book-snapshot.json"
TARGETS = {"Bambine", "Tacto", "Texture II", "Texture III", "Tramas"}
REF_KEYS = {"r", "ref", "referencia", "reference", "codigo_referencia"}


def parse_catalog() -> list[dict]:
    text = INDEX.read_text(encoding="utf-8")
    start = text.index("let DATA=") + len("let DATA=")
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    return data


def norm(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def load_source_file(path: Path):
    if path.name.endswith(".json"):
        return json.loads(path.read_text(encoding="utf-8"))
    if path.name.endswith(".json.gz.b64"):
        raw = base64.b64decode(path.read_text(encoding="utf-8"))
        return json.loads(gzip.decompress(raw).decode("utf-8"))
    raise ValueError(path.name)


def collect_refs(obj) -> set[str]:
    refs: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in REF_KEYS and isinstance(value, (str, int)):
                text = str(value).strip()
                if text:
                    refs.add(text)
            refs.update(collect_refs(value))
    elif isinstance(obj, list):
        for value in obj:
            refs.update(collect_refs(value))
    return refs


def walk_collections(obj, source_file: str, path="root"):
    found = []
    if isinstance(obj, dict):
        collection = obj.get("colecao") or obj.get("collection")
        supplier = obj.get("fornecedor") or obj.get("supplier")
        if isinstance(collection, str):
            found.append({
                "source_file": source_file,
                "path": path,
                "fornecedor": supplier,
                "colecao": collection,
                "fonte_pdf": obj.get("fonte_pdf"),
                "refs": sorted(collect_refs(obj)),
            })
        for key, value in obj.items():
            found.extend(walk_collections(value, source_file, f"{path}.{key}"))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            found.extend(walk_collections(value, source_file, f"{path}[{i}]"))
    return found


def main() -> None:
    data = parse_catalog()
    files = []
    candidates = []
    errors = []

    if not SOURCE.exists():
        raise SystemExit(f"Source checkout not found: {SOURCE}")

    for path in sorted(SOURCE.iterdir()):
        if not (path.name.endswith(".json") or path.name.endswith(".json.gz.b64")):
            continue
        try:
            obj = load_source_file(path)
            entries = walk_collections(obj, path.name)
            files.append({
                "arquivo": path.name,
                "tipo_topo": type(obj).__name__,
                "colecoes_detectadas": [e["colecao"] for e in entries],
            })
            candidates.extend(entries)
        except Exception as exc:
            errors.append({"arquivo": path.name, "erro": f"{type(exc).__name__}: {exc}"})

    results = []
    for target in sorted(TARGETS):
        catalog_refs = {
            str(x.get("ref") or "").strip()
            for x in data
            if x.get("fornecedor") == "Wiler"
            and x.get("colecao") == target
            and str(x.get("ref") or "").strip()
        }
        matches = [e for e in candidates if norm(e["colecao"]) == norm(target)]
        snapshot_refs: set[str] = set()
        for match in matches:
            snapshot_refs.update(match["refs"])
        snap_norm = {norm(r): r for r in snapshot_refs if norm(r)}
        cat_norm = {norm(r): r for r in catalog_refs if norm(r)}
        missing = [snap_norm[k] for k in sorted(set(snap_norm) - set(cat_norm))]
        extras = [cat_norm[k] for k in sorted(set(cat_norm) - set(snap_norm))]
        results.append({
            "colecao": target,
            "catalogo_total": len(catalog_refs),
            "snapshot_total": len(snapshot_refs) if matches else None,
            "snapshot_fontes": [
                {
                    "arquivo": e["source_file"],
                    "path": e["path"],
                    "fornecedor": e["fornecedor"],
                    "fonte_pdf": e["fonte_pdf"],
                    "refs": len(e["refs"]),
                }
                for e in matches
            ],
            "faltantes_vs_snapshot": missing,
            "extras_vs_snapshot": extras,
            "match_exato": bool(matches) and not missing and not extras,
            "status": "match_exato" if matches and not missing and not extras else ("divergencia" if matches else "snapshot_nao_localizado"),
        })

    report = {
        "fonte": "Snapshot interno do repositório-fonte da Fábrika; usado como evidência histórica do book, não como substituto da fonte oficial online.",
        "criterio": "Decodifica os datasets de coleções já construídos a partir dos materiais de origem e compara referência a referência com o catálogo publicado. Nenhuma divergência causa remoção automática.",
        "arquivos_lidos": files,
        "erros": errors,
        "colecoes": results,
        "resumo": {
            "matches_exatos": [r["colecao"] for r in results if r["match_exato"]],
            "divergencias": [r["colecao"] for r in results if r["status"] == "divergencia"],
            "sem_snapshot": [r["colecao"] for r in results if r["status"] == "snapshot_nao_localizado"],
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["resumo"], ensure_ascii=False))


if __name__ == "__main__":
    main()
