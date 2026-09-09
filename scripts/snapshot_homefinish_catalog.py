from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-homefinish-catalog-refs.json"


def parse_data() -> list[dict]:
    text = INDEX.read_text(encoding="utf-8")
    start = text.index("let DATA=") + len("let DATA=")
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    return data


def main() -> None:
    data = parse_data()
    grouped: dict[str, list[str]] = defaultdict(list)
    duplicates: list[dict] = []

    for item in data:
        if item.get("fornecedor") != "Home Finish":
            continue
        collection = str(item.get("colecao") or "").strip()
        ref = str(item.get("ref") or "").strip().upper()
        if collection and ref:
            grouped[collection].append(ref)

    collections = {}
    for collection, refs in sorted(grouped.items()):
        seen = set()
        dups = []
        unique = []
        for ref in refs:
            if ref in seen:
                dups.append(ref)
            else:
                seen.add(ref)
                unique.append(ref)
        if dups:
            duplicates.append({"colecao": collection, "refs": sorted(set(dups))})
        collections[collection] = {
            "quantidade": len(unique),
            "refs": sorted(unique),
        }

    report = {
        "fonte": "DATA do catálogo publicado",
        "fornecedor": "Home Finish",
        "total": sum(v["quantidade"] for v in collections.values()),
        "duplicatas": duplicates,
        "colecoes": collections,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "total": report["total"],
        "colecoes": {k: v["quantidade"] for k, v in collections.items()},
        "duplicatas": duplicates,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
