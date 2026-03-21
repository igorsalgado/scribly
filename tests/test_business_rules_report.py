from __future__ import annotations

import unittest

from application.business_rules_report import build_business_rules_markdown


class BusinessRulesReportTests(unittest.TestCase):
    def test_removes_duplicate_table_header(self) -> None:
        extracted = """\
## Resumo Executivo
Reuniao curta sobre ajustes no fluxo.

## Decisoes Tomadas
- Seguir com a mudanca.

## Regras de Negocio Identificadas
| # | Regra | Contexto |
|---|-------|---------|
| # | Regra | Contexto |
|---|-------|---------|
| 1 | O cliente pode cancelar pedidos em ate 7 dias. | Politica do produto |

## Acoes / Next Steps
- [ ] [UX] revisar o prototipo.

## Duvidas em Aberto
- Nenhuma.
"""

        report = build_business_rules_markdown(
            extracted,
            date="2026-03-21",
            participants=["Ana", "Bruno"],
        )

        self.assertEqual(report.count("| # | Regra | Contexto |"), 1)
        self.assertIn(
            "| 1 | O cliente pode cancelar pedidos em ate 7 dias. | Politica do produto |",
            report,
        )

    def test_separates_actions_from_rules(self) -> None:
        extracted = """\
## Resumo Executivo
Resumo suportado.

## Regras de Negocio Identificadas
| # | Regra | Contexto |
|---|-------|---------|
| 1 | O sistema deve bloquear acesso apos 3 tentativas. | Regra de seguranca |
| 2 | Criar um prototipo para validar o fluxo com UX. | Proximo passo |

## Acoes / Next Steps
- [ ] [Produto] validar a proposta com o time.
"""

        report = build_business_rules_markdown(
            extracted,
            date="2026-03-21",
            participants=[],
        )

        self.assertIn(
            "| 1 | O sistema deve bloquear acesso apos 3 tentativas. | Regra de seguranca |",
            report,
        )
        self.assertNotIn(
            "| 2 | Criar um prototipo para validar o fluxo com UX. | Proximo passo |",
            report,
        )
        self.assertIn("- [ ] Criar um prototipo para validar o fluxo com UX.", report)
        self.assertIn("- [ ] [Produto] validar a proposta com o time.", report)

    def test_moves_rule_like_content_out_of_actions(self) -> None:
        extracted = """\
## Resumo Executivo
Resumo suportado.

## Regras de Negocio Identificadas
| # | Regra | Contexto |
|---|-------|---------|
| 1 | O sistema deve registrar auditoria. | Regra principal |

## Acoes / Next Steps
- [ ] O sistema deve registrar auditoria apenas para administradores.
- [ ] [Backend] revisar o fluxo de log.
"""

        report = build_business_rules_markdown(
            extracted,
            date="2026-03-21",
            participants=["Ana"],
        )

        self.assertIn(
            "| 1 | O sistema deve registrar auditoria. | Regra principal |", report
        )
        self.assertIn("- [ ] [Backend] revisar o fluxo de log.", report)
        self.assertNotIn(
            "O sistema deve registrar auditoria apenas para administradores.",
            report.split("## Acoes / Next Steps", 1)[1],
        )
        self.assertIn(
            "| 2 | O sistema deve registrar auditoria apenas para administradores. | (nao identificado) |",
            report,
        )

    def test_keeps_noisy_or_missing_sections_conservative(self) -> None:
        extracted = """\
Texto solto antes das secoes.

## Regras de Negocio Identificadas
| # | Regra | Contexto |
|---|-------|---------|
| 1 | Ajustar o material com o time. | Observacao vaga |

## Acoes / Next Steps
"""

        report = build_business_rules_markdown(
            extracted,
            date="2026-03-21",
            participants=["Ana"],
        )

        self.assertIn("## Decisoes Tomadas\n(nao identificado)", report)
        self.assertIn("## Duvidas em Aberto\n(nao identificado)", report)
        self.assertIn("- [ ] Ajustar o material com o time.", report)
        self.assertIn(
            "## Regras de Negocio Identificadas\n| # | Regra | Contexto |\n|---|-------|---------|\n(nao identificado)",
            report,
        )
        self.assertNotIn("Observacao vaga", report)

    def test_treats_tem_que_criar_as_action(self) -> None:
        extracted = """\
## Resumo Executivo
Resumo curto.

## Regras de Negocio Identificadas
| # | Regra | Contexto |
|---|-------|---------|
| 1 | Tem que criar um prompt especifico para o arquivo markdown. | Encaminhamento da reuniao |

## Acoes / Next Steps
(nao identificado)
"""

        report = build_business_rules_markdown(
            extracted,
            date="2026-03-21",
            participants=["Ana"],
        )

        self.assertIn(
            "- [ ] Tem que criar um prompt especifico para o arquivo markdown.", report
        )
        self.assertIn(
            "## Regras de Negocio Identificadas\n| # | Regra | Contexto |\n|---|-------|---------|\n(nao identificado)",
            report,
        )


if __name__ == "__main__":
    unittest.main()
