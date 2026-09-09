from __future__ import annotations

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "diagnostico-texture-iii-cards.json"
URL = "https://www.imperiopapeldeparede.com.br/produtos/categoria/papel-de-parede-texture-iii"
REFS = ["TX-3010", "TX-3019", "TX-3037", "TX-3050", "TX-3052", "TX-3054"]

SCRIPT = r"""
(ref) => {
  const clean = s => (s || '').replace(/\s+/g,' ').trim();
  const wanted = ref.toUpperCase();
  const textNodes = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    if ((n.nodeValue || '').toUpperCase().includes(wanted)) textNodes.push(n);
  }
  const out = [];
  for (const node of textNodes.slice(0, 20)) {
    let el = node.parentElement;
    const ancestors = [];
    for (let depth = 0; depth < 12 && el; depth++, el = el.parentElement) {
      const imgs = [...el.querySelectorAll('img')].slice(0, 8).map(img => ({
        src: img.src || '', currentSrc: img.currentSrc || '',
        dataSrc: img.getAttribute('data-src') || '',
        dataOriginal: img.getAttribute('data-original') || '',
        lazy: img.getAttribute('data-lazy') || img.getAttribute('data-lazy-src') || '',
        alt: img.alt || ''
      }));
      const links = [...el.querySelectorAll('a')].slice(0, 12).map(a => ({href:a.href || '', text:clean(a.textContent).slice(0,120)}));
      const attrs = {};
      for (const a of [...el.attributes]) {
        if (a.name.startsWith('data-') || ['id','class','onclick','href','src','value','name'].includes(a.name)) attrs[a.name] = a.value;
      }
      ancestors.push({
        depth,
        tag: el.tagName,
        attrs,
        text: clean(el.innerText || el.textContent).slice(0,1000),
        imgs,
        links,
        html: el.outerHTML.slice(0,12000)
      });
    }
    out.push({nodeText: clean(node.nodeValue), ancestors});
  }
  return out;
}
"""


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="pt-BR",
            viewport={"width": 1440, "height": 1400},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        )
        page = context.new_page()
        response = page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3500)
        for _ in range(8):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(400)
        result = {
            "url": URL,
            "http": response.status if response else None,
            "title": page.title(),
            "refs": {ref: page.evaluate(SCRIPT, ref) for ref in REFS},
        }
        browser.close()
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({ref: len(rows) for ref, rows in result['refs'].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
