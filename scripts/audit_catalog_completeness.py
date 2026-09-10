from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "auditoria-completude.json"


def load(name: str) -> dict:
    path = ROOT / name
    if not path.exists():
        raise RuntimeError(f"Relatório obrigatório não encontrado: {name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Relatório inválido: {name}")
    return data


def main() -> None:
    inventory = load("auditoria-catalogo-atual.json")
    consolidated = load("auditoria-catalogo-consolidada.json")

    inventory_items = int(inventory.get("itens_catalogo") or 0)
    consolidated_items = int(consolidated.get("itens_catalogo") or 0)
    inventory_collections = int(inventory.get("total_colecoes") or 0)
    consolidated_collections = int(consolidated.get("colecoes") or 0)
    inventory_suppliers = int(inventory.get("total_fornecedores") or 0)
    consolidated_suppliers = int(consolidated.get("fornecedores") or 0)

    if inventory_items != consolidated_items:
        raise RuntimeError(
            f"Inventário e auditoria consolidada divergem em itens: "
            f"{inventory_items} != {consolidated_items}"
        )
    if inventory_collections != consolidated_collections:
        raise RuntimeError(
            f"Inventário e auditoria consolidada divergem em coleções: "
            f"{inventory_collections} != {consolidated_collections}"
        )
    if inventory_suppliers != consolidated_suppliers:
        raise RuntimeError(
            f"Inventário e auditoria consolidada divergem em fornecedores: "
            f"{inventory_suppliers} != {consolidated_suppliers}"
        )

    supplier_inventory = inventory.get("fornecedores") or {}
    provider_rows = consolidated.get("fornecedores_auditados") or []
    providers = []
    provider_divergences = 0

    for row in provider_rows:
        name = str(row.get("fornecedor") or "").strip()
        if not name:
            continue
        current_count = int(supplier_inventory.get(name) or 0)
        audited_count = int(row.get("itens_auditados") or 0)
        registered_status = str(row.get("status_colecoes_cadastradas") or "")
        totals_match = bool(row.get("totais_coincidem")) and current_count == audited_count
        registered_complete = registered_status.startswith("completo") and totals_match
        if not registered_complete:
            provider_divergences += 1

        portfolio = row.get("cobertura_portfolio_oficial") or {}
        providers.append({
            "fornecedor": name,
            "itens_catalogo": current_count,
            "itens_auditados": audited_count,
            "colecoes_cadastradas": row.get("colecoes_cadastradas"),
            "status_colecoes_cadastradas": registered_status,
            "totais_coincidem": totals_match,
            "cobertura_portfolio_status": portfolio.get("status"),
            "relatorio_fonte": row.get("relatorio"),
        })

    expected_provider_names = set(supplier_inventory)
    audited_provider_names = {row["fornecedor"] for row in providers}
    if expected_provider_names != audited_provider_names:
        raise RuntimeError(
            "Fornecedores do inventário e da auditoria consolidada divergem: "
            f"inventário={sorted(expected_provider_names)}, "
            f"auditados={sorted(audited_provider_names)}"
        )

    integrity = consolidated.get("integridade_publicacao") or {}
    registered_complete = (
        consolidated.get("status") == "completo_nas_fontes_auditadas"
        and provider_divergences == 0
        and int(integrity.get("codigos_duplicados") or 0) == 0
        and int(integrity.get("referencias_duplicadas") or 0) == 0
        and int(integrity.get("imagens_locais_faltantes") or 0) == 0
    )

    report = {
        "status": "completo_nas_fontes_auditadas" if registered_complete else "revisao_necessaria",
        "metodo": "auditoria_consolidada_por_fontes_validadas",
        "autoridade_atual": "auditoria-catalogo-consolidada.json",
        "comparacao_biblioteca_fisica": "descontinuada",
        "motivo_descontinuacao": (
            "A antiga auditoria inferia completude pela presença de thumbnails em "
            "_image_source/imagens. Essa estrutura não representa mais as fontes de verdade "
            "atuais e podia reportar biblioteca 0 e marcar todo o catálogo como extra."
        ),
        "itens_catalogo": inventory_items,
        "fornecedores_catalogo": inventory_suppliers,
        "colecoes_catalogo": inventory_collections,
        "colecoes_auditadas_registradas": sum(int(row.get("colecoes_cadastradas") or 0) for row in providers),
        "fornecedores_com_divergencia": provider_divergences,
        "integridade_publicacao": integrity,
        "escopo_portfolio": consolidated.get("escopo_status"),
        "portfolio_statuses": consolidated.get("portfolio_statuses") or {},
        "fornecedores": providers,
        "criterio": (
            "Compara o inventário publicado com as auditorias consolidadas por fornecedor. "
            "O status de completude refere-se somente às coleções já cadastradas e auditadas; "
            "não significa cobertura integral do portfólio atual dos fornecedores. A cobertura "
            "de portfólio é registrada separadamente. Não usa ZIP/HTML antigo nem a presença "
            "física de thumbnails da biblioteca como fonte operacional."
        ),
    }

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "itens_catalogo": report["itens_catalogo"],
        "fornecedores_catalogo": report["fornecedores_catalogo"],
        "colecoes_catalogo": report["colecoes_catalogo"],
        "colecoes_auditadas_registradas": report["colecoes_auditadas_registradas"],
        "fornecedores_com_divergencia": report["fornecedores_com_divergencia"],
        "comparacao_biblioteca_fisica": report["comparacao_biblioteca_fisica"],
        "escopo_portfolio": report["escopo_portfolio"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
