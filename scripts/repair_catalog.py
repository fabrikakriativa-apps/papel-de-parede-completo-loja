from __future__ import annotations

import repair_catalog_original as original

MASTER_EXPECTED_ITEMS = 1212
PUBLISHED_EXPECTED_ITEMS = 1207
DISCONTINUED_BAMBINE_REFS = frozenset({"BA0047", "BA0048", "BA0049", "BA0050"})


def norm_ref(value: object) -> str:
    return str(value or "").strip().upper()


def norm_text(value: object) -> str:
    return str(value or "").strip().casefold()


def is_invalid_provence_84360(item: dict) -> bool:
    return (
        norm_ref(item.get("ref")) == "84360"
        and norm_text(item.get("colecao")) == "provence"
    )


def exclusion_reason(item: dict) -> str | None:
    ref = norm_ref(item.get("ref"))
    if ref in DISCONTINUED_BAMBINE_REFS:
        return f"Bambine descontinuado: {ref}"
    if is_invalid_provence_84360(item):
        return "registro Provence inválido: 84360"
    return None


def apply_publication_filter(data: list[dict]) -> list[dict]:
    """Publish exactly 1,207 items without removing the valid Flora 84360.

    Authorized removals are the four discontinued Bambine panels and only the
    84360 record that belongs to Provence. The valid Flora 84360 must remain.
    The check is intentionally idempotent for subsequent repair runs.
    """
    before = len(data)
    flagged = [(item, exclusion_reason(item)) for item in data if exclusion_reason(item)]

    if before == MASTER_EXPECTED_ITEMS:
        if len(flagged) != 5:
            details = [
                f"{item.get('codigo')}|{item.get('ref')}|{item.get('colecao')}|{reason}"
                for item, reason in flagged
            ]
            raise RuntimeError(
                "Publication filter safety check failed; expected exactly 5 authorized records "
                f"to remove, found {len(flagged)}: " + "; ".join(details)
            )

        found_bambine = {
            norm_ref(item.get("ref"))
            for item, _ in flagged
            if norm_ref(item.get("ref")) in DISCONTINUED_BAMBINE_REFS
        }
        if found_bambine != DISCONTINUED_BAMBINE_REFS:
            raise RuntimeError(
                "Publication filter safety check failed; Bambine exclusion set mismatch. "
                f"Expected {sorted(DISCONTINUED_BAMBINE_REFS)}, found {sorted(found_bambine)}"
            )

        invalid_provence = [item for item, _ in flagged if is_invalid_provence_84360(item)]
        if len(invalid_provence) != 1:
            raise RuntimeError(
                "Publication filter safety check failed; expected exactly one Provence 84360 "
                f"record, found {len(invalid_provence)}"
            )

        filtered = [item for item in data if exclusion_reason(item) is None]

    elif before == PUBLISHED_EXPECTED_ITEMS:
        if flagged:
            details = [
                f"{item.get('codigo')}|{item.get('ref')}|{item.get('colecao')}|{reason}"
                for item, reason in flagged
            ]
            raise RuntimeError(
                "Publication filter safety check failed; an already-published catalog still "
                "contains authorized exclusions: " + "; ".join(details)
            )
        filtered = data

    else:
        raise RuntimeError(
            f"Publication filter count mismatch before filtering: {before}. "
            f"Expected {MASTER_EXPECTED_ITEMS} (master) or {PUBLISHED_EXPECTED_ITEMS} (published)."
        )

    if len(filtered) != PUBLISHED_EXPECTED_ITEMS:
        raise RuntimeError(
            f"Publication filter count mismatch after filtering: {len(filtered)}. "
            f"Expected {PUBLISHED_EXPECTED_ITEMS}."
        )

    remaining_bambine = {
        norm_ref(item.get("ref"))
        for item in filtered
        if norm_ref(item.get("ref")) in DISCONTINUED_BAMBINE_REFS
    }
    if remaining_bambine:
        raise RuntimeError(
            "Publication filter failed; discontinued Bambine refs remain: "
            + ", ".join(sorted(remaining_bambine))
        )

    remaining_invalid_provence = [item for item in filtered if is_invalid_provence_84360(item)]
    if remaining_invalid_provence:
        raise RuntimeError("Publication filter failed; invalid Provence 84360 still remains")

    valid_84360 = [item for item in filtered if norm_ref(item.get("ref")) == "84360"]
    if len(valid_84360) != 1 or norm_text(valid_84360[0].get("colecao")) != "flora":
        details = [
            f"{item.get('codigo')}|{item.get('ref')}|{item.get('colecao')}"
            for item in valid_84360
        ]
        raise RuntimeError(
            "Publication filter safety check failed; expected exactly one valid Flora 84360 "
            "after filtering. Found: " + "; ".join(details)
        )

    print(
        "[publish] "
        f"before={before} after={len(filtered)} "
        "excluded=84360(Provence),BA0047,BA0048,BA0049,BA0050 "
        f"kept_84360={valid_84360[0].get('codigo')}|{valid_84360[0].get('colecao')}"
    )
    return filtered


original.apply_publication_filter = apply_publication_filter


if __name__ == "__main__":
    original.main()
