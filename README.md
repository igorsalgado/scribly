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

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado e rodando
- `make` instalado (`choco install make` no Windows, nativo no Linux/Mac)
- Conta no [HuggingFace](https://huggingface.co) com token de acesso

## Setup

### 1. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Edite `.env`:

```env
HF_TOKEN=hf_...
WHISPER_MODEL=medium
OLLAMA_MODEL=mistral
```

### 2. Obter o HuggingFace Token

1. Crie uma conta em [huggingface.co](https://huggingface.co)
2. Gere um token em [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
3. Aceite os termos:
   - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)

### 3. Build da imagem

```bash
make build
```

Todos os modelos são baixados e embutidos na imagem durante o build (~5-15 min, imagem final ~6GB). Após isso, **zero dependências externas** — tudo roda offline dentro do container.

**Modelos embutidos na imagem:**
| Modelo | Tamanho | Função |
|--------|---------|--------|
| Whisper `medium` | ~1.5 GB | Transcrição de áudio em PT-BR |
| Pyannote diarization 3.1 | ~200 MB | Identificação de speakers |
| Mistral 7B (Ollama) | ~4 GB | Extração de regras de negócio |

### 4. Pull do modelo Ollama

```bash
make pull-model
```

## Uso

```bash
make run      # grava nova reunião
```

1. Selecione o dispositivo de entrada de áudio
2. Transcrição aparece em tempo real no terminal
3. `Ctrl+C` encerra a reunião e dispara o processamento completo
4. Relatório salvo em `output/reuniao_YYYYMMDD_HHMMSS.md`

### Reprocessar um áudio existente

```bash
make process FILE=output/reuniao_20260318_143000.wav
```

### Todos os comandos

```bash
make help
```

```
  build           Build image with all models baked in — required once (5-15 min, ~6GB)
  run             Record a new meeting — Ctrl+C stops recording and starts processing
  process         Reprocess an existing WAV  →  make process FILE=output/recording.wav
  pull-model      Pull Ollama LLM model (default: mistral)  →  make pull-model MODEL=llama3.2:3b
  up              Start Ollama service in background
  down            Stop all services
  logs            Follow container logs
  clean           Remove containers, volumes and local image
```

## Áudio em Docker — por plataforma

| Plataforma | Suporte | Como habilitar |
|---|---|---|
| **Linux** | ✅ Nativo | Automático via Makefile (`/dev/snd` passthrough) |
| **Windows 11 WSL2** | ✅ Nativo | Execute os comandos `make` dentro do terminal WSL2 |
| **Windows nativo** | ⚠️ Via PulseAudio | Instale PulseAudio, adicione `PULSE_SERVER=tcp:host.docker.internal:4713` no `.env` |
| **Mac** | ⚠️ Via PulseAudio | Instale BlackHole + PulseAudio, adicione `PULSE_SERVER=...` no `.env` |

### Capturar áudio do sistema no Windows (Teams / Meet / Zoom)

Ative o **Stereo Mix** antes de iniciar:

> Painel de Controle → Som → Gravação → clique direito → **Mostrar dispositivos desabilitados** → ativar **Stereo Mix**

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
