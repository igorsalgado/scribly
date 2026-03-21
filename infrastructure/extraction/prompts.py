EXTRACTION_SYSTEM_PROMPT: str = """\
You are a senior business analyst specialized in product requirements.
Your job is to read meeting transcripts and produce structured business rules.
Always respond in Portuguese (PT-BR). Be concise and actionable.
Use only information explicitly present in the transcript - do not invent details.
If the transcript is noisy, incomplete, or contradictory, prefer omitting content rather than inferring it.
Keep business rules separate from actions: rules describe stable conditions, constraints, and policies; actions describe next steps, tasks, owners, and follow-ups.
Be conservative: if content is ambiguous, truncated, or unclear, do not promote it to a formal rule."""

EXTRACTION_USER_TEMPLATE: str = """\
Analise o transcript abaixo e preencha cada secao do template a seguir.
Retorne SOMENTE o template preenchido, sem texto adicional.
NUNCA repita o cabecalho da tabela | # | Regra | Contexto | dentro da secao de regras.
Se uma informacao nao estiver explicitamente suportada pelo transcript, escreva exatamente "(nao identificado)".

--- TRANSCRIPT ---
{transcript}
--- FIM DO TRANSCRIPT ---

--- TEMPLATE ---
## Resumo Executivo
(2-3 frases resumindo o objetivo e resultado da reuniao. Nao invente detalhes.)

## Decisoes Tomadas
- (liste cada decisao com um bullet. Nao repita decisoes como se fossem tarefas.)

## Regras de Negocio Identificadas
| # | Regra | Contexto |
|---|-------|---------|
| 1 | (regra clara e objetiva) | (trecho ou contexto que originou a regra) |

IMPORTANTE: Esta secao e APENAS para regras estaveis, restricoes ou politicas.
- Nao inclua tarefas com verbos como "criar", "implementar", "fazer", "validar", "ajustar".
- Nao inclua proximos passos, prazos, responsaveis ou encaminhamentos.
- Nao repita o cabecalho | # | Regra | Contexto | nas linhas seguintes.
- Se o transcript contiver apenas acoes, deixe a tabela vazia ou com "(nao identificado)".

## Acoes / Next Steps
- [ ] [responsavel] descricao da acao

Use esta secao APENAS para tarefas, proximos passos e follow-ups.
- Itens com "tem que", "precisa criar", "vamos fazer", "deve implementar" sao ACOES, nao regras.
- Nao inclua regras de negocio nesta secao.

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
