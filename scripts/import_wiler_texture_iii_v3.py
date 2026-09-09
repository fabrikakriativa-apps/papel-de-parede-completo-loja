from __future__ import annotations

import import_wiler_texture_iii as base

PRODUCT_BASE = "https://www.imperiopapeldeparede.com.br/produto/"


def product_id_for(ref: str) -> int:
    # A coleção Texture III é paginada pelo próprio número da referência:
    # TX-3005 -> produto 57838, TX-3010 -> 57843, TX-3019 -> 57852,
    # TX-3050 -> 57883. A fórmula abaixo apenas constrói a rota; a página
    # resultante é obrigatoriamente validada pela referência/coleção antes do uso.
    number = int(ref.split("-")[-1])
    if not 3001 <= number <= 3057:
        raise RuntimeError(f"Referência fora do intervalo Texture III: {ref}")
    return 57833 + (number - 3000)


def discover_product(page, ref: str) -> dict:
    url = f"{PRODUCT_BASE}{product_id_for(ref)}"
    response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
    if not response or response.status not in {200, 301, 302}:
        raise RuntimeError(f"Produto {ref} não abriu: HTTP {response.status if response else None}")
    page.wait_for_timeout(1200)
    body = page.locator("body").inner_text(timeout=10000).upper()
    if ref.upper() not in body:
        raise RuntimeError(f"Rota {url} não confirmou a referência {ref}")
    if "TEXTURE III" not in body:
        raise RuntimeError(f"Rota {url} não confirmou a coleção Texture III para {ref}")
    return {"href": page.url, "image": "", "text": body[:800]}


base.discover_product = discover_product

if __name__ == "__main__":
    base.main()
