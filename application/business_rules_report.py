from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from infrastructure.extraction.prompts import BUSINESS_RULES_OUTPUT_TEMPLATE
from application.classification_helpers import SECTION_ALIASES, get_classification_data

EMPTY_SECTION = "(nao identificado)"
_DATA = get_classification_data("pt-br")

_TABLE_HEADER = ("#", "regra", "contexto")
_TABLE_HEADER_RE = re.compile(r"^\s*\|\s*#\s*\|\s*Regra\s*\|\s*Contexto\s*\|\s*$")
_TABLE_HEADER_NORMALIZED_RE = re.compile(
    r"^\s*\|\s*#\s*\|\s*[Rr]egra\s*\|\s*[Cc]ontexto\s*\|\s*$"
)
_TABLE_SEPARATOR_RE = re.compile(r"^\|\s*-+\s*\|\s*-+\s*\|\s*-+\s*\|$")
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*+]|(?:\d+[.)]))\s*")
_CHECKBOX_RE = re.compile(r"^\s*\[[xX\s]\]\s*")


def build_business_rules_markdown(
    extracted_markdown: str,
    *,
    date: str,
    participants: list[str],
) -> str:
    sections = parse_report_sections(extracted_markdown)

    summary = _normalize_block(sections["summary"])
    decisions = _normalize_block(sections["decisions"])
    rules_rows, actions_from_rules = _normalize_rules_section(sections["rules"])
    actions, rules_from_actions = _normalize_actions_section(
        sections["actions"],
        actions_from_rules,
    )
    rules_rows.extend(rules_from_actions)
    open_questions = _normalize_block(sections["open_questions"])

    rules_rows = _dedupe_rule_rows(rules_rows)
    actions = _dedupe_action_items(actions)
    rules_table = "\n".join(rules_rows) if rules_rows else EMPTY_SECTION

    return BUSINESS_RULES_OUTPUT_TEMPLATE.format(
        date=date,
        participants="\n".join(f"- {participant}" for participant in participants),
        summary=summary,
        decisions=decisions,
        rules_table=rules_table,
        actions=actions,
        open_questions=open_questions,
    )


def parse_report_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {key: [] for key in SECTION_ALIASES}
    current_section: str | None = None

    for raw_line in text.splitlines():
        section_name = _match_section_heading(raw_line)
        if section_name:
            current_section = section_name
            continue

        if _is_heading(raw_line):
            current_section = None
            continue

        if current_section is not None:
            sections[current_section].append(raw_line.rstrip())

    return {
        key: "\n".join(lines).strip()
        for key, lines in sections.items()
    }


def _match_section_heading(line: str) -> str | None:
    normalized = _normalize_for_compare(line)
    if not normalized.startswith("## "):
        return None

    heading = normalized[3:].strip()
    for section_name, aliases in SECTION_ALIASES.items():
        if heading in aliases:
            return section_name
    return None


def _is_heading(line: str) -> bool:
    return _normalize_for_compare(line).startswith("## ")


def _normalize_for_compare(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    normalized = normalized.lower().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _normalize_block(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip() or EMPTY_SECTION


def _normalize_rules_section(text: str) -> tuple[list[str], list[str]]:
    rules: list[tuple[str, str]] = []
    actions: list[str] = []
    seen_rules: set[tuple[str, str]] = set()
    seen_actions: set[str] = set()

    for raw_line in _non_empty_lines(text):
        cells = _split_table_row(raw_line)
        if cells is not None:
            # Remover cabecalhos duplicados da tabela de regras
            if _is_table_header(cells) or _TABLE_SEPARATOR_RE.match(raw_line.strip()):
                continue
            if _TABLE_HEADER_NORMALIZED_RE.match(raw_line.strip()):
                continue

            rule_text = cells[1] if len(cells) > 1 else ""
            context_text = cells[2] if len(cells) > 2 else ""
            verdict = _classify_text(rule_text or " ".join(cells))
            if verdict == "action":
                action_item = _normalize_action_item(rule_text or " ".join(cells))
                if action_item and action_item not in seen_actions:
                    actions.append(action_item)
                    seen_actions.add(action_item)
                continue

            rule_item = _clean_item_text(rule_text or " ".join(cells))
            if not rule_item:
                continue
            context_item = _clean_item_text(context_text) or EMPTY_SECTION
            key = (_normalize_for_compare(rule_item), _normalize_for_compare(context_item))
            if key not in seen_rules:
                rules.append((rule_item, context_item))
                seen_rules.add(key)
            continue

        # Remover cabecalhos duplicados em formato de texto
        if _TABLE_HEADER_NORMALIZED_RE.match(raw_line.strip()):
            continue

        verdict = _classify_text(raw_line)
        if verdict == "action":
            action_item = _normalize_action_item(raw_line)
            if action_item and action_item not in seen_actions:
                actions.append(action_item)
                seen_actions.add(action_item)
        elif verdict == "rule":
            rule_item = _clean_item_text(raw_line)
            if rule_item:
                key = (_normalize_for_compare(rule_item), _normalize_for_compare(EMPTY_SECTION))
                if key not in seen_rules:
                    rules.append((rule_item, EMPTY_SECTION))
                    seen_rules.add(key)

    rendered_rules = [
        f"| {index} | {rule} | {context} |"
        for index, (rule, context) in enumerate(rules, start=1)
    ]
    return rendered_rules, actions


def _normalize_actions_section(
    text: str,
    extra_actions: Iterable[str],
) -> tuple[str, list[str]]:
    actions: list[str] = []
    seen_actions: set[str] = set()
    extra_rules: list[str] = []
    seen_rules: set[tuple[str, str]] = set()

    def add_action(item: str | None) -> None:
        if not item:
            return
        key = _normalize_for_compare(item)
        if key and key not in seen_actions:
            actions.append(item)
            seen_actions.add(key)

    def add_rule(item: str | None, context: str = EMPTY_SECTION) -> None:
        if not item:
            return
        key = (_normalize_for_compare(item), _normalize_for_compare(context))
        if key not in seen_rules:
            extra_rules.append(f"| 0 | {item} | {context} |")
            seen_rules.add(key)

    for raw_line in _non_empty_lines(text):
        cells = _split_table_row(raw_line)
        if cells is not None:
            # Remover cabecalhos duplicados da tabela de regras
            if _is_table_header(cells) or _TABLE_SEPARATOR_RE.match(raw_line.strip()):
                continue
            if _TABLE_HEADER_NORMALIZED_RE.match(raw_line.strip()):
                continue

            action_text = cells[1] if len(cells) > 1 else ""
            verdict = _classify_text(action_text or " ".join(cells))
            if verdict == "rule":
                add_rule(_clean_item_text(action_text or " ".join(cells)))
            else:
                add_action(_normalize_action_item(action_text or " ".join(cells)))
            continue

        # Remover cabecalhos duplicados em formato de texto
        if _TABLE_HEADER_NORMALIZED_RE.match(raw_line.strip()):
            continue

        verdict = _classify_text(raw_line)
        if verdict == "rule":
            add_rule(_clean_item_text(raw_line))
        else:
            add_action(_normalize_action_item(raw_line))

    for action in extra_actions:
        add_action(action)

    rendered_actions = "\n".join(
        f"- [ ] {item.removeprefix('- [ ] ').strip()}" for item in actions
    ) or EMPTY_SECTION
    return rendered_actions, extra_rules


def _split_table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None

    cells = [re.sub(r"\s+", " ", cell).strip() for cell in stripped.strip("|").split("|")]
    return cells


def _is_table_header(cells: list[str]) -> bool:
    if len(cells) < 3:
        return False
    normalized = tuple(_normalize_for_compare(cell) for cell in cells[:3])
    return normalized == _TABLE_HEADER


def _non_empty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _clean_item_text(text: str) -> str:
    cleaned = _strip_list_prefix(text)
    cleaned = _CHECKBOX_RE.sub("", cleaned)
    cleaned = cleaned.strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _normalize_action_item(text: str) -> str | None:
    cleaned = _clean_item_text(text)
    if not cleaned:
        return None
    if cleaned.lower().startswith("[ ]"):
        cleaned = cleaned[3:].strip()
    return cleaned


def _dedupe_action_items(rendered_actions: str) -> str:
    if rendered_actions == EMPTY_SECTION:
        return rendered_actions

    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in rendered_actions.splitlines():
        item = _normalize_action_item(raw_line)
        if not item:
            continue
        key = _normalize_for_compare(item)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- [ ] {item}")
    return "\n".join(lines) or EMPTY_SECTION


def _dedupe_rule_rows(rows: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        cells = _split_table_row(row)
        if cells is None or len(cells) < 3:
            continue
        key = (_normalize_for_compare(cells[1]), _normalize_for_compare(cells[2]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f"| {len(deduped) + 1} | {cells[1]} | {cells[2]} |")
    return deduped


def _classify_text(text: str) -> str | None:
    normalized = _normalize_for_compare(text)
    if not normalized:
        return None

    # Indicadores fortes de acao vindos do helper
    action_prefixes = _DATA["action_prefixes"]

    # Frases truncadas ou ambigias - nao classificar como regra
    if normalized.endswith(("...", "etc", "talvez", "acho que", "mais ou menos")):
        return None
    if len(normalized.split()) < 4:
        return None

    if normalized.startswith("[ ]") or normalized.startswith("[x]"):
        return "action"
    if any(normalized.startswith(prefix) for prefix in action_prefixes):
        return "action"

    has_rule_cue = any(cue in normalized for cue in _DATA["rule_cues"])
    has_action_cue = any(cue in normalized for cue in _DATA["action_cues"])

    # Se tem indicador de acao forte, priorizar acao
    if has_action_cue and any(
        f"{cue} " in normalized for cue in ("criar", "ajustar", "revisar", "validar", "implementar", "fazer")
    ):
        return "action"

    # Se tem rule cue mas tambem tem acao forte, verificar contexto
    if has_rule_cue and has_action_cue:
        # Verbos de acao indicam que e tarefa, nao regra
        if any(
            f"{cue} " in normalized or f"{cue} que" in normalized
            for cue in ("criar", "implementar", "fazer", "ajustar", "revisar", "validar")
        ):
            return "action"

    if has_rule_cue:
        return "rule"
    if has_action_cue:
        return "action"
    return None


def _strip_list_prefix(text: str) -> str:
    cleaned = _LIST_PREFIX_RE.sub("", text.strip(), count=1)
    cleaned = re.sub(r"^\s*\[[xX\s]\]\s*", "", cleaned)
    return cleaned.strip()
