from __future__ import annotations

import asyncio
import io
import json
import math
import re
import shutil
import urllib.request
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from PIL import Image, ImageOps
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
AUDIT = ROOT / "auditoria-kantai.json"

COLLECTIONS = [
    {"name": "Aditare 3", "slug": "aditare-3", "url": "https://www.kantai.com.br/aditare3", "expected": 81},
    {"name": "Criativo 3", "slug": "criativo-3", "url": "https://www.kantai.com.br/criativo3", "expected": 89},
    {"name": "Poet Chart 5", "slug": "poet-chart-5", "url": "https://www.kantai.com.br/poetchart5", "expected": 78},
    {"name": "Space IX", "slug": "space-ix", "url": "https://www.kantai.com.br/space9", "expected": 83},
]

MAX_LONG_EDGE = 1200
TARGET_BYTES = 220 * 1024
HARD_CAP_BYTES = 250 * 1024
JPEG_QUALITIES = (82, 78, 74, 70, 66, 62, 58)


def find_gallery_node(obj, expected):
    """Find the Wix gallery object that owns the expected total and an items list."""
    if isinstance(obj, dict):
        total = obj.get("totalItemsCount")
        items = obj.get("items")
        try:
            total_int = int(total)
        except (TypeError, ValueError):
            total_int = None
        if total_int == expected and isinstance(items, list):
            return obj
        for value in obj.values():
            found = find_gallery_node(value, expected)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_gallery_node(value, expected)
            if found is not None:
                return found
    return None


def build_page_url(url, offset, limit=25):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["offset"] = str(offset)
    query["limit"] = str(limit)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def normalize_ref(item):
    candidates = [item.get("title"), item.get("name")]
    for raw in candidates:
        if not raw:
            continue
        value = str(raw).strip()
        value = re.sub(r"\.(?:jpe?g|png|webp|gif)$", "", value, flags=re.I).strip().upper()
        if re.fullmatch(r"[A-Z0-9_-]{4,50}", value):
            return value
    raise RuntimeError(f"Referência oficial inválida/inesperada: {candidates!r}")


def extract_media_url(item):
    direct = item.get("mediaUrl")
    if isinstance(direct, str) and direct.startswith("http"):
        return direct
    # Defensive fallback for possible Wix payload variations.
    stack = [item]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() == "mediaurl" and isinstance(child, str) and child.startswith("http"):
                    return child
                if isinstance(child, (dict, list)):
                    stack.append(child)
        elif isinstance(value, list):
            stack.extend(value)
    raise RuntimeError(f"Imagem oficial não localizada para {normalize_ref(item)}")


async def discover_api_url(page, context, collection):
    expected = collection["expected"]
    await page.goto(collection["url"], wait_until="domcontentloaded", timeout=90000)
    await page.wait_for_timeout(5000)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.75)")
    await page.wait_for_timeout(3500)

    urls = await page.evaluate(
        "performance.getEntriesByType('resource').map(e => e.name).filter(u => u.includes('/pro-gallery-webapp/v1/galleries/'))"
    )

    # If Wix deferred the gallery until interaction, trigger one public pagination request.
    if not urls:
        buttons = page.locator('button[aria-label*="Nossos Produtos"]')
        if await buttons.count():
            try:
                await buttons.last.scroll_into_view_if_needed()
                await buttons.last.click(timeout=8000)
                await page.wait_for_timeout(2500)
            except Exception:
                pass
        urls = await page.evaluate(
            "performance.getEntriesByType('resource').map(e => e.name).filter(u => u.includes('/pro-gallery-webapp/v1/galleries/'))"
        )

    for url in dict.fromkeys(urls):
        try:
            response = await context.request.get(url, headers={"Referer": collection["url"]}, timeout=30000)
            if not response.ok:
                continue
            payload = await response.json()
            node = find_gallery_node(payload, expected)
            if node is not None:
                return url
        except Exception:
            continue

    raise RuntimeError(
        f"Não foi possível localizar a galeria oficial de {collection['name']} com total {expected}. Nenhuma alteração será feita."
    )


async def fetch_official_items(context, api_url, collection):
    expected = collection["expected"]
    by_ref = {}
    offset = 0

    while offset < expected:
        url = build_page_url(api_url, offset=offset, limit=25)
        response = await context.request.get(url, headers={"Referer": collection["url"]}, timeout=30000)
        if not response.ok:
            raise RuntimeError(f"Falha HTTP {response.status} na galeria de {collection['name']} (offset {offset})")
        payload = await response.json()
        node = find_gallery_node(payload, expected)
        if node is None:
            raise RuntimeError(f"Resposta da galeria de {collection['name']} não confirma total oficial {expected}")

        items = node.get("items", [])
        if not items:
            raise RuntimeError(f"Página vazia inesperada em {collection['name']} (offset {offset})")

        for item in items:
            ref = normalize_ref(item)
            if ref in by_ref:
                raise RuntimeError(f"Referência duplicada na fonte oficial de {collection['name']}: {ref}")
            by_ref[ref] = {
                "ref": ref,
                "media_url": extract_media_url(item),
                "order": item.get("orderIndex", len(by_ref)),
            }
        offset += 25

    if len(by_ref) != expected:
        raise RuntimeError(
            f"Importação parcial bloqueada em {collection['name']}: fonte retornou {len(by_ref)} refs únicas; esperado {expected}."
        )

    def order_key(row):
        try:
            return (0, float(row["order"]))
        except (TypeError, ValueError):
            return (1, row["ref"])

    return sorted(by_ref.values(), key=order_key)


def download(url, referer):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; FabrikaCatalog/1.0)",
            "Referer": referer,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return response.read()


def encode_jpeg(img, quality):
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True, progressive=True, subsampling="4:2:0")
    return out.getvalue()


def optimize_bytes(raw):
    with Image.open(io.BytesIO(raw)) as source:
        img = ImageOps.exif_transpose(source).convert("RGB")

    if max(img.size) > MAX_LONG_EDGE:
        scale = MAX_LONG_EDGE / max(img.size)
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.Resampling.LANCZOS)

    best = None
    working = img
    for shrink_round in range(8):
        for quality in JPEG_QUALITIES:
            data = encode_jpeg(working, quality)
            best = data
            if len(data) <= TARGET_BYTES:
                return data
        if len(best) <= HARD_CAP_BYTES:
            return best
        new_size = (max(450, round(working.width * 0.90)), max(450, round(working.height * 0.90)))
        if new_size == working.size:
            break
        working = working.resize(new_size, Image.Resampling.LANCZOS)

    if best is None or len(best) > HARD_CAP_BYTES:
        raise RuntimeError(f"Não foi possível reduzir imagem para <= {HARD_CAP_BYTES} bytes")
    return best


def extract_data(html):
    marker = "let DATA="
    start = html.find(marker)
    if start < 0:
        raise RuntimeError("Bloco 'let DATA=' não localizado em index.html")
    start += len(marker)
    while start < len(html) and html[start].isspace():
        start += 1
    if start >= len(html) or html[start] != "[":
        raise RuntimeError("DATA não começa com array JSON")

    depth = 0
    in_string = False
    escaped = False
    end = None
    for pos in range(start, len(html)):
        ch = html[pos]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = pos + 1
                break
    if end is None:
        raise RuntimeError("Fim do array DATA não localizado")
    return json.loads(html[start:end]), start, end


def unique_value(items, key, collection_name):
    vals = []
    for item in items:
        value = item.get(key)
        if value not in vals:
            vals.append(value)
    if len(vals) != 1:
        raise RuntimeError(
            f"Campo {key!r} tem {len(vals)} valores na coleção {collection_name}; não vou adivinhar qual usar para novos itens: {vals!r}"
        )
    return vals[0]


def next_code_state(data):
    numbers = []
    widths = []
    for item in data:
        match = re.fullmatch(r"FK-(\d+)", str(item.get("codigo", "")), flags=re.I)
        if match:
            numbers.append(int(match.group(1)))
            widths.append(len(match.group(1)))
    if not numbers:
        raise RuntimeError("Nenhum código FK-numérico encontrado")
    return max(numbers), max(widths or [5])


def percentile95(values):
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


async def collect_all():
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 1200})
        page = await context.new_page()
        for collection in COLLECTIONS:
            api_url = await discover_api_url(page, context, collection)
            items = await fetch_official_items(context, api_url, collection)
            results[collection["name"]] = {"api_url": api_url, "items": items}
        await browser.close()
    return results


async def main():
    original_html = INDEX.read_text(encoding="utf-8")
    data, data_start, data_end = extract_data(original_html)
    catalog_before = len(data)

    official = await collect_all()

    # Validate ALL four official datasets before changing index.html or local images.
    for collection in COLLECTIONS:
        count = len(official[collection["name"]]["items"])
        if count != collection["expected"]:
            raise RuntimeError(f"Bloqueio de segurança: {collection['name']} trouxe {count}, esperado {collection['expected']}")

    max_code, code_width = next_code_state(data)
    next_number = max_code + 1
    audit_collections = []
    total_added = 0

    # Write images only after the whole official dataset has passed validation.
    for collection in COLLECTIONS:
        name = collection["name"]
        official_items = official[name]["items"]
        official_refs = [row["ref"] for row in official_items]
        official_ref_set = set(official_refs)

        positions = [i for i, item in enumerate(data) if item.get("fornecedor") == "Kantai" and item.get("colecao") == name]
        if not positions:
            raise RuntimeError(f"Coleção existente não localizada no catálogo: {name}")
        existing_items = [data[i] for i in positions]
        existing_by_ref = {}
        for item in existing_items:
            ref = str(item.get("ref", "")).strip().upper()
            if ref in existing_by_ref:
                raise RuntimeError(f"Duplicidade pré-existente em {name}: {ref}")
            existing_by_ref[ref] = item

        # Ensure business-sensitive fields are consistent before cloning them.
        for key in ("fornecedor", "colecao", "tipo", "medida", "preco"):
            unique_value(existing_items, key, name)

        template = deepcopy(existing_items[0])
        new_collection_items = []
        added_refs = []

        for row in official_items:
            ref = row["ref"]
            local_path = f"imagens/kantai/{collection['slug']}/thumbnails/{ref}.jpg"
            if ref in existing_by_ref:
                item = deepcopy(existing_by_ref[ref])
                item["card"] = local_path
                item["zoom"] = local_path
            else:
                item = deepcopy(template)
                item["codigo"] = f"FK-{next_number:0{code_width}d}"
                next_number += 1
                item["ref"] = ref
                item["card"] = local_path
                item["zoom"] = local_path
                if isinstance(item.get("cor"), list):
                    item["cor"] = []
                if isinstance(item.get("estilo"), list):
                    item["estilo"] = []
                added_refs.append(ref)
            new_collection_items.append(item)

        extras = sorted(set(existing_by_ref) - official_ref_set)
        if extras:
            raise RuntimeError(f"{name} contém refs locais que não aparecem na coleção oficial: {extras}")

        # Replace the collection as one block, in official order, at its current first position.
        first = min(positions)
        position_set = set(positions)
        data = [item for idx, item in enumerate(data) if idx not in position_set]
        data[first:first] = new_collection_items

        image_dir = ROOT / "imagens" / "kantai" / collection["slug"] / "thumbnails"
        image_dir.mkdir(parents=True, exist_ok=True)
        sizes = []
        for row in official_items:
            ref = row["ref"]
            target = image_dir / f"{ref}.jpg"
            raw = download(row["media_url"], collection["url"])
            optimized = optimize_bytes(raw)
            if len(optimized) > HARD_CAP_BYTES:
                raise RuntimeError(f"Imagem acima do teto após otimização: {name}/{ref} = {len(optimized)} bytes")
            target.write_bytes(optimized)
            sizes.append(len(optimized))

        # Remove stale JPG files from these four collection thumbnail folders only.
        valid_names = {f"{ref}.jpg" for ref in official_refs}
        for file in image_dir.glob("*.jpg"):
            if file.name not in valid_names:
                file.unlink()

        total_added += len(added_refs)
        audit_collections.append(
            {
                "colecao": name,
                "url_oficial": collection["url"],
                "total_oficial_esperado": collection["expected"],
                "total_api": len(official_items),
                "catalogo_antes": len(existing_items),
                "adicionados": len(added_refs),
                "catalogo_depois": len(new_collection_items),
                "refs_adicionadas": added_refs,
                "duplicidades_depois": len(official_refs) - len(set(official_refs)),
                "imagens_locais": len(sizes),
                "imagem_max_bytes": max(sizes) if sizes else 0,
                "imagem_p95_bytes": percentile95(sizes),
                "teto_imagem_bytes": HARD_CAP_BYTES,
                "medida_catalogo_preservada": unique_value(existing_items, "medida", name),
                "observacao_medida": "O importador preserva a medida comercial já existente no catálogo; especificações oficiais serão auditadas separadamente para não alterar dados de negócio silenciosamente.",
            }
        )

    compact_data = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    updated_html = original_html[:data_start] + compact_data + original_html[data_end:]
    INDEX.write_text(updated_html, encoding="utf-8")

    # Final structural validation.
    check_data, _, _ = extract_data(updated_html)
    if len(check_data) != catalog_before + total_added:
        raise RuntimeError(
            f"Total final inconsistente: {len(check_data)}; esperado {catalog_before + total_added}"
        )

    for collection in COLLECTIONS:
        rows = [x for x in check_data if x.get("fornecedor") == "Kantai" and x.get("colecao") == collection["name"]]
        refs = [str(x.get("ref", "")).upper() for x in rows]
        if len(rows) != collection["expected"] or len(set(refs)) != collection["expected"]:
            raise RuntimeError(f"Validação final falhou em {collection['name']}")
        for row in rows:
            for key in ("card", "zoom"):
                value = str(row.get(key, ""))
                if value.startswith("http://") or value.startswith("https://"):
                    raise RuntimeError(f"Dependência externa Kantai detectada: {collection['name']} {row.get('ref')} {key}")
                if not (ROOT / value).is_file():
                    raise RuntimeError(f"Imagem local ausente: {value}")

    audit = {
        "status": "ok",
        "catalogo_antes": catalog_before,
        "itens_adicionados": total_added,
        "catalogo_depois": len(check_data),
        "colecoes": audit_collections,
        "garantias": {
            "importacao_parcial_bloqueada": True,
            "imagens_kantai_externas_no_catalogo": 0,
            "limite_imagem_bytes": HARD_CAP_BYTES,
            "max_long_edge_px": MAX_LONG_EDGE,
        },
    }
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
