# Scribly

Assistente de reuniões offline para desktop. Grava o áudio, exibe transcrição ao vivo, identifica speakers automaticamente e extrai regras de negócio — tudo sem enviar dados para nenhuma API externa.

> TODO: screenshot da janela principal

---

## Requisitos

| Requisito | Versão mínima |
|---|---|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | 24+ |
| [Python](https://www.python.org/downloads/) | 3.11+ |
| [Make](https://gnuwin32.sourceforge.net/packages/make.htm) (Windows) | qualquer |
| Conta no [Hugging Face](https://huggingface.co) | — |

> O build da imagem Docker baixa os modelos Whisper e Pyannote e os deixa embutidos (~6 GB). Após o build, o projeto funciona completamente offline.

---

## Configuração

### 1. Obter token do Hugging Face

1. Acesse [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) e crie um token com permissão de leitura.
2. Aceite os termos de uso dos modelos:
   - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)

### 2. Criar o `.env`

```bash
cp .env.example .env
```

Preencha o `.env` com suas configurações:

```env
# Obrigatório — necessário apenas no build da imagem
HF_TOKEN=hf_...

# Modelo Whisper: tiny | base | small | medium | large-v3
WHISPER_MODEL=medium

# Modelo Ollama para extração de regras de negócio
OLLAMA_MODEL=mistral
```

As demais variáveis já têm valores padrão e não precisam ser alteradas.

---

## Instalação

### 1. Instalar dependências Python

```bash
pip install -r requirements.txt
```

### 2. Build da imagem Docker

> Necessário apenas uma vez. Demora entre 5 e 15 minutos dependendo da conexão.

```bash
make build
```

Este comando baixa e embute os modelos Whisper e Pyannote na imagem. Após isso, o projeto não precisa mais de internet.

### 3. Baixar o modelo LLM no Ollama

```bash
make pull-model
```

Para usar um modelo diferente do padrão:

```bash
make pull-model MODEL=llama3.2:3b
```

> TODO: screenshot do terminal durante o build

---

## Utilização

### Iniciar

```bash
make run
```

Sobe os serviços Docker (Redis, Worker, Ollama) e abre a interface desktop.

> TODO: screenshot da interface com estados IDLE / RECORDING / PROCESSING / DONE

### Atalho no Desktop (opcional)

Dê duplo clique em `scribly.pyw` ou crie um atalho para ele no Desktop. Ao abrir, os containers Docker são iniciados automaticamente se não estiverem rodando.

> Requer que o **Docker Desktop esteja aberto** antes de clicar no atalho.

### Fluxo de uso

1. Clique em **Iniciar** para começar a gravar a reunião
2. A transcrição ao vivo aparece na caixa de texto conforme você fala
3. Use **Mudo** para pausar a captura do microfone sem interromper a gravação
4. Use **Ignorar** para descartar o último trecho gravado
5. Clique em **Encerrar** para finalizar — o pipeline completo é disparado automaticamente
6. Quando o indicador ficar verde e o status mostrar **Concluído**, a reunião foi processada

> TODO: gif demonstrando o fluxo completo de gravação

### Reprocessar um arquivo WAV existente

```bash
make process FILE=output/reuniao_20260318_143000.wav
```

---

## Resultados

Após o processamento, dois arquivos são gerados em `output/`:

- `reuniao_YYYYMMDD_HHmmss.wav` — áudio completo da reunião
- `reuniao_YYYYMMDD_HHmmss.md` — transcrição diarizada + regras de negócio extraídas

O banco SQLite em `data/scribly.db` armazena todos os dados estruturados para consulta posterior.

> TODO: exemplo de arquivo .md gerado

---

## Comandos disponíveis

```bash
make build                              # Build da imagem com modelos embutidos
make run                                # Sobe serviços + abre a UI
make up                                 # Sobe apenas os serviços Docker
make down                               # Para todos os serviços
make logs                               # Acompanha logs dos containers
make process FILE=output/arquivo.wav    # Reprocessa um WAV existente
make pull-model MODEL=mistral           # Baixa modelo Ollama
make clean                              # Remove containers, volumes e imagem
```

---

## Arquitetura

```text
scribly/
├── domain/             # Agregados, Value Objects e interfaces (DDD)
├── application/        # Casos de uso e pipeline Chain of Responsibility
├── infrastructure/     # Whisper, Pyannote, Ollama, SQLite, workers de áudio
├── ui/                 # Interface desktop customtkinter
├── settings.py         # Configurações centralizadas, factories e WorkerSettings ARQ
├── main.py             # Entrypoint: sem args → UI | --file WAV → reprocessa
├── scribly.pyw         # Atalho desktop (inicia Docker + abre UI sem terminal)
├── Dockerfile          # Imagem do worker com modelos embutidos
└── docker-compose.yml  # Redis + Worker + Ollama
```

**Design patterns utilizados:**
- **Chain of Responsibility** — pipeline de processamento (Transcrição → Diarização → Extração)
- **Strategy** — interfaces `TranscriptionService`, `DiarizationService`, `ExtractionService`
- **Repository** — `SQLiteMeetingRepository`
- **Factory Method** — `create_pipeline()` em `settings.py`
- **Producer-Consumer** — `AudioWorker` (Thread) → fila ARQ/Redis → worker Docker
