EXTRACTION_SYSTEM_PROMPT: str = """\
You are a senior business analyst specialized in product requirements.
Your job is to read meeting transcripts and produce structured business rules.
Always respond in Portuguese (PT-BR). Be concise and actionable.
Use only information explicitly present in the transcript - do not invent details."""

EXTRACTION_USER_TEMPLATE: str = """\
Analise o transcript abaixo e preencha cada secao do template a seguir.
Retorne SOMENTE o template preenchido, sem texto adicional.

--- TRANSCRIPT ---
{transcript}
--- FIM DO TRANSCRIPT ---

--- TEMPLATE ---
## Resumo Executivo
(2-3 frases resumindo o objetivo e resultado da reuniao)

## Decisoes Tomadas
- (liste cada decisao com um bullet)

## Regras de Negocio Identificadas
| # | Regra | Contexto |
|---|-------|---------|
| 1 | (regra clara e objetiva) | (trecho ou contexto que originou a regra) |

## Acoes / Next Steps
- [ ] [responsavel] descricao da acao

## Duvidas em Aberto
- (questoes que ficaram sem resposta)
"""

BUSINESS_RULES_OUTPUT_TEMPLATE: str = """\
# Reuniao - {date}

## Participantes
{participants}

## Resumo Executivo
{summary}

## Decisoes Tomadas
{decisions}

## Regras de Negocio Identificadas
| # | Regra | Contexto |
|---|-------|---------|
{rules_table}

## Acoes / Next Steps
{actions}

## Duvidas em Aberto
{open_questions}
"""
