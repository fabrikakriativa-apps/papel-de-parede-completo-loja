from __future__ import annotations

import base64
import html as html_lib
import json
import re
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
PAYLOAD = ROOT / "data" / "classificacoes_971_v15.b85"
REPORT = ROOT / "auditoria-classificacoes-971.json"
EXPECTED_CATALOG_ITEMS = 1207
EXPECTED_CURATED = 971


def load_classifications() -> list[dict]:
    encoded = PAYLOAD.read_text(encoding="utf-8").strip()
    raw = zlib.decompress(base64.b85decode(encoded.encode("ascii")))
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list):
        raise RuntimeError("Classification payload must be a list")
    return data


def unique_clean(values) -> list[str]:
    out = []
    seen = set()
    for value in values or []:
        value = str(value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def norm(value: object) -> str:
    return str(value or "").strip().upper()


def parse_catalog(html: str) -> tuple[list[dict], int, int]:
    marker = "let DATA="
    start = html.index(marker) + len(marker)
    decoder = json.JSONDecoder()
    data, consumed = decoder.raw_decode(html[start:])
    end = start + consumed
    if not isinstance(data, list):
        raise RuntimeError("Catalog DATA must be a list")
    return data, start, end


def rebuild_search(item: dict) -> str:
    parts = [
        item.get("codigo", ""),
        item.get("ref", ""),
        item.get("fornecedor", ""),
        item.get("colecao", ""),
        item.get("tipo", ""),
        item.get("medida", ""),
        *(item.get("cor") or []),
        *(item.get("estilo") or []),
        item.get("perfil", ""),
    ]
    return " ".join(str(x).strip() for x in parts if str(x or "").strip()).casefold()


def refresh_color_options(html: str, data: list[dict]) -> str:
    """Keep the existing color filter aligned with the catalog data.

    The 971 curated items use the final taxonomy. The 236 restored items are
    intentionally left untouched, so any legacy labels they still use are also
    exposed until those items receive their own curated review.
    """
    colors = sorted(
        {
            color
            for item in data
            for color in unique_clean(item.get("cor") or [])
        },
        key=lambda value: value.casefold(),
    )
    options = '<option value="">Todas as cores</option>' + "".join(
        f'<option>{html_lib.escape(color)}</option>' for color in colors
    )
    pattern = re.compile(r'(<select id="color">).*?(</select>)', re.DOTALL)
    updated, count = pattern.subn(
        lambda match: match.group(1) + options + match.group(2), html, count=1
    )
    if count != 1:
        raise RuntimeError("Could not refresh #color select options")
    return updated


def main() -> None:
    html = INDEX.read_text(encoding="utf-8")
    catalog, start, end = parse_catalog(html)
    curated = load_classifications()

    if len(catalog) != EXPECTED_CATALOG_ITEMS:
        raise RuntimeError(
            f"Catalog has {len(catalog)} items; expected {EXPECTED_CATALOG_ITEMS}"
        )
    if len(curated) != EXPECTED_CURATED:
        raise RuntimeError(
            f"Curated mapping has {len(curated)} items; expected {EXPECTED_CURATED}"
        )

    map_refs = [norm(row.get("ref")) for row in curated]
    map_codes = [norm(row.get("codigo")) for row in curated]
    dup_map_refs = sorted(ref for ref, n in Counter(map_refs).items() if ref and n > 1)
    dup_map_codes = sorted(code for code, n in Counter(map_codes).items() if code and n > 1)
    if dup_map_refs or dup_map_codes:
        raise RuntimeError(
            f"Duplicate curated keys: refs={dup_map_refs} codes={dup_map_codes}"
        )

    catalog_ref_counts = Counter(norm(item.get("ref")) for item in catalog)
    duplicate_catalog_refs = sorted(
        ref for ref, n in catalog_ref_counts.items() if ref and n > 1
    )
    if duplicate_catalog_refs:
        raise RuntimeError(
            f"Published catalog has duplicate refs: {duplicate_catalog_refs[:20]}"
        )
    catalog_by_ref = {norm(item.get("ref")): item for item in catalog}

    missing_refs = []
    code_mismatches = []
    blank_colors = []
    blank_styles = []
    updated_refs = set()

    for row in curated:
        ref = norm(row.get("ref"))
        code = norm(row.get("codigo"))
        item = catalog_by_ref.get(ref)
        if item is None:
            missing_refs.append({"codigo": code, "ref": ref})
            continue

        catalog_code = norm(item.get("codigo"))
        if catalog_code != code:
            # A supplier reference is the stable product identity. Keep the
            # current published FK code, record the historical code difference,
            # and apply the curated classification to the unique matching ref.
            code_mismatches.append(
                {
                    "ref": ref,
                    "codigo_curado": code,
                    "codigo_catalogo": catalog_code,
                }
            )

        colors = unique_clean(row.get("cores") or [])
        styles = unique_clean(row.get("estilos") or [])
        if not colors:
            blank_colors.append({"codigo": code, "ref": ref})
        if not styles:
            blank_styles.append({"codigo": code, "ref": ref})

        item["cor"] = colors
        item["estilo"] = styles
        item["perfil"] = str(row.get("perfil") or "").strip()
        item["search"] = rebuild_search(item)
        updated_refs.add(ref)

    if missing_refs or blank_colors or blank_styles:
        REPORT.write_text(
            json.dumps(
                {
                    "status": "erro",
                    "itens_catalogo": len(catalog),
                    "mapeamentos_curados": len(curated),
                    "refs_ausentes": missing_refs,
                    "codigos_divergentes": code_mismatches,
                    "sem_cor": blank_colors,
                    "sem_estilo": blank_styles,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise RuntimeError(
            "Curated classification overlay failed: "
            f"missing={len(missing_refs)} blank_colors={len(blank_colors)} "
            f"blank_styles={len(blank_styles)}"
        )

    preserved = len(catalog) - len(updated_refs)
    if (
        len(updated_refs) != EXPECTED_CURATED
        or preserved != EXPECTED_CATALOG_ITEMS - EXPECTED_CURATED
    ):
        raise RuntimeError(
            f"Overlay count mismatch: updated={len(updated_refs)} preserved={preserved}"
        )

    compact = json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
    new_html = html[:start] + compact + html[end:]
    new_html = refresh_color_options(new_html, catalog)
    INDEX.write_text(new_html, encoding="utf-8")

    report = {
        "status": "ok" if not code_mismatches else "ok_com_divergencia_de_codigo_historico",
        "fonte_classificacao": "classificacao_completa_971_v15_AJUSTES_FINAIS.csv",
        "itens_catalogo": len(catalog),
        "mapeamentos_curados": len(curated),
        "itens_atualizados": len(updated_refs),
        "itens_restaurados_preservados_sem_sobreposicao": preserved,
        "refs_ausentes": [],
        "codigos_divergentes": code_mismatches,
        "sem_cor_no_overlay": 0,
        "sem_estilo_no_overlay": 0,
        "perfil_infantil_no_overlay": sum(
            1
            for row in curated
            if str(row.get("perfil") or "").strip() == "Infantil"
        ),
        "cores_no_catalogo_apos_overlay": sorted(
            {
                color
                for item in catalog
                for color in unique_clean(item.get("cor") or [])
            },
            key=lambda value: value.casefold(),
        ),
        "estilos_curados": sorted(
            {
                style
                for item in catalog
                if norm(item.get("ref")) in updated_refs
                for style in unique_clean(item.get("estilo") or [])
            },
            key=lambda value: value.casefold(),
        ),
    }
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "itens_catalogo": report["itens_catalogo"],
                "itens_atualizados": report["itens_atualizados"],
                "itens_preservados": report[
                    "itens_restaurados_preservados_sem_sobreposicao"
                ],
                "divergencias_codigo_historico": len(code_mismatches),
                "sem_cor": 0,
                "sem_estilo": 0,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
