# Scribly

Captura áudio de reuniões, transcreve com Whisper, identifica quem falou e extrai regras de negócio — 100% offline.

## Como funciona

```
Gravação em tempo real
       ↓
Whisper (transcrição live, feedback imediato)
       ↓
Ctrl+C — encerra a reunião
       ↓
Whisper com timestamps (transcrição completa)
       ↓
Pyannote (diarização: Participante 1, Participante 2…)
       ↓
Ollama / Mistral (extração de regras de negócio)
       ↓
Markdown + SQLite
```

## Stack

| Componente | Tecnologia |
|------------|------------|
| Transcrição | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (offline) |
| Diarização de speakers | [pyannote.audio 3.x](https://github.com/pyannote/pyannote-audio) (offline) |
| Extração de regras de negócio | [Ollama](https://ollama.com) + Mistral (offline, via Docker) |
| Persistência | SQLite (stdlib) |
| CLI | [Rich](https://github.com/Textualize/rich) |

## Pré-requisitos

- Python 3.11+
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado e rodando
- Conta no [HuggingFace](https://huggingface.co) com token de acesso

## Setup

### 1. Instalar dependências

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Edite `.env` e preencha o `HF_TOKEN`:

```env
HF_TOKEN=hf_...
WHISPER_MODEL=medium
OLLAMA_MODEL=mistral
OLLAMA_URL=http://localhost:11434
```

### 3. Obter o HuggingFace Token

1. Crie uma conta em [huggingface.co](https://huggingface.co)
2. Gere um token em [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
3. Aceite os termos dos modelos de diarização:
   - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)

### 4. Subir Ollama e baixar os modelos

```bash
# Subir Ollama via Docker
docker compose up -d

# Baixar todos os modelos (Whisper + Pyannote + Ollama)
# Apenas necessário na primeira execução (~5GB total)
python download_models.py
```

**Modelos baixados:**
| Modelo | Tamanho | Descrição |
|--------|---------|-----------|
| Whisper `small` | ~500 MB | Transcrição de áudio em PT-BR |
| Pyannote diarization 3.1 | ~200 MB | Identificação de speakers |
| Mistral 7B | ~4 GB | Extração de regras de negócio |

## Uso

```bash
python main.py
```

1. Selecione o dispositivo de entrada de áudio
2. A transcrição aparece em tempo real no terminal
3. Pressione `Ctrl+C` para encerrar a reunião
4. O Scribly processa o áudio completo, identifica os speakers e extrai as regras de negócio
5. O relatório é salvo em `output/reuniao_YYYYMMDD_HHMMSS.md`

### Capturar áudio do sistema (Teams / Meet / Zoom)

No Windows, ative o **Stereo Mix**:

> Painel de Controle → Som → Gravação → clique direito → **Mostrar dispositivos desabilitados** → ativar **Stereo Mix**

Selecione esse dispositivo ao iniciar o Scribly.

### Reprocessar um áudio existente

```python
from pathlib import Path
from application.reprocess_meeting import ReprocessMeetingUseCase

use_case = ReprocessMeetingUseCase(pipeline=pipeline, repository=repository)
meeting = use_case.execute(wav_path=Path("output/reuniao_20260318_143000.wav"))
```

## Saída

Cada reunião gera um arquivo `.md` em `output/` e um registro no banco SQLite (`scribly.db`):

```markdown
# Transcript Diarizado

**Participante 1**: Precisamos definir o fluxo de aprovação...
**Participante 2**: Concordo, e também precisamos tratar o caso de rejeição...

---

# Reunião — 18/03/2026 14:30

## Participantes
- Participante 1
- Participante 2

## Resumo Executivo
...

## Regras de Negócio Identificadas
| # | Regra | Contexto |
|---|-------|---------|
| 1 | ... | ... |

## Ações / Next Steps
- [ ] ...
```

## Arquitetura

O projeto segue **DDD + Clean Architecture** com os seguintes design patterns:

| Pattern | Aplicação |
|---------|-----------|
| **Strategy** | `TranscriptionService`, `DiarizationService`, `ExtractionService` — backends intercambiáveis |
| **Chain of Responsibility** | Pipeline pós-gravação: Transcrição → Diarização → Extração |
| **Facade** | `main.py` esconde toda a complexidade de wiring |
| **Factory Method** | `build_pipeline()` instancia a cadeia com as implementações concretas |
| **Repository** | `SQLiteMeetingRepository` — persistência desacoplada do domínio |

```
scribly/
├── domain/          # Agregados, entidades, value objects, interfaces
├── application/     # Use cases, pipeline (Chain of Responsibility)
├── infrastructure/  # Whisper, Pyannote, Ollama, SQLite
├── prompts.py       # Todos os prompts centralizados
└── main.py          # CLI entry point
```

## Modelos alternativos

### Whisper
Altere `WHISPER_MODEL` no `.env`:
| Modelo | Tamanho | Velocidade |
|--------|---------|------------|
| `tiny` | 75 MB | Muito rápido |
| `base` | 150 MB | Rápido |
| `small` | 500 MB | Equilibrado |
| `medium` | 1.5 GB | Mais preciso ✓ |
| `large-v3` | 3 GB | Máxima precisão |

### Ollama
Altere `OLLAMA_MODEL` no `.env` e execute `python download_models.py` novamente:
```bash
# Exemplos
OLLAMA_MODEL=llama3.2:3b   # leve e rápido
OLLAMA_MODEL=phi4           # boa relação custo/benefício
OLLAMA_MODEL=mistral        # padrão recomendado
```

## Licença

MIT
