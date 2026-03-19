EXTRACTION_SYSTEM_PROMPT: str = """\
You are a senior business analyst specialized in product requirements.
Your job is to read meeting transcripts and produce structured business rules.
Always respond in Portuguese (PT-BR). Be concise and actionable.
Use only information explicitly present in the transcript — do not invent details."""

EXTRACTION_USER_TEMPLATE: str = """\
Analise o transcript abaixo e preencha cada seção do template a seguir.
Retorne SOMENTE o template preenchido, sem texto adicional.

--- TRANSCRIPT ---
{transcript}
--- FIM DO TRANSCRIPT ---

--- TEMPLATE ---
## Resumo Executivo
(2-3 frases resumindo o objetivo e resultado da reunião)

## Decisões Tomadas
- (liste cada decisão com um bullet)

## Regras de Negócio Identificadas
| # | Regra | Contexto |
|---|-------|---------|
| 1 | (regra clara e objetiva) | (trecho ou contexto que originou a regra) |

## Ações / Next Steps
- [ ] [responsável] descrição da ação

## Dúvidas em Aberto
- (questões que ficaram sem resposta)
"""

BUSINESS_RULES_OUTPUT_TEMPLATE: str = """\
# Reunião — {date}

## Participantes
{participants}

## Resumo Executivo
{summary}

## Decisões Tomadas
{decisions}

## Regras de Negócio Identificadas
| # | Regra | Contexto |
|---|-------|---------|
{rules_table}

## Ações / Next Steps
{actions}

## Dúvidas em Aberto
{open_questions}
"""
