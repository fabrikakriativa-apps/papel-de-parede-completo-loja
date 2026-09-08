from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "diagnostico-wiler-vtex.json"
REPORT = ROOT / "diagnostico-wiler-api-resumo.json"

ASSET_HOST_MARKERS = ("vtexassets.com", "io.vtex.com.br", "activity-flow.vtex.com")
DATA_HINT = re.compile(r"(?:graphql|productsearch|facets|search|products|catalog|segment|render-session|api/|_v/)", re.I)
SEARCH_OP = re.compile(r"(?:productsearch|facets|searchmetadata|products)", re.I)


def flatten_urls(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("url"), str):
            yield obj
        for value in obj.values():
            yield from flatten_urls(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from flatten_urls(value)


def operation_from_row(url: str, row: dict) -> str | None:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if qs.get("operationName"):
        return qs["operationName"][0]
    post = row.get("post_data")
    if not post:
        return None
    try:
        payload = json.loads(post)
        if isinstance(payload, dict):
            return payload.get("operationName")
    except Exception:
        pass
    m = re.search(r'operationName["\'=:%20]+([A-Za-z0-9_]+)', unquote(str(post)))
    return m.group(1) if m else None


def main() -> None:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows = list(flatten_urls(data))
    unique = {}
    for row in rows:
        url = row.get("url", "")
        if url:
            key = (row.get("method"), url, row.get("post_data"))
            unique.setdefault(key, row)

    host_counts = Counter(urlparse(k[1]).netloc for k in unique)
    candidates = []
    search_calls = []
    for (_, url, _), row in unique.items():
        host = urlparse(url).netloc.lower()
        path = urlparse(url).path.lower()
        content_type = str(row.get("content_type") or "").lower()
        is_asset = any(marker in host for marker in ASSET_HOST_MARKERS) and (
            path.endswith((".js", ".css", ".woff", ".woff2", ".png", ".jpg", ".svg"))
            or "/assets/" in path
        )
        if is_asset:
            continue
        op = operation_from_row(url, row)
        item = {
            "url": url,
            "host": host,
            "path": urlparse(url).path,
            "query": urlparse(url).query,
            "method": row.get("method"),
            "resource_type": row.get("resource_type"),
            "operation_name": op,
            "post_data": row.get("post_data"),
            "status": row.get("status"),
            "content_type": row.get("content_type"),
            "json_preview": row.get("json_preview"),
        }
        if DATA_HINT.search(url) or "json" in content_type or row.get("resource_type") in {"xhr", "fetch"}:
            candidates.append(item)
        if (op and SEARCH_OP.search(op)) or SEARCH_OP.search(str(row.get("post_data") or "")):
            search_calls.append(item)

    raw = SOURCE.read_text(encoding="utf-8")
    operations = sorted(set(re.findall(r"Query(?:ProductSearchV\d+|FacetsV\d+|SearchMetadataV\d+|Products)", raw)))

    out = {
        "fonte": "diagnostico-wiler-vtex.json",
        "hosts_observados": dict(host_counts.most_common()),
        "operacoes_busca_vtex_detectadas": operations,
        "total_requisicoes_unicas": len(unique),
        "chamadas_busca": search_calls,
        "candidatos_dados": candidates,
        "criterio": "Preserva método, resource type e corpo das requisições. Destaca chamadas cujo operationName/post_data indique ProductSearch, Facets, SearchMetadata ou Products.",
    }
    REPORT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "requisicoes_unicas": len(unique),
        "candidatos": len(candidates),
        "chamadas_busca": len(search_calls),
        "operacoes": operations,
        "hosts": dict(host_counts.most_common(10)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
