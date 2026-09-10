from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "auditoria-catalogo-consolidada.json"


def load(name: str) -> dict:
    path = ROOT / name
    if not path.exists():
        raise RuntimeError(f"Relatório obrigatório não encontrado: {name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Relatório inválido: {name}")
    return data


def audited_total(values: dict[str, object]) -> int:
    total = 0
    for value in values.values():
        try:
            total += int(value or 0)
        except (TypeError, ValueError):
            pass
    return total


def build_homefinish(report: dict, inventory_count: int) -> dict:
    audited_catalog_total = int(report.get("total_catalogo_home_finish") or 0)
    source_total = int(report.get("total_fonte_validada") or 0)
    current_match = inventory_count == audited_catalog_total == source_total
    base_ok = (
        report.get("status") == "ok"
        and int(report.get("total_faltando_no_catalogo") or 0) == 0
        and int(report.get("total_extras_no_catalogo") or 0) == 0
        and len(report.get("duplicatas_catalogo") or []) == 0
    )
    return {
        "fornecedor": "Home Finish",
        "itens_catalogo": inventory_count,
        "itens_auditados": audited_catalog_total,
        "itens_fonte_validada": source_total,
        "colecoes": report.get("colecoes_catalogo"),
        "status_colecoes_cadastradas": (
            "completo_contra_snapshot_validado_oficial"
            if base_ok and current_match
            else "divergente_ou_auditoria_desatualizada"
        ),
        "faltando": int(report.get("total_faltando_no_catalogo") or 0),
        "extras": int(report.get("total_extras_no_catalogo") or 0),
        "duplicidades": len(report.get("duplicatas_catalogo") or []),
        "totais_coincidem": current_match,
        "fonte": "Snapshot validado de URLs do domínio oficial homefinish.com.br",
        "relatorio": "auditoria-homefinish-fonte-validada.json",
        "observacao": "Os prefixos comerciais BH e MI são preservados no catálogo e normalizados apenas durante a comparação.",
    }


def build_kantai(report: dict, scope: dict, inventory_count: int) -> dict:
    rows = report.get("collections") or []
    audited: dict[str, object] = {}
    all_rows_ok = True
    for row in rows:
        name = row.get("name")
        if not name:
            continue
        audited[name] = row.get("unique_references")
        if row.get("status") != "ok":
            all_rows_ok = False
    audit_total = audited_total(audited)
    current_match = audit_total == inventory_count and bool(audited)
    return {
        "fornecedor": "Kantai",
        "itens_catalogo": inventory_count,
        "itens_auditados": audit_total,
        "colecoes_cadastradas": len(audited),
        "status_colecoes_cadastradas": (
            "completo_contra_fonte_oficial"
            if all_rows_ok and current_match
            else "divergente_ou_auditoria_desatualizada"
        ),
        "totais_coincidem": current_match,
        "colecoes_auditadas": audited,
        "cobertura_portfolio_oficial": {
            "status": scope.get("status"),
            "colecoes_oficiais_listadas": scope.get("colecoes_oficiais_listadas"),
            "colecoes_presentes_no_catalogo": scope.get("colecoes_presentes_no_catalogo"),
            "colecoes_ausentes_no_catalogo": scope.get("colecoes_ausentes_no_catalogo"),
            "amostras_declaradas_no_portfolio": scope.get("amostras_declaradas_no_portfolio"),
            "amostras_presentes_no_catalogo": scope.get("amostras_presentes_no_catalogo"),
            "amostras_declaradas_em_colecoes_ausentes": scope.get("amostras_declaradas_em_colecoes_ausentes"),
            "relatorio": "auditoria-kantai-escopo-oficial.json",
        },
        "fonte": "Site oficial Kantai / API pública das galerias Wix",
        "relatorio": "auditoria-kantai-oficial.json",
    }


def build_wiler(report: dict, inventory_count: int) -> dict:
    rows = report.get("colecoes") or []
    audited: dict[str, object] = {}
    all_rows_ok = True
    for row in rows:
        name = row.get("colecao")
        if not name:
            continue
        audited[name] = row.get("confirmado", row.get("catalogo"))
        status = str(row.get("status") or "")
        if not status.startswith("completo"):
            all_rows_ok = False
    audit_total = audited_total(audited)
    current_match = audit_total == inventory_count and bool(audited)
    return {
        "fornecedor": "Wiler",
        "itens_catalogo": inventory_count,
        "itens_auditados": audit_total,
        "colecoes_cadastradas": len(audited),
        "status_colecoes_cadastradas": (
            "completo_nas_cinco_colecoes_auditadas"
            if all_rows_ok and current_match
            else "divergente_ou_auditoria_desatualizada"
        ),
        "totais_coincidem": current_match,
        "colecoes_auditadas": audited,
        "fonte": "Fontes da cadeia de fornecimento e snapshot histórico do book de origem para Tacto",
        "relatorio": "auditoria-wiler-consolidada.json",
    }


def provider_registered_ok(row: dict) -> bool:
    return str(row.get("status_colecoes_cadastradas") or "").startswith("completo")


def main() -> None:
    inventory = load("auditoria-catalogo-atual.json")
    homefinish = load("auditoria-homefinish-fonte-validada.json")
    kantai = load("auditoria-kantai-oficial.json")
    kantai_scope = load("auditoria-kantai-escopo-oficial.json")
    wiler = load("auditoria-wiler-consolidada.json")

    suppliers = inventory.get("fornecedores") or {}
    integrity_ok = (
        len(inventory.get("codigos_duplicados") or []) == 0
        and int(inventory.get("total_refs_duplicadas") or 0) == 0
        and int(inventory.get("imagens_card_locais_faltantes") or 0) == 0
    )

    provider_rows = [
        build_homefinish(homefinish, int(suppliers.get("Home Finish") or 0)),
        build_kantai(kantai, kantai_scope, int(suppliers.get("Kantai") or 0)),
        build_wiler(wiler, int(suppliers.get("Wiler") or 0)),
    ]

    registered_complete = integrity_ok and all(provider_registered_ok(row) for row in provider_rows)

    report = {
        "status": "completo_nas_fontes_auditadas" if registered_complete else "revisao_necessaria",
        "escopo_status": "cobertura_portfolio_em_auditoria",
        "itens_catalogo": inventory.get("itens_catalogo"),
        "fornecedores": inventory.get("total_fornecedores"),
        "colecoes": inventory.get("total_colecoes"),
        "integridade_publicacao": {
            "codigos_duplicados": len(inventory.get("codigos_duplicados") or []),
            "referencias_duplicadas": int(inventory.get("total_refs_duplicadas") or 0),
            "imagens_locais_faltantes": int(inventory.get("imagens_card_locais_faltantes") or 0),
        },
        "cobertura_portfolio": {
            "Kantai": {
                "status": kantai_scope.get("status"),
                "colecoes_oficiais_listadas": kantai_scope.get("colecoes_oficiais_listadas"),
                "colecoes_presentes_no_catalogo": kantai_scope.get("colecoes_presentes_no_catalogo"),
                "colecoes_ausentes_no_catalogo": kantai_scope.get("colecoes_ausentes_no_catalogo"),
                "amostras_declaradas_em_colecoes_ausentes": kantai_scope.get("amostras_declaradas_em_colecoes_ausentes"),
            },
            "Home Finish": {"status": "a_validar_portfolio_completo"},
            "Wiler": {"status": "a_validar_portfolio_completo"},
        },
        "fornecedores_auditados": provider_rows,
        "criterio": "O status principal mede integridade e completude das coleções já cadastradas; não equivale a dizer que todo o portfólio atual de cada fornecedor está no catálogo. A cobertura de portfólio é registrada separadamente. Totais publicados precisam coincidir com os totais efetivamente auditados, evitando falso positivo após novas inclusões. Não usa versões ZIP/HTML antigas como fonte operacional.",
    }

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "escopo_status": report["escopo_status"],
        "itens_catalogo": report["itens_catalogo"],
        "fornecedores": report["fornecedores"],
        "colecoes": report["colecoes"],
        "integridade_ok": integrity_ok,
        "colecoes_cadastradas_ok": all(provider_registered_ok(row) for row in provider_rows),
        "kantai_portfolio": kantai_scope.get("status"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
