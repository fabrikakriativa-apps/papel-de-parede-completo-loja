from __future__ import annotations

import asyncio

import import_kantai as base


async def discover_api_url(page, context, collection):
    """Discover the public Wix gallery endpoint by intercepting browser network requests.

    This replaces performance.getEntriesByType(), which does not reliably expose
    Wix's gallery calls on GitHub Actions. We only capture public requests made by
    the official collection page and then validate the candidate against the
    collection's exact official item total before accepting it.
    """
    expected = collection["expected"]
    captured = []

    def observe_request(request):
        url = request.url
        if "/pro-gallery-webapp/v1/galleries/" in url:
            captured.append(url)

    page.on("request", observe_request)
    await page.goto(collection["url"], wait_until="domcontentloaded", timeout=90000)
    await page.wait_for_timeout(4500)

    # Wix may defer the product gallery request until the gallery approaches the viewport.
    for fraction in (0.45, 0.70, 0.88, 1.0):
        await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {fraction})")
        await page.wait_for_timeout(1000)

    # Trigger a public pagination request as a second discovery path. This does not
    # alter source data; it merely causes Wix to request the next gallery batch.
    buttons = page.get_by_role("button", name=base.re.compile("Mais páginas de Nossos Produtos", base.re.I))
    if await buttons.count() == 0:
        buttons = page.locator('button[aria-label*="Nossos Produtos"]')
    if await buttons.count():
        try:
            btn = buttons.last
            await btn.scroll_into_view_if_needed()
            await btn.click(timeout=10000)
            await page.wait_for_timeout(2200)
        except Exception:
            pass

    # Validate each intercepted candidate using the public endpoint itself.
    for url in dict.fromkeys(captured):
        try:
            response = await context.request.get(
                url,
                headers={"Referer": collection["url"]},
                timeout=30000,
            )
            if not response.ok:
                continue
            payload = await response.json()
            node = base.find_gallery_node(payload, expected)
            if node is not None:
                print(f"Galeria oficial localizada: {collection['name']} -> total {expected}")
                return url
        except Exception:
            continue

    raise RuntimeError(
        f"Não foi possível validar a galeria pública de {collection['name']} com total {expected}. "
        f"Foram interceptadas {len(set(captured))} chamadas de galeria; nenhuma alteração será feita."
    )


# Keep every safety check and import rule from the original importer; replace only
# the fragile endpoint-discovery strategy.
base.discover_api_url = discover_api_url


if __name__ == "__main__":
    asyncio.run(base.main())
