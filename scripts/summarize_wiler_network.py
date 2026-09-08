from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "diagnostico-wiler-vtex.json"
REPORT = ROOT / "diagnostico-wiler-api-resumo.json"

ASSET_HOST_MARKERS = ("vtexassets.com", "io.vtex.com.br", "activity-flow.vtex.com")
DATA_HINT = re.compile(r"(?:graphql|productsearch|facets|search|products|catalog|segment|render-session|api/|_v/)", re.I)


def flatten_urls(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("url"), str):
            yield obj
        for value in obj.values():
            yield from flatten_urls(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from flatten_urls(value)


def main() -> None:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows = list(flatten_urls(data))
    unique = {}
    for row in rows:
        url = row.get("url", "")
        if url:
            unique.setdefault(url, row)

    host_counts = Counter(urlparse(u).netloc for u in unique)
    candidates = []
    for url, row in unique.items():
        host = urlparse(url).netloc.lower()
        path = urlparse(url).path.lower()
        content_type = str(row.get("content_type") or "").lower()
        is_asset = any(marker in host for marker in ASSET_HOST_MARKERS) and (
            path.endswith((".js", ".css", ".woff", ".woff2", ".png", ".jpg", ".svg"))
            or "/assets/" in path
        )
        if is_asset:
            continue
        if DATA_HINT.search(url) or "json" in content_type:
            candidates.append({
                "url": url,
                "host": host,
                "path": urlparse(url).path,
                "query": urlparse(url).query,
                "status": row.get("status"),
                "content_type": row.get("content_type"),
                "json_preview": row.get("json_preview"),
            })

    # Also record bundle evidence that names the VTEX search operations, useful
    # even when the browser request is sent through a generic GraphQL endpoint.
    raw = SOURCE.read_text(encoding="utf-8")
    operations = sorted(set(re.findall(r"Query(?:ProductSearchV\d+|FacetsV\d+|SearchMetadataV\d+|Products)", raw)))

    out = {
        "fonte": "diagnostico-wiler-vtex.json",
        "hosts_observados": dict(host_counts.most_common()),
        "operacoes_busca_vtex_detectadas": operations,
        "total_urls_unicas": len(unique),
        "candidatos_dados": candidates,
        "criterio": "Remove assets estáticos e mantém apenas chamadas/hosts com sinais de API, busca, catálogo, GraphQL ou JSON.",
    }
    REPORT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "urls_unicas": len(unique),
        "candidatos": len(candidates),
        "operacoes": operations,
        "hosts": dict(host_counts.most_common(10)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
