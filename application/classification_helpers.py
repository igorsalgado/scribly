from __future__ import annotations

# Aliases para mapeamento de seções do Markdown gerado pelo LLM
SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "summary": ("resumo executivo", "summary", "executive summary"),
    "decisions": ("decisoes tomadas", "decisions", "decisões"),
    "rules": ("regras de negocio identificadas", "business rules", "regras de negócio"),
    "actions": ("acoes / next steps", "actions", "ações", "próximos passos", "proximos passos"),
    "open_questions": ("duvidas em aberto", "open questions", "dúvidas"),
}

# Verbos de ação comuns (Pistas de tarefas)
ACTION_CUES_PT = (
    "criar", "implementar", "revisar", "validar", "ajustar", "enviar", "definir",
    "documentar", "executar", "agendar", "fazer", "preparar", "corrigir",
    "refatorar", "testar", "alinhar", "alinhamento", "levantar", "mapear",
    "atualizar", "aprovar", "publicar", "entregar", "priorizar", "acompanhar",
    "subir", "desenvolver", "trazer", "rodar",
)

# Pistas de regras de negócio (Pistas normativas)
RULE_CUES_PT = (
    "deve", "nao pode", "não pode", "precisa", "somente", "apenas", "sempre",
    "quando", "caso", "regra", "limite", "proibido", "permitido", "obrigatorio",
    "obrigatório", "tem que", "deve ser", "pode ser",
)

# Prefixos fortes de ação (Frases que indicam encaminhamento)
ACTION_PREFIXES_PT = (
    "tem que ", "precisa ", "precisa de ", "vamos ", "deve criar ",
    "deve ajustar ", "deve revisar ", "deve validar ", "deve implementar ",
    "deve fazer ", "deve documentar ", "deve testar ", "deve subir ",
    "deve descer ", "deve rodar ", "deve agendar ", "deve alinhar ",
)

# Mapeamento por idioma (Preparado para i18n)
CLASSIFICATION_REGISTRY = {
    "pt-br": {
        "action_cues": ACTION_CUES_PT,
        "rule_cues": RULE_CUES_PT,
        "action_prefixes": ACTION_PREFIXES_PT,
    },
    # Futuro: "en": { ... }
}

def get_classification_data(lang: str = "pt-br") -> dict:
    return CLASSIFICATION_REGISTRY.get(lang.lower(), CLASSIFICATION_REGISTRY["pt-br"])
