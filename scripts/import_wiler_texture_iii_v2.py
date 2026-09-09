from __future__ import annotations

import import_wiler_texture_iii as base


def discover_product(page, ref: str) -> dict:
    """Localiza o produto partindo dos próprios links /produto/, não da estrutura CSS.

    O site do distribuidor divide 'CÓD:' e a referência em elementos diferentes;
    por isso o primeiro importador, que procurava um nó de texto folha, não
    encontrou TX-3010. Aqui cada link de produto sobe pelos ancestrais até achar
    o card cujo texto contém a referência exata.
    """
    result = page.evaluate(
        r"""
        (ref) => {
          const clean = s => (s || '').replace(/\s+/g,' ').trim().toUpperCase();
          const wanted = clean(ref);
          const links = [...document.querySelectorAll('a[href*="/produto/"]')];
          for (const link of links) {
            let cur = link;
            for (let depth = 0; depth < 14 && cur; depth++, cur = cur.parentElement) {
              const text = clean(cur.innerText || cur.textContent);
              if (!text.includes(wanted)) continue;
              const img = cur.querySelector?.('img') || link.querySelector?.('img');
              return {
                href: link.href,
                image: img ? (img.currentSrc || img.src || img.dataset?.src || img.dataset?.lazySrc || img.getAttribute('data-original') || '') : '',
                text: text.slice(0, 800),
              };
            }
          }

          // Segundo caminho: encontre o menor bloco contendo a referência e
          // procure um link de produto dentro/ao redor dele.
          const blocks = [...document.querySelectorAll('body *')]
            .map(el => ({el, text: clean(el.innerText || el.textContent)}))
            .filter(x => x.text.includes(wanted))
            .sort((a,b) => a.text.length - b.text.length);
          for (const item of blocks.slice(0, 80)) {
            let cur = item.el;
            for (let depth = 0; depth < 14 && cur; depth++, cur = cur.parentElement) {
              const own = cur.matches?.('a[href*="/produto/"]') ? cur : null;
              const link = own || cur.querySelector?.('a[href*="/produto/"]');
              if (!link) continue;
              const img = cur.querySelector?.('img') || link.querySelector?.('img');
              return {
                href: link.href,
                image: img ? (img.currentSrc || img.src || img.dataset?.src || img.dataset?.lazySrc || img.getAttribute('data-original') || '') : '',
                text: clean(cur.innerText || cur.textContent).slice(0, 800),
              };
            }
          }
          return null;
        }
        """,
        ref,
    )
    if not result or not result.get("href"):
        raise RuntimeError(f"Não foi possível localizar o link do produto {ref} na página da coleção")
    return result


base.discover_product = discover_product

if __name__ == "__main__":
    base.main()
