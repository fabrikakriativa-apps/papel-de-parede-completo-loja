from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
IMAGES = ROOT / "imagens"
REPORT = ROOT / "auditoria-imagens.json"
VALID_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("&", " e ")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def norm_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", slug(value))


def posix(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def build_index():
    files = [p for p in IMAGES.rglob("*") if p.is_file() and p.suffix.lower() in VALID_EXTS]
    by_name = defaultdict(list)
    by_stem = defaultdict(list)
    for p in files:
        by_name[p.name.casefold()].append(p)
        by_stem[p.stem.casefold()].append(p)
    return files, by_name, by_stem


def local_path(value: str) -> Path | None:
    if not value or value.startswith("data:"):
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return None
    clean = unquote(value.split("?", 1)[0].split("#", 1)[0]).lstrip("./")
    return ROOT / clean


def choose_candidate(item: dict, value: str, by_name, by_stem):
    parsed = urlparse(value) if value.startswith(("http://", "https://")) else None
    raw_path = parsed.path if parsed else value
    base = Path(unquote(raw_path)).name
    if not base:
        return None, "sem_nome"

    # Correções de alias conhecidas, mas apenas se o arquivo realmente existir.
    aliases = []
    clean = unquote(value.split("?", 1)[0].split("#", 1)[0]).lstrip("./")
    if clean.startswith("imagens/wiler-k/"):
        aliases.append(clean.replace("imagens/wiler-k/", "imagens/wiler/", 1))
    aliases.append(clean.replace("poetic-chart-5", "poet-chart-5"))
    aliases.append(clean.replace("poetic-chart", "poet-chart"))
    for alias in aliases:
        p = ROOT / alias
        if p.is_file():
            return p, "alias"

    candidates = list(by_name.get(base.casefold(), []))
    if not candidates:
        candidates = list(by_stem.get(Path(base).stem.casefold(), []))
    if not candidates:
        return None, "nao_encontrado"

    vendor = slug(item.get("fornecedor", ""))
    collection = slug(item.get("colecao", ""))
    ref = norm_token(item.get("ref", ""))

    def score(p: Path):
        s = p.as_posix().lower()
        stem = norm_token(p.stem)
        points = 0
        if vendor and f"/{vendor}/" in f"/{s}/":
            points += 12
        if collection and f"/{collection}/" in f"/{s}/":
            points += 16
        if ref and stem == ref:
            points += 20
        elif ref and (ref in stem or stem in ref):
            points += 8
        if "/thumbnails/" in f"/{s}/":
            points += 4
        return points

    ranked = sorted(((score(p), p) for p in candidates), key=lambda x: (-x[0], x[1].as_posix()))
    best_score, best = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else -1

    # Não troca imagem quando há empate entre candidatos plausíveis.
    if len(ranked) > 1 and best_score == second_score:
        return None, "ambiguo"
    return best, "codigo_nome"


def main():
    html = INDEX.read_text(encoding="utf-8")
    marker = "let DATA="
    start = html.index(marker) + len(marker)
    decoder = json.JSONDecoder()
    data, consumed = decoder.raw_decode(html[start:])
    end = start + consumed

    _, by_name, by_stem = build_index()
    corrections = []
    unresolved = []

    for item in data:
        for field in ("card", "zoom"):
            original = item.get(field, "")
            if not original:
                unresolved.append({"codigo": item.get("codigo"), "ref": item.get("ref"), "campo": field, "caminho": original, "motivo": "vazio"})
                continue

            lp = local_path(original)
            if lp is not None and lp.is_file():
                continue

            candidate, reason = choose_candidate(item, original, by_name, by_stem)
            if candidate is not None:
                new_value = posix(candidate)
                if new_value != original:
                    item[field] = new_value
                    corrections.append({
                        "codigo": item.get("codigo"),
                        "ref": item.get("ref"),
                        "campo": field,
                        "de": original,
                        "para": new_value,
                        "criterio": reason,
                    })
            else:
                # Se o zoom não existir mas o card já estiver válido, usa o card em vez de quebrar o modal.
                if field == "zoom":
                    card = item.get("card", "")
                    cp = local_path(card)
                    if cp is not None and cp.is_file():
                        item[field] = card
                        corrections.append({
                            "codigo": item.get("codigo"),
                            "ref": item.get("ref"),
                            "campo": field,
                            "de": original,
                            "para": card,
                            "criterio": "fallback_card",
                        })
                        continue
                unresolved.append({
                    "codigo": item.get("codigo"),
                    "ref": item.get("ref"),
                    "fornecedor": item.get("fornecedor"),
                    "colecao": item.get("colecao"),
                    "campo": field,
                    "caminho": original,
                    "motivo": reason,
                })

    compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    new_html = html[:start] + compact + html[end:]
    if new_html != html:
        INDEX.write_text(new_html, encoding="utf-8")

    # Segunda validação: tudo que ficou como caminho local precisa existir.
    remaining_local_missing = []
    external_remaining = []
    for item in data:
        for field in ("card", "zoom"):
            value = item.get(field, "")
            if value.startswith(("http://", "https://")):
                external_remaining.append({"codigo": item.get("codigo"), "ref": item.get("ref"), "campo": field, "caminho": value})
                continue
            lp = local_path(value)
            if lp is not None and not lp.is_file():
                remaining_local_missing.append({"codigo": item.get("codigo"), "ref": item.get("ref"), "campo": field, "caminho": value})

    report = {
        "itens_catalogo": len(data),
        "referencias_imagem": len(data) * 2,
        "correcoes_aplicadas": len(corrections),
        "faltantes_locais_apos_correcao": len(remaining_local_missing),
        "externas_apos_correcao": len(external_remaining),
        "correcoes": corrections,
        "nao_resolvidos": unresolved,
        "faltantes_locais": remaining_local_missing,
        "externas": external_remaining,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({k: report[k] for k in ("itens_catalogo", "referencias_imagem", "correcoes_aplicadas", "faltantes_locais_apos_correcao", "externas_apos_correcao")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
