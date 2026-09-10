from __future__ import annotations

import io
import json
import re
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-import-texture-iii.json"
CATEGORY_URL = "https://www.imperiopapeldeparede.com.br/produtos/categoria/papel-de-parede-texture-iii"
SUPPLIER = "Wiler"
COLLECTION = "Texture III"
MISSING_REFS = ["TX-3010", "TX-3019", "TX-3037", "TX-3050", "TX-3052", "TX-3054"]
TARGET_DIR = ROOT / "imagens" / "wiler" / "texture-iii" / "thumbnails"
MAX_DIMENSION = 900
TARGET_BYTES = 300 * 1024
HARD_BYTES = 360 * 1024


def parse_index() -> tuple[str, list[dict], int, int]:
    text = INDEX.read_text(encoding="utf-8")
    marker = "let DATA="
    start = text.index(marker) + len(marker)
    data, consumed = json.JSONDecoder().raw_decode(text[start:])
    return text, data, start, start + consumed


def norm(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def next_fk_codes(data: list[dict], quantity: int) -> list[str]:
    used = set()
    maximum = 0
    for item in data:
        code = str(item.get("codigo") or "")
        m = re.fullmatch(r"FK-(\d+)", code)
        if m:
            n = int(m.group(1))
            used.add(n)
            maximum = max(maximum, n)
    out = []
    n = maximum + 1
    while len(out) < quantity:
        if n not in used:
            out.append(f"FK-{n:04d}")
        n += 1
    return out


def discover_card(page, ref: str) -> dict:
    result = page.evaluate(
        r"""
        async (ref) => {
          const clean = s => (s || '').replace(/\s+/g, ' ').trim().toUpperCase();
          const hasRef = el => {
            const t = clean(el.textContent);
            return t === ref || t === `CÓD: ${ref}` || t.endsWith(` ${ref}`) || t.includes(`CÓD: ${ref}`);
          };
          const refNodes = [...document.querySelectorAll('body *')]
            .filter(el => el.children.length === 0 && hasRef(el));
          if (refNodes.length) {
            refNodes[0].scrollIntoView({block: 'center'});
            await new Promise(resolve => setTimeout(resolve, 600));
          }

          const imageUrl = img => {
            if (!img) return '';
            const values = [
              img.currentSrc,
              img.getAttribute('src'),
              img.dataset?.src,
              img.dataset?.lazySrc,
              img.dataset?.original,
              img.getAttribute('data-original'),
              img.getAttribute('data-lazy'),
              img.getAttribute('data-image')
            ].filter(Boolean);
            for (const value of values) {
              if (/^https?:\/\//i.test(value)) return value;
            }
            const srcset = img.getAttribute('srcset') || img.getAttribute('data-srcset') || '';
            const candidate = srcset.split(',').map(x => x.trim().split(/\s+/)[0]).find(x => /^https?:\/\//i.test(x));
            return candidate || '';
          };

          const containers = [...document.querySelectorAll('article, li, div')]
            .map(el => ({el, text: clean(el.innerText)}))
            .filter(x => x.text.includes(ref) && x.el.querySelector('img'))
            .sort((a, b) => a.text.length - b.text.length);

          for (const item of containers) {
            const img = item.el.querySelector('img');
            const image = imageUrl(img);
            const links = [...item.el.querySelectorAll('a[href]')];
            const productLink = links.find(a => /\/produto\//i.test(a.href)) ||
                                links.find(a => /produto/i.test(a.href)) || null;
            if (image || productLink) {
              return {
                href: productLink ? productLink.href : '',
                image,
                text: item.text.slice(0, 800)
              };
            }
          }

          for (const node of refNodes) {
            let cur = node;
            for (let i = 0; i < 18 && cur; i++, cur = cur.parentElement) {
              const img = cur.querySelector?.('img');
              const image = imageUrl(img);
              const links = [...(cur.querySelectorAll?.('a[href]') || [])];
              const productLink = links.find(a => /\/produto\//i.test(a.href)) ||
                                  links.find(a => /produto/i.test(a.href)) || null;
              if (image || productLink) {
                return {
                  href: productLink ? productLink.href : '',
                  image,
                  text: clean(cur.innerText).slice(0, 800)
                };
              }
            }
          }
          return null;
        }
        """,
        ref,
    )
    if not result or (not result.get("href") and not result.get("image")):
        raise RuntimeError(f"Não foi possível localizar imagem ou página do card distribuidor de {ref}")
    return result


def discover_image(page, product_url: str, fallback: str) -> str:
    if fallback and fallback.startswith(("http://", "https://")):
        return fallback
    if not product_url:
        raise RuntimeError("Card sem imagem pública e sem link de produto")
    page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1500)
    candidates = []
    for selector, attr in [
        ('meta[property="og:image"]', 'content'),
        ('meta[name="twitter:image"]', 'content'),
    ]:
        loc = page.locator(selector)
        if loc.count():
            value = loc.first.get_attribute(attr)
            if value:
                candidates.append(value)
    for selector in ['img[src*="produto"]', 'img[src*="product"]', '.produto img', '.product img', 'main img']:
        loc = page.locator(selector)
        if loc.count():
            value = loc.first.get_attribute('src') or loc.first.get_attribute('data-src')
            if value:
                candidates.append(value)
    for value in candidates:
        if value and value.startswith(("http://", "https://")):
            return value
    raise RuntimeError(f"Nenhuma imagem pública encontrada em {product_url}")


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": CATEGORY_URL,
    })
    with urllib.request.urlopen(req, timeout=40) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} para imagem {url}")
        raw = response.read()
    if len(raw) < 1500:
        raise RuntimeError(f"Imagem suspeitamente pequena ({len(raw)} bytes): {url}")
    return raw


def optimize_jpeg(raw: bytes, output: Path) -> dict:
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        image = image.convert("RGB")
        image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
        best = None
        for quality in (82, 78, 74, 70):
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
            payload = buf.getvalue()
            best = (payload, quality, image.size)
            if len(payload) <= TARGET_BYTES:
                break
        payload, quality, size = best
        if len(payload) > HARD_BYTES:
            smaller = image.copy()
            smaller.thumbnail((800, 800), Image.Resampling.LANCZOS)
            for quality in (76, 72, 68):
                buf = io.BytesIO()
                smaller.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
                payload = buf.getvalue()
                best = (payload, quality, smaller.size)
                if len(payload) <= TARGET_BYTES:
                    break
            payload, quality, size = best
        if len(payload) > HARD_BYTES:
            raise RuntimeError(f"Não foi possível otimizar {output.name} abaixo de {HARD_BYTES} bytes")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)

    with Image.open(output) as check:
        check.verify()
    return {"bytes": output.stat().st_size, "quality": quality, "width": size[0], "height": size[1]}


def main() -> None:
    original_text, data, start, end = parse_index()
    existing = {
        norm(item.get("ref")): item
        for item in data
        if item.get("fornecedor") == SUPPLIER and item.get("colecao") == COLLECTION
    }
    already = [ref for ref in MISSING_REFS if norm(ref) in existing]
    pending = [ref for ref in MISSING_REFS if norm(ref) not in existing]

    if not pending:
        report = {
            "fonte": CATEGORY_URL,
            "fornecedor": SUPPLIER,
            "colecao": COLLECTION,
            "refs_confirmadas": MISSING_REFS,
            "adicionados": [],
            "ja_presentes": MISSING_REFS,
            "catalogo_antes": len(data),
            "catalogo_depois": len(data),
            "status": "ja_completo_para_as_refs_confirmadas",
        }
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return

    if already:
        raise RuntimeError(f"Estado parcial inesperado; já presentes={already}, pendentes={pending}. Nenhuma mutação feita.")
    if set(pending) != set(MISSING_REFS):
        raise RuntimeError("Conjunto pendente não corresponde exatamente às seis referências confirmadas")

    template = next((
        item for item in data
        if item.get("fornecedor") == SUPPLIER and item.get("colecao") == COLLECTION
    ), None)
    if not template:
        raise RuntimeError("Nenhum item Texture III existente para preservar tipo/medida/preço da coleção")

    discovered = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="pt-BR",
            viewport={"width": 1440, "height": 1200},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        )
        page = context.new_page()
        response = page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=30000)
        if not response or response.status != 200:
            raise RuntimeError(f"Fonte distribuidora indisponível: HTTP {response.status if response else None}")
        page.wait_for_timeout(2500)
        body = page.locator("body").inner_text(timeout=10000)
        if "58 produto" not in body.lower() or "CAT7154" not in body:
            raise RuntimeError("A coleção não confirmou 58 produtos + mostruário CAT7154; abortando sem mutação")
        for ref in MISSING_REFS:
            if ref not in body:
                raise RuntimeError(f"A fonte não confirmou {ref}; abortando sem mutação")
            card = discover_card(page, ref)
            image_url = discover_image(page, card.get("href", ""), card.get("image", ""))
            discovered[ref] = {
                "product_url": card.get("href") or CATEGORY_URL,
                "image_url": image_url,
                "card_text": card.get("text", ""),
            }
            if page.url != CATEGORY_URL:
                page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(700)
        browser.close()

    image_audit = {}
    created_files = []
    try:
        for ref in MISSING_REFS:
            output = TARGET_DIR / f"{ref}.jpg"
            raw = fetch_bytes(discovered[ref]["image_url"])
            image_audit[ref] = optimize_jpeg(raw, output)
            created_files.append(output)
    except Exception:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise

    codes = next_fk_codes(data, len(MISSING_REFS))
    added = []
    for code, ref in zip(codes, MISSING_REFS):
        local = f"imagens/wiler/texture-iii/thumbnails/{ref}.jpg"
        item = {
            "codigo": code,
            "ref": ref,
            "fornecedor": SUPPLIER,
            "colecao": COLLECTION,
            "tipo": template.get("tipo") or "Papel de parede",
            "medida": template.get("medida") or "Rolo: 0,53 m x 10 m",
            "preco": template.get("preco") or "",
            "card": local,
            "zoom": local,
            "search": f"{code} {ref} {SUPPLIER} {COLLECTION} {template.get('tipo') or 'Papel de parede'}".lower(),
            "cor": [],
            "estilo": [],
        }
        data.append(item)
        added.append(item)

    keys = [(norm(x.get("fornecedor")), norm(x.get("colecao")), norm(x.get("ref"))) for x in data]
    if len(keys) != len(set(keys)):
        for path in created_files:
            path.unlink(missing_ok=True)
        raise RuntimeError("Inclusão criaria fornecedor+coleção+referência duplicado; index não alterado")

    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    new_text = original_text[:start] + encoded + original_text[end:]
    INDEX.write_text(new_text, encoding="utf-8")

    _, final_data, _, _ = parse_index()
    final_refs = {
        norm(x.get("ref"))
        for x in final_data
        if x.get("fornecedor") == SUPPLIER and x.get("colecao") == COLLECTION
    }
    if any(norm(ref) not in final_refs for ref in MISSING_REFS):
        INDEX.write_text(original_text, encoding="utf-8")
        for path in created_files:
            path.unlink(missing_ok=True)
        raise RuntimeError("Validação pós-escrita falhou; alterações revertidas")

    report = {
        "fonte": CATEGORY_URL,
        "fonte_tipo": "Distribuidor/importador — cadeia de fornecimento",
        "fornecedor": SUPPLIER,
        "colecao": COLLECTION,
        "colecao_produtos_reportados": 58,
        "mostruario": "CAT7154",
        "papeis_confirmados": 57,
        "catalogo_antes": len(final_data) - len(added),
        "catalogo_depois": len(final_data),
        "texture_iii_antes": len(existing),
        "texture_iii_depois": len(final_refs),
        "refs_confirmadas_adicionadas": MISSING_REFS,
        "produtos": discovered,
        "imagens": image_audit,
        "total_bytes_novos": sum(x["bytes"] for x in image_audit.values()),
        "max_bytes": max(x["bytes"] for x in image_audit.values()),
        "runtime_hotlinks_novos": 0,
        "status": "ok",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
