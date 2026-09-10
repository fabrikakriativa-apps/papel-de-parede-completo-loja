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


def build_homefinish(report: dict, inventory_count: int) -> dict:
    return {
        "fornecedor": "Home Finish",
        "itens_catalogo": inventory_count,
        "colecoes": report.get("colecoes_catalogo"),
        "status": (
            "completo_contra_snapshot_validado_oficial"
            if report.get("status") == "ok"
            else "divergente"
        ),
        "faltando": report.get("total_faltando_no_catalogo", 0),
        "extras": report.get("total_extras_no_catalogo", 0),
        "duplicidades": len(report.get("duplicatas_catalogo") or []),
        "fonte": "Snapshot validado de URLs do domínio oficial homefinish.com.br",
        "relatorio": "auditoria-homefinish-fonte-validada.json",
        "observacao": "Os prefixos comerciais BH e MI são preservados no catálogo e normalizados apenas durante a comparação.",
    }


def build_kantai(report: dict, inventory_count: int) -> dict:
    rows = report.get("collections") or []
    audited = {}
    all_ok = True
    for row in rows:
        name = row.get("name")
        if not name:
            continue
        count = row.get("unique_references")
        audited[name] = count
        if row.get("status") != "ok":
            all_ok = False
    if not rows:
        all_ok = False
    return {
        "fornecedor": "Kantai",
        "itens_catalogo": inventory_count,
        "colecoes": len(audited),
        "status": "completo_contra_fonte_oficial" if all_ok else "divergente",
        "colecoes_auditadas": audited,
        "fonte": "Site oficial Kantai / API pública das galerias Wix",
        "relatorio": "auditoria-kantai-oficial.json",
    }


def build_wiler(report: dict, inventory_count: int) -> dict:
    rows = report.get("colecoes") or []
    audited = {}
    all_ok = True
    for row in rows:
        name = row.get("colecao")
        if not name:
            continue
        audited[name] = row.get("confirmado", row.get("catalogo"))
        status = str(row.get("status") or "")
        if not status.startswith("completo"):
            all_ok = False
    if not rows:
        all_ok = False
    return {
        "fornecedor": "Wiler",
        "itens_catalogo": inventory_count,
        "colecoes": len(audited),
        "status": "completo_nas_cinco_colecoes_auditadas" if all_ok else "divergente",
        "colecoes_auditadas": audited,
        "fonte": "Fontes da cadeia de fornecimento e snapshot histórico do book de origem para Tacto",
        "relatorio": "auditoria-wiler-consolidada.json",
    }


def main() -> None:
    inventory = load("auditoria-catalogo-atual.json")
    homefinish = load("auditoria-homefinish-fonte-validada.json")
    kantai = load("auditoria-kantai-oficial.json")
    wiler = load("auditoria-wiler-consolidada.json")

    suppliers = inventory.get("fornecedores") or {}
    integrity_ok = (
        len(inventory.get("codigos_duplicados") or []) == 0
        and int(inventory.get("total_refs_duplicadas") or 0) == 0
        and int(inventory.get("imagens_card_locais_faltantes") or 0) == 0
    )

    provider_rows = [
        build_homefinish(homefinish, int(suppliers.get("Home Finish") or 0)),
        build_kantai(kantai, int(suppliers.get("Kantai") or 0)),
        build_wiler(wiler, int(suppliers.get("Wiler") or 0)),
    ]

    all_complete = integrity_ok and all(
        str(row.get("status") or "").startswith("completo") for row in provider_rows
    )

    report = {
        "status": "completo_nas_fontes_auditadas" if all_complete else "revisao_necessaria",
        "itens_catalogo": inventory.get("itens_catalogo"),
        "fornecedores": inventory.get("total_fornecedores"),
        "colecoes": inventory.get("total_colecoes"),
        "integridade_publicacao": {
            "codigos_duplicados": len(inventory.get("codigos_duplicados") or []),
            "referencias_duplicadas": int(inventory.get("total_refs_duplicadas") or 0),
            "imagens_locais_faltantes": int(inventory.get("imagens_card_locais_faltantes") or 0),
        },
        "fornecedores_auditados": provider_rows,
        "criterio": "Estado consolidado gerado automaticamente a partir do catálogo publicado e dos relatórios de auditoria. Não usa versões ZIP/HTML antigas como fonte operacional. Alterações futuras devem partir da main atual e das fontes de cadeia de fornecimento/oficiais correspondentes.",
    }

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "itens_catalogo": report["itens_catalogo"],
        "fornecedores": report["fornecedores"],
        "colecoes": report["colecoes"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
