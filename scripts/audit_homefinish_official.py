from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT = ROOT / "auditoria-homefinish-oficial.json"
PAGE_PARAM = "e-page-23ca821"

# URLs exatas das coleções já cadastradas e das lacunas confirmadas.
# As coleções DiCoração usam /colecoes/dicoracao/, enquanto as demais usam
# /colecoes/papeis-de-parede/. Guardar a URL completa evita inferência de rota.
COLLECTION_URLS = {
    "BIO Habitat": "https://www.homefinish.com.br/colecoes/papeis-de-parede/bio-habitat/",
    "Biomas": "https://www.homefinish.com.br/colecoes/papeis-de-parede/biomas/",
    "Bosque da Imaginação": "https://www.homefinish.com.br/colecoes/papeis-de-parede/bosque-da-imaginacao/",
    "Botânica": "https://www.homefinish.com.br/colecoes/papeis-de-parede/botanica/",
    "Doce Estilo": "https://www.homefinish.com.br/colecoes/papeis-de-parede/doce-estilo/",
    "Era Uma Vez": "https://www.homefinish.com.br/colecoes/papeis-de-parede/era-uma-vez/",
    "Flora": "https://www.homefinish.com.br/colecoes/papeis-de-parede/flora/",
    "HF Texture III": "https://www.homefinish.com.br/colecoes/papeis-de-parede/hf-textures-3/",
    "Memórias de Infância": "https://www.homefinish.com.br/colecoes/papeis-de-parede/memorias-de-infancia/",
    "Natureza Lúdica": "https://www.homefinish.com.br/colecoes/papeis-de-parede/natureza-ludica/",
    "Passeio no Campo": "https://www.homefinish.com.br/colecoes/papeis-de-parede/passeio-no-campo/",
    "Provence": "https://www.homefinish.com.br/colecoes/papeis-de-parede/provence/",
    "Tartan": "https://www.homefinish.com.br/colecoes/papeis-de-parede/tartan/",
    "HF Orient": "https://www.homefinish.com.br/colecoes/papeis-de-parede/hf-orient/",
    "HF Orient II": "https://www.homefinish.com.br/colecoes/papeis-de-parede/hf-orient-ii/",
    "Mundo Encantado": "https://www.homefinish.com.br/colecoes/papeis-de-parede/mundo-encantado/",
    "Vichy": "https://www.homefinish.com.br/colecoes/dicoracao/vichy/",
    "Bosque": "https://www.homefinish.com.br/colecoes/dicoracao/bosque/",
    "Xadrez": "https://www.homefinish.com.br/colecoes/dicoracao/xadrez/",
    "Temáticos": "https://www.homefinish.com.br/colecoes/dicoracao/tematicos/",
    "Floresta Brasileira": "https://www.homefinish.com.br/colecoes/dicoracao/floresta-brasileira/",
    "Clássicos": "https://www.homefinish.com.br/colecoes/dicoracao/classicos/",
    "Fundo do Mar": "https://www.homefinish.com.br/colecoes/dicoracao/fundo-do-mar/",
    "Montanhas": "https://www.homefinish.com.br/colecoes/dicoracao/montanhas/",
    "Safari": "https://www.homefinish.com.br/colecoes/dicoracao/safari/",
}

# A coleção está confirmada por metadado oficial de produto, mas sua rota de
# coleção ainda não foi capturada. Não inferir slug para fazê-la parecer auditável.
CONFIRMED_WITHOUT_COLLECTION_URL = {
    "As Crônicas de Nárnia": {
        "referencias_confirmadas": ["603664"],
        "evidencia": "Metadado COLEÇÃO em página oficial Home Finish",
    }
}

REF_TEXT_RE = re.compile(r"^[A-Z]{0,6}(?:-?[A-Z]{0,3})?-?\d{2,9}[A-Z]?$", re.I)
REF_SLUG_RE = re.compile(r"(?:^|-)([A-Z]{1,6}-?\d{2,9}[A-Z]?|\d{3,9}[A-Z]?)$", re.I)


def parse_data() -> list[dict]:
    text = INDEX.read_text(encoding="utf-8")
    marker = "let DATA="
    start = text.index(marker) + len(marker)
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    return data


def norm(value: object, collection: str) -> str:
    s = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if collection == "BIO Habitat" and s.startswith("BH"):
        s = s[2:]
    if collection == "Memórias de Infância" and s.startswith("MI"):
        s = s[2:]
    return s


def extract_ref(text: str, href: str) -> str | None:
    text = re.sub(r"\s+", " ", text or "").strip()
    if text and len(text) <= 24 and REF_TEXT_RE.fullmatch(text):
        return text.upper().replace(" ", "")
    path = urllib.parse.urlparse(href or "").path.rstrip("/")
    product_slug = path.rsplit("/", 1)[-1]
    product_slug = re.sub(r"^papel-de-parede-", "", product_slug, flags=re.I)
    m = REF_SLUG_RE.search(product_slug)
    return m.group(1).upper() if m else None


def refs_from_page(page) -> set[str]:
    rows = page.evaluate("""
        () => {
          const heads = [...document.querySelectorAll('h1,h2,h3,h4')];
          const stop = heads.find(h => /TALVEZ.*GOST/i.test((h.textContent || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g,'')));
          return [...document.querySelectorAll('a[href*="/papel-de-parede/"]')]
            .filter(a => !stop || (a.compareDocumentPosition(stop) & Node.DOCUMENT_POSITION_FOLLOWING))
            .map(a => ({text:(a.textContent || '').trim(), href:a.href}));
        }
    """)
    refs = set()
    for row in rows:
        ref = extract_ref(row.get("text", ""), row.get("href", ""))
        if ref:
            refs.add(ref)
    return refs


def page_url(base_url: str, number: int) -> str:
    if number == 1:
        return base_url
    separator = "&" if "?" in base_url else "?"
    return base_url + separator + urllib.parse.urlencode({PAGE_PARAM: number})


def crawl(page, base_url: str) -> tuple[set[str], list[dict]]:
    all_refs: set[str] = set()
    pages = []
    for number in range(1, 25):
        url = page_url(base_url, number)
        response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        status = response.status if response else None
        title = page.title()
        refs = refs_from_page(page) if status == 200 else set()
        new_refs = refs - all_refs
        pages.append({
            "pagina": number,
            "url": url,
            "http": status,
            "titulo": title,
            "refs_encontradas": len(refs),
            "novas": len(new_refs),
        })
        if number == 1 and (status != 200 or not refs):
            raise RuntimeError(
                f"Página oficial não auditável: HTTP {status}, {len(refs)} refs, título={title!r}"
            )
        if number > 1 and not new_refs:
            break
        all_refs.update(refs)
    return all_refs, pages


def main() -> None:
    data = parse_data()
    results = []
    errors = []
    partial_missing = 0
    partial_extras = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="pt-BR",
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/152.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"image", "font", "media"}
            else route.continue_(),
        )

        for collection, official_url in COLLECTION_URLS.items():
            catalog_raw = {
                str(x.get("ref") or "").strip()
                for x in data
                if x.get("fornecedor") == "Home Finish"
                and x.get("colecao") == collection
                and str(x.get("ref") or "").strip()
            }
            try:
                official_refs, pages = crawl(page, official_url)
            except Exception as exc:
                error_text = f"{type(exc).__name__}: {exc}"
                errors.append({
                    "colecao": collection,
                    "url_oficial": official_url,
                    "erro": error_text,
                })
                results.append({
                    "colecao": collection,
                    "url_oficial": official_url,
                    "oficial": None,
                    "catalogo": len(catalog_raw),
                    "faltantes": None,
                    "extras_no_catalogo": None,
                    "paginas": [],
                    "status": "erro_coleta",
                })
                continue

            official_norm = {norm(r, collection): r for r in official_refs if norm(r, collection)}
            catalog_norm = {norm(r, collection): r for r in catalog_raw if norm(r, collection)}
            missing_keys = sorted(set(official_norm) - set(catalog_norm))
            extra_keys = sorted(set(catalog_norm) - set(official_norm))
            missing = [official_norm[k] for k in missing_keys]
            extras = [catalog_norm[k] for k in extra_keys]
            partial_missing += len(missing)
            partial_extras += len(extras)
            results.append({
                "colecao": collection,
                "url_oficial": official_url,
                "oficial": len(official_refs),
                "catalogo": len(catalog_raw),
                "faltantes": missing,
                "extras_no_catalogo": extras,
                "paginas": pages,
                "status": "ok",
            })

        browser.close()

    valid = [r for r in results if r["oficial"] is not None]
    unresolved_names = sorted(CONFIRMED_WITHOUT_COLLECTION_URL)
    complete_collection_audit = len(valid) == len(results) and not unresolved_names
    all_403 = bool(errors) and all("HTTP 403" in str(row.get("erro") or "") for row in errors)

    if complete_collection_audit:
        audit_status = "ok"
    elif not valid and all_403:
        audit_status = "bloqueado_pela_origem_http_403"
    elif valid:
        audit_status = "parcial_com_falhas_ou_rotas_pendentes"
    else:
        audit_status = "sem_coleta_confiavel"

    report = {
        "status": audit_status,
        "fonte": "Home Finish — páginas oficiais das coleções lidas em navegador real",
        "fornecedor_catalogo": "Home Finish",
        "colecoes_com_url_configurada": len(results),
        "colecoes_confirmadas_sem_url_de_colecao": CONFIRMED_WITHOUT_COLLECTION_URL,
        "colecoes_confirmadas_sem_url_de_colecao_total": len(unresolved_names),
        "colecoes_confirmadas_no_escopo_desta_rotina": len(results) + len(unresolved_names),
        "colecoes_auditadas_com_sucesso": len(valid),
        "colecoes_com_falha_de_coleta": len(errors),
        "auditoria_integral": complete_collection_audit,
        "erros_coleta": errors,
        "total_oficial_parcial": sum(int(r["oficial"] or 0) for r in valid),
        "total_catalogo_nas_colecoes_configuradas": sum(r["catalogo"] for r in results),
        "total_faltantes_confirmados": partial_missing if complete_collection_audit else None,
        "total_extras_confirmados": partial_extras if complete_collection_audit else None,
        "faltantes_confirmados_nas_colecoes_coletadas": partial_missing,
        "extras_confirmados_nas_colecoes_coletadas": partial_extras,
        "nao_inferir_zero_em_falha": True,
        "nao_inferir_rota_de_colecao": True,
        "rotas_colecao_explicitas": True,
        "colecoes": results,
        "criterio": (
            "Navega pelas URLs oficiais exatas e pela paginação pública da Home Finish em Chromium. "
            "As rotas DiCoração são mantidas separadas das rotas de papéis de parede tradicionais. "
            "Coleções confirmadas por metadado oficial, mas ainda sem rota capturada, ficam explicitamente "
            "fora da enumeração automática até a URL ser comprovada. Falhas de acesso nunca são tratadas "
            "como zero itens ou zero faltantes. Os totais globais de faltantes/extras só recebem número "
            "quando todas as coleções confirmadas do escopo estiverem integralmente auditáveis."
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": audit_status,
        "colecoes_com_url": len(results),
        "colecoes_sem_url": len(unresolved_names),
        "colecoes_ok": len(valid),
        "erros": len(errors),
        "total_oficial_parcial": report["total_oficial_parcial"],
        "total_catalogo_nas_colecoes_configuradas": report["total_catalogo_nas_colecoes_configuradas"],
        "faltantes_globais": report["total_faltantes_confirmados"],
        "extras_globais": report["total_extras_confirmados"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
