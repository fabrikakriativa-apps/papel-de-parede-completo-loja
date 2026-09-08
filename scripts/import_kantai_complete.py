from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
OFFICIAL = ROOT / "auditoria-kantai-oficial.json"
REPORT = ROOT / "auditoria-importacao-kantai.json"

TARGETS = {
    "Aditare 3": {"slug": "aditare-3", "expected": 81},
    "Criativo 3": {"slug": "criativo-3", "expected": 89},
    "Poet Chart 5": {"slug": "poet-chart-5", "expected": 78},
    "Space IX": {"slug": "space-ix", "expected": 83},
}


def parse_catalog():
    html = INDEX.read_text(encoding="utf-8")
    marker = "let DATA="
    start = html.index(marker) + len(marker)
    data, consumed = json.JSONDecoder().raw_decode(html[start:])
    return html, start, start + consumed, data


def unique_nonempty(items, field: str):
    values = {str(x.get(field, "")).strip() for x in items if str(x.get(field, "")).strip()}
    return values


def max_fk_code(data: list[dict]) -> int:
    best = 0
    for item in data:
        m = re.fullmatch(r"FK-(\d+)", str(item.get("codigo", "")).strip(), re.I)
        if m:
            best = max(best, int(m.group(1)))
    return best


def download_jpeg(url: str, target: Path) -> None:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; FabrikaKriativa-Catalog/1.0)",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": "https://www.kantai.com.br/",
        },
    )
    with urlopen(req, timeout=45) as response:
        payload = response.read()
    if len(payload) < 1500:
        raise ValueError(f"imagem muito pequena ({len(payload)} bytes)")

    with Image.open(io.BytesIO(payload)) as im:
        im.load()
        if im.width < 100 or im.height < 100:
            raise ValueError(f"dimensão inválida {im.width}x{im.height}")
        if im.mode not in ("RGB", "L"):
            background = Image.new("RGB", im.size, "white")
            if "A" in im.getbands():
                background.paste(im.convert("RGBA"), mask=im.getchannel("A"))
                im = background
            else:
                im = im.convert("RGB")
        elif im.mode == "L":
            im = im.convert("RGB")
        else:
            im = im.copy()
        im.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
        target.parent.mkdir(parents=True, exist_ok=True)
        im.save(target, format="JPEG", quality=90, optimize=True, progressive=True)


def collection_key(item: dict):
    return str(item.get("fornecedor", "")).strip(), str(item.get("colecao", "")).strip()


def main():
    official = json.loads(OFFICIAL.read_text(encoding="utf-8"))
    if not official.get("all_ok"):
        raise RuntimeError("auditoria oficial Kantai não está all_ok=true")

    official_by_name = {x["name"]: x for x in official.get("collections", [])}
    for name, cfg in TARGETS.items():
        source = official_by_name.get(name)
        if not source:
            raise RuntimeError(f"coleção oficial ausente: {name}")
        if int(source.get("declared_total") or 0) != cfg["expected"]:
            raise RuntimeError(f"total oficial divergente em {name}: {source.get('declared_total')} != {cfg['expected']}")
        if int(source.get("captured_items") or 0) != cfg["expected"]:
            raise RuntimeError(f"captura incompleta em {name}: {source.get('captured_items')} != {cfg['expected']}")
        if int(source.get("valid_reference_items") or 0) != cfg["expected"]:
            raise RuntimeError(f"referências válidas incompletas em {name}")

    html, data_start, data_end, data = parse_catalog()
    before_total = len(data)
    original_codes = {str(x.get("codigo", "")) for x in data}
    if len(original_codes) != len(data):
        raise RuntimeError("catálogo já possui códigos FK duplicados; importação abortada")

    prepared = {}
    all_missing = []
    next_code = max_fk_code(data) + 1

    for name, cfg in TARGETS.items():
        existing = [x for x in data if collection_key(x) == ("Kantai", name)]
        if not existing:
            raise RuntimeError(f"nenhum item existente para usar como template: {name}")

        metadata = {}
        for field in ("tipo", "medida", "preco"):
            values = unique_nonempty(existing, field)
            if len(values) != 1:
                raise RuntimeError(f"{name}: campo {field} não é uniforme: {sorted(values)}")
            metadata[field] = next(iter(values))

        existing_by_ref = {str(x.get("ref", "")).strip().upper(): x for x in existing}
        if len(existing_by_ref) != len(existing):
            raise RuntimeError(f"{name}: referências duplicadas no catálogo atual")

        src = official_by_name[name]
        official_items = list(src.get("items", []))
        official_items.sort(key=lambda x: (x.get("orderIndex") is None, x.get("orderIndex") or 0, x.get("ref") or ""))
        official_refs = [str(x.get("ref", "")).strip().upper() for x in official_items]
        if len(official_refs) != cfg["expected"] or len(set(official_refs)) != cfg["expected"]:
            raise RuntimeError(f"{name}: lista oficial não fecha {cfg['expected']} referências únicas")

        missing = [x for x in official_items if str(x.get("ref", "")).strip().upper() not in existing_by_ref]
        expected_missing = cfg["expected"] - len(existing)
        if len(missing) != expected_missing:
            raise RuntimeError(f"{name}: faltantes calculados {len(missing)} != esperado {expected_missing}")

        block = []
        new_refs = []
        for source_item in official_items:
            ref = str(source_item.get("ref", "")).strip().upper()
            if ref in existing_by_ref:
                block.append(existing_by_ref[ref])
                continue

            code = f"FK-{next_code:04d}"
            next_code += 1
            rel = f"imagens/kantai/{cfg['slug']}/thumbnails/{ref}.jpg"
            search = f"{code} {ref} Kantai {name} {metadata['tipo']} {metadata['medida']}".lower()
            item = {
                "codigo": code,
                "ref": ref,
                "fornecedor": "Kantai",
                "colecao": name,
                "tipo": metadata["tipo"],
                "medida": metadata["medida"],
                "preco": metadata["preco"],
                "card": rel,
                "zoom": rel,
                "search": search,
                "cor": [],
                "estilo": [],
            }
            block.append(item)
            new_refs.append(ref)
            all_missing.append({
                "colecao": name,
                "slug": cfg["slug"],
                "ref": ref,
                "codigo": code,
                "mediaUrl": source_item.get("mediaUrl"),
                "target": rel,
            })

        prepared[name] = {
            "existing": existing,
            "existing_refs": set(existing_by_ref),
            "block": block,
            "new_refs": new_refs,
            "metadata": metadata,
            "official_refs": official_refs,
        }

    if len(all_missing) != 231:
        raise RuntimeError(f"importação deveria adicionar 231 itens, calculou {len(all_missing)}")

    # Download every missing image to a temporary staging tree first.
    # Nothing in the live catalog is changed unless all 231 images validate.
    with tempfile.TemporaryDirectory(prefix="kantai-import-") as tmp:
        stage_root = Path(tmp)
        failures = []
        for i, item in enumerate(all_missing, 1):
            url = str(item.get("mediaUrl") or "")
            if not url.startswith("https://"):
                failures.append({**item, "erro": "mediaUrl oficial inválida"})
                continue
            staged = stage_root / item["target"]
            try:
                download_jpeg(url, staged)
            except Exception as exc:
                failures.append({**item, "erro": f"{type(exc).__name__}: {exc}"})
            if i % 25 == 0 or i == len(all_missing):
                print(f"imagens oficiais processadas: {i}/{len(all_missing)}; falhas: {len(failures)}")

        if failures:
            REPORT.write_text(json.dumps({
                "status": "abortado",
                "motivo": "falha no download/validação de imagens; index.html não alterado",
                "falhas": failures,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            raise RuntimeError(f"{len(failures)} imagens falharam; importação abortada")

        # Rebuild target blocks at their first original occurrence, preserving all unrelated items.
        emitted = set()
        new_data = []
        for item in data:
            vendor, collection = collection_key(item)
            if vendor == "Kantai" and collection in TARGETS:
                if collection not in emitted:
                    new_data.extend(prepared[collection]["block"])
                    emitted.add(collection)
                continue
            new_data.append(item)

        if emitted != set(TARGETS):
            raise RuntimeError(f"nem todas as coleções foram reconstruídas: {sorted(emitted)}")

        # Final in-memory validation before copying any staged image.
        final_codes = [str(x.get("codigo", "")) for x in new_data]
        if len(final_codes) != len(set(final_codes)):
            raise RuntimeError("códigos duplicados após reconstrução")
        if len(new_data) != before_total + 231:
            raise RuntimeError(f"total final inesperado: {len(new_data)} != {before_total + 231}")

        per_collection = {}
        for name, cfg in TARGETS.items():
            final_items = [x for x in new_data if collection_key(x) == ("Kantai", name)]
            refs = [str(x.get("ref", "")).strip().upper() for x in final_items]
            if len(final_items) != cfg["expected"] or len(set(refs)) != cfg["expected"]:
                raise RuntimeError(f"{name}: validação final falhou ({len(final_items)} itens, {len(set(refs))} refs)")
            if set(refs) != set(prepared[name]["official_refs"]):
                raise RuntimeError(f"{name}: referências finais divergem da fonte oficial")
            per_collection[name] = {
                "oficial": cfg["expected"],
                "antes": len(prepared[name]["existing"]),
                "adicionados": len(prepared[name]["new_refs"]),
                "depois": len(final_items),
                "metadata_template": prepared[name]["metadata"],
                "refs_adicionadas": prepared[name]["new_refs"],
            }

        # Commit file system changes only after the full transaction validates.
        for item in all_missing:
            staged = stage_root / item["target"]
            final = ROOT / item["target"]
            final.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staged, final)

        compact = json.dumps(new_data, ensure_ascii=False, separators=(",", ":"))
        new_html = html[:data_start] + compact + html[data_end:]
        INDEX.write_text(new_html, encoding="utf-8")

        report = {
            "status": "ok",
            "fonte": "Kantai official public website / Wix public gallery API",
            "itens_catalogo_antes": before_total,
            "itens_catalogo_depois": len(new_data),
            "itens_adicionados": 231,
            "imagens_oficiais_adicionadas": len(all_missing),
            "colecoes": per_collection,
            "validacoes": {
                "auditoria_oficial_all_ok": True,
                "codigos_fk_unicos": True,
                "referencias_finais_iguais_a_fonte_oficial": True,
                "todas_imagens_novas_baixadas_e_validadas": True,
            },
        }
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "status": "ok",
            "antes": before_total,
            "depois": len(new_data),
            "adicionados": 231,
            "colecoes": {k: {x: v[x] for x in ("antes", "adicionados", "depois")} for k, v in per_collection.items()},
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
