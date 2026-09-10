from __future__ import annotations

import io
import json
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-localizacao-homefinish.json"
SUPPLIER = "Home Finish"
COLLECTION = "BIO Habitat"
COLLECTION_PAGE = "https://homefinish.com.br/colecoes/papeis-de-parede/bio-habitat/"
COLLECTION_PAGE_WWW = "https://www.homefinish.com.br/colecoes/papeis-de-parede/bio-habitat/"
TARGET_DIR = ROOT / "imagens" / "home-finish" / "bio-habitat" / "thumbnails"
EXPECTED_EXTERNAL_ITEMS = 28
ALLOWED_HOSTS = {"homefinish.com.br", "www.homefinish.com.br"}
MAX_SOURCE_BYTES = 12 * 1024 * 1024
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"


def parse_index() -> tuple[str, list[dict], int, int]:
    text = INDEX.read_text(encoding="utf-8")
    marker = "let DATA="
    start = text.index(marker) + len(marker)
    data, consumed = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(data, list) or not data:
        raise RuntimeError("DATA do catálogo vazio ou inválido")
    return text, data, start, start + consumed


def norm(value: object) -> str:
    return str(value or "").strip()


def is_external(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def validate_official_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise RuntimeError(f"URL externa não usa HTTPS: {url}")
    if parsed.netloc.casefold() not in ALLOWED_HOSTS:
        raise RuntimeError(f"Host externo não autorizado para esta rotina: {url}")
    if "/wp-content/uploads/" not in parsed.path:
        raise RuntimeError(f"URL Home Finish fora da biblioteca oficial esperada: {url}")


def official_variants(url: str) -> list[str]:
    validate_official_url(url)
    parsed = urlparse(url)
    if parsed.netloc.casefold() == "homefinish.com.br":
        alt = url.replace("https://homefinish.com.br/", "https://www.homefinish.com.br/", 1)
    else:
        alt = url.replace("https://www.homefinish.com.br/", "https://homefinish.com.br/", 1)
    return [url, alt] if alt != url else [url]


def referer_for(url: str) -> str:
    return COLLECTION_PAGE_WWW if urlparse(url).netloc.casefold().startswith("www.") else COLLECTION_PAGE


def validate_image_bytes(raw: bytes, content_type: str, url: str) -> tuple[bytes, dict]:
    if len(raw) > MAX_SOURCE_BYTES:
        raise RuntimeError(f"Imagem excede limite de segurança de {MAX_SOURCE_BYTES} bytes: {url}")
    if len(raw) < 1500:
        raise RuntimeError(f"Resposta pequena demais para ser imagem válida ({len(raw)} bytes): {url}")
    if content_type and not content_type.lower().startswith("image/"):
        raise RuntimeError(f"Content-Type inesperado {content_type!r}: {url}")

    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            info = {
                "format": image.format,
                "width": image.width,
                "height": image.height,
                "bytes": len(raw),
            }
    except Exception as exc:
        raise RuntimeError(f"Arquivo oficial não abriu como imagem: {url}: {exc}") from exc

    if info["format"] not in {"JPEG", "PNG", "WEBP"}:
        raise RuntimeError(f"Formato inesperado {info['format']} para {url}")
    if info["width"] < 200 or info["height"] < 200:
        raise RuntimeError(f"Imagem pequena demais ({info['width']}x{info['height']}): {url}")
    return raw, info


def fetch_with_urllib(url: str) -> tuple[bytes, dict]:
    validate_official_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": referer_for(url),
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} ao buscar {url}")
        content_type = response.headers.get("Content-Type") or ""
        raw = response.read(MAX_SOURCE_BYTES + 1)
    raw, info = validate_image_bytes(raw, content_type, url)
    info["metodo"] = "urllib_same_origin_referer"
    info["source_resolved"] = url
    return raw, info


def fetch_with_browser(context, page, url: str) -> tuple[bytes, dict]:
    validate_official_url(url)
    referer = referer_for(url)
    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": referer,
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-origin",
    }

    response = context.request.get(url, headers=headers, timeout=45000, fail_on_status_code=False)
    if response.status == 200:
        raw = response.body()
        raw, info = validate_image_bytes(raw, response.headers.get("content-type", ""), url)
        info["metodo"] = "playwright_api_context"
        info["source_resolved"] = url
        return raw, info

    page.set_extra_http_headers({
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": referer,
    })
    nav = page.goto(url, wait_until="commit", timeout=45000)
    if not nav or nav.status != 200:
        raise RuntimeError(
            f"api_status={response.status}, browser_status={nav.status if nav else None}, url={url}"
        )
    raw = nav.body()
    raw, info = validate_image_bytes(raw, nav.headers.get("content-type", ""), url)
    info["metodo"] = "playwright_browser_navigation"
    info["source_resolved"] = url
    return raw, info


def fetch_official_image(context, page, url: str) -> tuple[bytes, dict]:
    errors: list[str] = []
    variants = official_variants(url)

    for candidate in variants:
        try:
            return fetch_with_urllib(candidate)
        except Exception as exc:
            errors.append(f"urllib {candidate}: {exc}")
            print(f"urllib bloqueado para {candidate}: {exc}", flush=True)

    for candidate in variants:
        try:
            return fetch_with_browser(context, page, candidate)
        except Exception as exc:
            errors.append(f"browser {candidate}: {exc}")
            print(f"navegador bloqueado para {candidate}: {exc}", flush=True)

    raise RuntimeError("Todas as rotas oficiais Home Finish foram bloqueadas: " + " | ".join(errors))


def extension_for(fmt: str) -> str:
    return {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[fmt]


def count_external_items(data: list[dict]) -> int:
    return sum(
        1 for item in data
        if is_external(norm(item.get("card"))) or is_external(norm(item.get("zoom")))
    )


def main() -> None:
    original_text, data, start, end = parse_index()
    external_before = [
        item for item in data
        if is_external(norm(item.get("card"))) or is_external(norm(item.get("zoom")))
    ]
    targets = [
        item for item in external_before
        if norm(item.get("fornecedor")) == SUPPLIER and norm(item.get("colecao")) == COLLECTION
    ]

    if len(external_before) != EXPECTED_EXTERNAL_ITEMS or len(targets) != EXPECTED_EXTERNAL_ITEMS:
        raise RuntimeError(
            f"Escopo mudou: externos globais={len(external_before)}, BIO Habitat={len(targets)}, "
            f"esperado={EXPECTED_EXTERNAL_ITEMS}. Nenhuma alteração feita."
        )

    refs = [norm(item.get("ref")) for item in targets]
    if len(refs) != len(set(refs)) or any(not ref for ref in refs):
        raise RuntimeError("Referências externas BIO Habitat vazias ou duplicadas; nenhuma alteração feita")

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    downloaded: dict[str, dict] = {}
    staged_files: list[Path] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="pt-BR",
            user_agent=UA,
            viewport={"width": 1440, "height": 1200},
        )
        page = context.new_page()

        for warmup_url in (COLLECTION_PAGE, COLLECTION_PAGE_WWW):
            try:
                warmup = page.goto(warmup_url, wait_until="domcontentloaded", timeout=45000)
                print(f"Home Finish warmup {warmup_url} status={warmup.status if warmup else None}", flush=True)
                page.wait_for_timeout(600)
            except Exception as exc:
                print(f"Warmup Home Finish não concluiu em {warmup_url}: {exc}", flush=True)

        try:
            for item in targets:
                ref = norm(item.get("ref"))
                card_url = norm(item.get("card"))
                zoom_url = norm(item.get("zoom"))
                if not is_external(card_url) or not is_external(zoom_url):
                    raise RuntimeError(f"{ref}: card e zoom precisam estar externos nesta migração controlada")
                if card_url != zoom_url:
                    raise RuntimeError(f"{ref}: card e zoom usam fontes diferentes; revisão manual necessária")

                raw, info = fetch_official_image(context, page, card_url)
                output = TARGET_DIR / f"{ref}{extension_for(info['format'])}"
                if output.exists():
                    raise RuntimeError(f"Arquivo destino já existe e não será sobrescrito automaticamente: {output}")
                output.write_bytes(raw)
                staged_files.append(output)

                with Image.open(output) as check:
                    check.verify()

                downloaded[ref] = {
                    "source_requested": card_url,
                    "source_resolved": info["source_resolved"],
                    "local": output.relative_to(ROOT).as_posix(),
                    "format": info["format"],
                    "width": info["width"],
                    "height": info["height"],
                    "bytes": info["bytes"],
                    "metodo": info["metodo"],
                }
                print(
                    f"LOCALIZED {ref} {info['width']}x{info['height']} {info['bytes']} bytes via {info['metodo']} {info['source_resolved']}",
                    flush=True,
                )
        except Exception:
            for path in staged_files:
                path.unlink(missing_ok=True)
            raise
        finally:
            browser.close()

    for item in targets:
        ref = norm(item.get("ref"))
        local = downloaded[ref]["local"]
        item["card"] = local
        item["zoom"] = local

    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    new_text = original_text[:start] + encoded + original_text[end:]
    INDEX.write_text(new_text, encoding="utf-8")

    try:
        _, final_data, _, _ = parse_index()
        external_after = count_external_items(final_data)
        if external_after != 0:
            raise RuntimeError(f"Migração incompleta: ainda restaram {external_after} itens externos")
        if len(final_data) != len(data):
            raise RuntimeError("Quantidade de itens mudou durante localização de imagens")
        for ref, info in downloaded.items():
            path = ROOT / info["local"]
            if not path.is_file():
                raise RuntimeError(f"Asset local não existe após escrita: {ref} -> {path}")
    except Exception:
        INDEX.write_text(original_text, encoding="utf-8")
        for path in staged_files:
            path.unlink(missing_ok=True)
        raise

    report = {
        "status": "ok",
        "fornecedor": SUPPLIER,
        "colecao": COLLECTION,
        "itens_catalogo_preservados": len(data),
        "itens_externalizados_antes": len(external_before),
        "itens_externalizados_depois": 0,
        "imagens_localizadas": len(downloaded),
        "bytes_preservados_da_fonte": sum(int(v["bytes"]) for v in downloaded.values()),
        "metodos": sorted({v["metodo"] for v in downloaded.values()}),
        "fontes_resolvidas": sorted({v["source_resolved"] for v in downloaded.values()}),
        "itens": downloaded,
        "criterio": "Copia byte a byte as mesmas imagens já usadas pelo catálogo a partir exclusivamente dos domínios oficiais homefinish.com.br ou www.homefinish.com.br. Tenta ambas as rotas oficiais por requisição de mesma origem e Chromium/Playwright. Valida formato, dimensões e todos os 28 arquivos antes de trocar card/zoom para caminhos locais. Nenhuma recompressão ou substituição visual é realizada; falha parcial é revertida.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "imagens_localizadas": report["imagens_localizadas"],
        "itens_externalizados_depois": report["itens_externalizados_depois"],
        "bytes_preservados_da_fonte": report["bytes_preservados_da_fonte"],
        "metodos": report["metodos"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
