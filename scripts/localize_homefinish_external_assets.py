from __future__ import annotations

import io
import json
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-localizacao-homefinish.json"
SUPPLIER = "Home Finish"
COLLECTION = "BIO Habitat"
TARGET_DIR = ROOT / "imagens" / "home-finish" / "bio-habitat" / "thumbnails"
EXPECTED_EXTERNAL_ITEMS = 28
ALLOWED_HOSTS = {"homefinish.com.br", "www.homefinish.com.br"}
MAX_SOURCE_BYTES = 12 * 1024 * 1024


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


def fetch_official_image(url: str) -> tuple[bytes, dict]:
    validate_official_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} ao buscar {url}")
        content_type = (response.headers.get("Content-Type") or "").lower()
        raw = response.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise RuntimeError(f"Imagem excede limite de segurança de {MAX_SOURCE_BYTES} bytes: {url}")
    if len(raw) < 1500:
        raise RuntimeError(f"Resposta pequena demais para ser imagem válida ({len(raw)} bytes): {url}")
    if content_type and not content_type.startswith("image/"):
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

    # Download and validate every source before changing index.html.
    try:
        for item in targets:
            ref = norm(item.get("ref"))
            card_url = norm(item.get("card"))
            zoom_url = norm(item.get("zoom"))
            if not is_external(card_url) or not is_external(zoom_url):
                raise RuntimeError(f"{ref}: card e zoom precisam estar externos nesta migração controlada")
            if card_url != zoom_url:
                raise RuntimeError(f"{ref}: card e zoom usam fontes diferentes; revisão manual necessária")

            raw, info = fetch_official_image(card_url)
            output = TARGET_DIR / f"{ref}{extension_for(info['format'])}"
            if output.exists():
                raise RuntimeError(f"Arquivo destino já existe e não será sobrescrito automaticamente: {output}")
            output.write_bytes(raw)
            staged_files.append(output)

            with Image.open(output) as check:
                check.verify()

            downloaded[ref] = {
                "source": card_url,
                "local": output.relative_to(ROOT).as_posix(),
                **info,
            }
    except Exception:
        for path in staged_files:
            path.unlink(missing_ok=True)
        raise

    # Only after all 28 images are valid do we switch DATA to local paths.
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
        "fontes": sorted({v["source"] for v in downloaded.values()}),
        "itens": downloaded,
        "criterio": "Copia byte a byte as mesmas imagens já usadas pelo catálogo a partir do domínio oficial Home Finish, valida formato e dimensões e só depois troca card/zoom para arquivos locais. Nenhuma recompressão ou substituição visual é realizada. A operação aborta e remove arquivos parciais se qualquer uma das 28 imagens falhar.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "imagens_localizadas": report["imagens_localizadas"],
        "itens_externalizados_depois": report["itens_externalizados_depois"],
        "bytes_preservados_da_fonte": report["bytes_preservados_da_fonte"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
