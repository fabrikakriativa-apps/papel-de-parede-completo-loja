from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "diagnostico-render-imagens.json"

PATTERNS = [
    r"createElement",
    r"new\s+Image\s*\(",
    r"\.src\s*=",
    r"innerHTML",
    r"insertAdjacentHTML",
    r"appendChild",
    r"\.card\b",
    r"\.zoom\b",
    r"<img\b",
]


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def main() -> None:
    html = INDEX.read_text(encoding="utf-8")

    # Remove o enorme DATA do diagnóstico, sem tocar no arquivo real.
    marker = "let DATA="
    start = html.index(marker) + len(marker)
    _, end = json.JSONDecoder().raw_decode(html[start:])
    scan = html[:start] + "[DATA_REMOVIDO_DO_DIAGNOSTICO]" + html[start + end:]

    hits = []
    seen = set()
    for pattern in PATTERNS:
        for match in re.finditer(pattern, scan, re.I):
            lo = max(0, match.start() - 260)
            hi = min(len(scan), match.end() + 420)
            snippet = compact(scan[lo:hi])
            key = (pattern, snippet)
            if key in seen:
                continue
            seen.add(key)
            hits.append({
                "padrao": pattern,
                "posicao": match.start(),
                "trecho": snippet,
            })

    REPORT.write_text(
        json.dumps({
            "arquivo": "index.html",
            "data_excluido_da_varredura": True,
            "ocorrencias": len(hits),
            "resultados": hits,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Diagnóstico gravado com {len(hits)} ocorrências")


if __name__ == "__main__":
    main()
