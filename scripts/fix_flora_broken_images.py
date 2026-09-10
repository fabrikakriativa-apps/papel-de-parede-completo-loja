from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-flora-imagens-corrigidas.json"

TARGETS = {
    "FK-0371": {
        "ref": "84384",
        "url": "https://www.homefinish.com.br/wp-content/uploads/2025/06/84384-papel-parede-home-finish-flora.jpg",
    },
    "FK-0380": {
        "ref": "84858",
        "url": "https://homefinish.com.br/wp-content/uploads/2025/06/84858-papel-parede-home-finish-flora.jpg",
    },
    "FK-0408": {
        "ref": "84360",
        "url": "https://homefinish.com.br/wp-content/uploads/2025/06/84360-papel-parede-home-finish-flora.jpg",
    },
}


def parse_data(text: str) -> list[dict]:
    marker = "let DATA="
    start = text.index(marker) + len(marker)
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    return data


def main() -> None:
    text = INDEX.read_text(encoding="utf-8")
    data = parse_data(text)
    rows = []
    replacements: list[tuple[str, str]] = []

    for codigo, target in TARGETS.items():
        matches = [x for x in data if str(x.get("codigo") or "") == codigo]
        if len(matches) != 1:
            raise RuntimeError(f"{codigo}: esperado exatamente 1 item, encontrado {len(matches)}")

        item = matches[0]
        expected = {
            "fornecedor": "Home Finish",
            "colecao": "Flora",
            "ref": target["ref"],
        }
        for field, value in expected.items():
            if str(item.get(field) or "") != value:
                raise RuntimeError(
                    f"{codigo}: {field} inesperado: {item.get(field)!r}; esperado {value!r}"
                )

        card = str(item.get("card") or "")
        zoom = str(item.get("zoom") or "")
        official = target["url"]
        local_suffix = f"/flora/thumbnails/{target['ref']}.jpg"

        if card == official and zoom == official:
            rows.append({
                "codigo": codigo,
                "ref": target["ref"],
                "status": "ja_corrigido",
                "antes_card": card,
                "antes_zoom": zoom,
                "depois": official,
            })
            continue

        if card != zoom:
            raise RuntimeError(f"{codigo}: card e zoom divergentes antes da correção")
        if card.startswith("http://") or card.startswith("https://"):
            raise RuntimeError(f"{codigo}: URL externa inesperada antes da correção: {card}")
        if not card.replace("\\", "/").endswith(local_suffix):
            raise RuntimeError(f"{codigo}: caminho local inesperado: {card}")

        old_json = json.dumps(card, ensure_ascii=False)
        new_json = json.dumps(official, ensure_ascii=False)
        occurrences = text.count(old_json)
        if occurrences != 2:
            raise RuntimeError(
                f"{codigo}: esperado caminho local aparecer 2 vezes (card+zoom), encontrado {occurrences}"
            )
        replacements.append((old_json, new_json))
        rows.append({
            "codigo": codigo,
            "ref": target["ref"],
            "status": "corrigido",
            "antes_card": card,
            "antes_zoom": zoom,
            "depois": official,
        })

    for old_json, new_json in replacements:
        text = text.replace(old_json, new_json)

    INDEX.write_text(text, encoding="utf-8")

    final_data = parse_data(text)
    for codigo, target in TARGETS.items():
        item = next(x for x in final_data if str(x.get("codigo") or "") == codigo)
        if item.get("card") != target["url"] or item.get("zoom") != target["url"]:
            raise RuntimeError(f"{codigo}: validação pós-correção falhou")

    report = {
        "status": "ok",
        "escopo": "Somente três imagens Home Finish · Flora reportadas como não carregando",
        "itens_corrigidos_ou_ja_corrigidos": len(rows),
        "itens": rows,
        "criterio": (
            "Cada FK foi validado por código, referência, fornecedor e coleção. "
            "Card e zoom foram trocados somente para o JPG oficial exato exposto pela própria Home Finish. "
            "Nenhum outro item do DATA foi reserializado ou alterado."
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
