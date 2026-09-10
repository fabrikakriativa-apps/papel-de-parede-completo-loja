from __future__ import annotations

import io
import json
import urllib.error
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
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36"


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
        raise RuntimeError(f"Host externo não autorizado: {url}")
    if "/wp-content/uploads/" not in parsed.path:
        raise RuntimeError(f"URL Home Finish fora da biblioteca oficial esperada: {url}")


def validate_image(raw: bytes, content_type: str, url: str) -> dict:
    if len(raw) > MAX_SOURCE_BYTES:
        raise RuntimeError(f"Imagem excede {MAX_SOURCE_BYTES} bytes: {url}")
    if len(raw) < 1500:
        raise RuntimeError(f"Resposta pequena demais para imagem ({len(raw)} bytes): {url}")
    if content_type and not content_type.lower().startswith("image/"):
        raise RuntimeError(f"Content-Type inesperado {content_type!r}: {url}")
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        info = {
            "format": image.format,
            "width": image.width,
            "height": image.height,
            "bytes": len(raw),
        }
    if info["format"] not in {"JPEG", "PNG", "WEBP"}:
        raise RuntimeError(f"Formato inesperado {info['format']}: {url}")
    if info["width"] < 200 or info["height"] < 200:
        raise RuntimeError(f"Imagem pequena demais {info['width']}x{info['height']}: {url}")
    return info


def fetch_direct(url: str) -> tuple[bytes, dict]:
    validate_official_url(url)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} ao buscar {url}")
        content_type = response.headers.get("Content-Type") or ""
        raw = response.read(MAX_SOURCE_BYTES + 1)
    return raw, validate_image(raw, content_type, url)


def extension_for(fmt: str) -> str:
    return {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[fmt]


def external_items(data: list[dict]) -> list[dict]:
    return [
        item for item in data
        if is_external(norm(item.get("card"))) or is_external(norm(item.get("zoom")))
    ]


def write_blocked_report(data: list[dict], targets: list[dict], error: str) -> None:
    report = {
        "status": "bloqueado_pela_origem_http_403",
        "fornecedor": SUPPLIER,
        "colecao": COLLECTION,
        "itens_catalogo_preservados": len(data),
        "itens_externalizados_antes": len(targets),
        "itens_externalizados_depois": len(targets),
        "imagens_localizadas": 0,
        "origem": "homefinish.com.br",
        "erro": error,
        "acao_segura": "Catálogo preservado sem alteração. Mantidos os URLs oficiais com política no-referrer; nenhum proxy, screenshot ou recompressão foi usado.",
        "retentativa": "Pode ser executado novamente por workflow_dispatch. Se a origem voltar a aceitar o runner, a mesma rotina fará a localização direta.",
        "referencias": [norm(item.get("ref")) for item in targets],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "externos_preservados": len(targets)}, ensure_ascii=False))


def main() -> None:
    original_text, data, start, end = parse_index()
    before = external_items(data)
    targets = [
        item for item in before
        if norm(item.get("fornecedor")) == SUPPLIER and norm(item.get("colecao")) == COLLECTION
    ]

    if not before:
        report = {
            "status": "ok",
            "fornecedor": SUPPLIER,
            "colecao": COLLECTION,
            "itens_catalogo_preservados": len(data),
            "itens_externalizados_antes": 0,
            "itens_externalizados_depois": 0,
            "imagens_localizadas": 0,
            "observacao": "Nenhum asset externo permanece no catálogo.",
        }
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return

    if len(before) != EXPECTED_EXTERNAL_ITEMS or len(targets) != EXPECTED_EXTERNAL_ITEMS:
        raise RuntimeError(
            f"Escopo mudou: externos globais={len(before)}, BIO Habitat={len(targets)}, esperado={EXPECTED_EXTERNAL_ITEMS}."
        )

    refs = [norm(item.get("ref")) for item in targets]
    if any(not ref for ref in refs) or len(refs) != len(set(refs)):
        raise RuntimeError("Referências BIO Habitat externas vazias ou duplicadas")

    for item in targets:
        card = norm(item.get("card"))
        zoom = norm(item.get("zoom"))
        validate_official_url(card)
        validate_official_url(zoom)
        if card != zoom:
            raise RuntimeError(f"{item.get('ref')}: card e zoom usam fontes diferentes")

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    downloaded: dict[str, dict] = {}
    staged: list[Path] = []

    try:
        for item in targets:
            ref = norm(item.get("ref"))
            url = norm(item.get("card"))
            try:
                raw, info = fetch_direct(url)
            except urllib.error.HTTPError as exc:
                if exc.code == 403:
                    for path in staged:
                        path.unlink(missing_ok=True)
                    write_blocked_report(data, targets, f"HTTP 403 ao acessar diretamente {url}")
                    return
                raise

            output = TARGET_DIR / f"{ref}{extension_for(info['format'])}"
            if output.exists():
                raise RuntimeError(f"Destino já existe; não será sobrescrito: {output}")
            output.write_bytes(raw)
            staged.append(output)
            with Image.open(output) as check:
                check.verify()
            downloaded[ref] = {
                "source": url,
                "local": output.relative_to(ROOT).as_posix(),
                **info,
            }
    except Exception:
        for path in staged:
            path.unlink(missing_ok=True)
        raise

    for item in targets:
        local = downloaded[norm(item.get("ref"))]["local"]
        item["card"] = local
        item["zoom"] = local

    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    INDEX.write_text(original_text[:start] + encoded + original_text[end:], encoding="utf-8")

    try:
        _, final_data, _, _ = parse_index()
        after = external_items(final_data)
        if after:
            raise RuntimeError(f"Migração incompleta: ainda restam {len(after)} itens externos")
        if len(final_data) != len(data):
            raise RuntimeError("Quantidade de itens mudou durante a localização")
        for info in downloaded.values():
            if not (ROOT / info["local"]).is_file():
                raise RuntimeError(f"Arquivo local ausente após escrita: {info['local']}")
    except Exception:
        INDEX.write_text(original_text, encoding="utf-8")
        for path in staged:
            path.unlink(missing_ok=True)
        raise

    report = {
        "status": "ok",
        "fornecedor": SUPPLIER,
        "colecao": COLLECTION,
        "itens_catalogo_preservados": len(data),
        "itens_externalizados_antes": len(before),
        "itens_externalizados_depois": 0,
        "imagens_localizadas": len(downloaded),
        "bytes_preservados_da_fonte": sum(int(v["bytes"]) for v in downloaded.values()),
        "itens": downloaded,
        "criterio": "Download direto do domínio oficial Home Finish; bytes preservados sem recompressão. Alteração do DATA somente após validação das 28 imagens.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "imagens_localizadas": len(downloaded), "externos_depois": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
