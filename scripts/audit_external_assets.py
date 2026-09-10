from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-assets-externos.json"


def parse_data() -> list[dict]:
    html = INDEX.read_text(encoding="utf-8")
    marker = "let DATA="
    start = html.index(marker) + len(marker)
    data, _ = json.JSONDecoder().raw_decode(html[start:])
    if not isinstance(data, list):
        raise RuntimeError("DATA inválido")
    return data


def norm(value: object) -> str:
    return str(value or "").strip()


def is_external(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def ref_tokens(ref: str) -> set[str]:
    base = ref.strip().upper()
    tokens = {base}
    compact = re.sub(r"[^A-Z0-9]+", "", base)
    if compact:
        tokens.add(compact)
    # Home Finish commercial prefixes are sometimes absent from source filenames.
    if base.startswith("BH") and base[2:].isdigit():
        tokens.add(base[2:])
    if base.startswith("MI") and base[2:].isdigit():
        tokens.add(base[2:])
    return {t.casefold() for t in tokens if t}


def build_file_index() -> list[Path]:
    exts = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
    return [p for p in (ROOT / "imagens").rglob("*") if p.is_file() and p.suffix.lower() in exts]


def local_candidates(ref: str, files: list[Path]) -> list[str]:
    tokens = ref_tokens(ref)
    hits = []
    for path in files:
        name = path.stem.casefold()
        compact_name = re.sub(r"[^a-z0-9]+", "", name)
        if any(token in name or re.sub(r"[^a-z0-9]+", "", token) in compact_name for token in tokens):
            hits.append(path.relative_to(ROOT).as_posix())
    return sorted(set(hits))[:20]


def main() -> None:
    data = parse_data()
    files = build_file_index()
    rows = []
    hosts = Counter()

    for item in data:
        card = norm(item.get("card"))
        zoom = norm(item.get("zoom"))
        if not is_external(card) and not is_external(zoom):
            continue
        urls = [u for u in (card, zoom) if is_external(u)]
        for url in urls:
            hosts[urlparse(url).netloc.casefold()] += 1
        ref = norm(item.get("ref"))
        candidates = local_candidates(ref, files)
        rows.append({
            "codigo": norm(item.get("codigo")),
            "fornecedor": norm(item.get("fornecedor")),
            "colecao": norm(item.get("colecao")),
            "ref": ref,
            "card": card,
            "zoom": zoom,
            "hosts": sorted({urlparse(u).netloc for u in urls}),
            "candidatos_locais_por_ref": candidates,
            "tem_candidato_local": bool(candidates),
        })

    report = {
        "status": "ok" if not rows else "dependencias_externas_encontradas",
        "itens_catalogo": len(data),
        "itens_com_asset_externo": len(rows),
        "urls_externas": sum(hosts.values()),
        "hosts": dict(sorted(hosts.items())),
        "itens_com_candidato_local": sum(1 for row in rows if row["tem_candidato_local"]),
        "itens_sem_candidato_local": sum(1 for row in rows if not row["tem_candidato_local"]),
        "itens": rows,
        "criterio": "Lista todos os itens cujo card ou zoom depende de URL externa e procura, sem alterar nada, arquivos locais existentes que contenham a referência no nome. Candidato por nome não é prova de correspondência visual e exige validação antes de substituição.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "itens_com_asset_externo": report["itens_com_asset_externo"],
        "urls_externas": report["urls_externas"],
        "hosts": report["hosts"],
        "itens_com_candidato_local": report["itens_com_candidato_local"],
        "itens_sem_candidato_local": report["itens_sem_candidato_local"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
