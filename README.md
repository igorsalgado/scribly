# Scribly

Scribly e um assistente offline para reunioes no desktop. A interface roda na maquina do usuario, captura o audio do microfone, mostra a transcricao ao vivo e delega o processamento pesado para um worker em Docker.

O pipeline atual faz:

1. captura de audio na UI desktop
2. transcricao rapida em lotes curtos para feedback ao vivo
3. transcricao completa com timestamps
4. diarizacao de speakers com Pyannote
5. extracao de regras de negocio com Ollama
6. persistencia em Markdown e SQLite

## Como o projeto esta organizado

```text
scribly/
|-- application/        # casos de uso e pipeline
|-- domain/             # entidades, value objects e interfaces
|-- infrastructure/     # audio, Whisper, Pyannote, Ollama, SQLite e workers
|-- ui/                 # interface desktop em customtkinter
|-- settings.py         # configuracoes centralizadas e WorkerSettings do ARQ
|-- main.py             # entrypoint: UI por padrao, reprocessamento com --file
|-- scribly.pyw         # launcher opcional para abrir UI sem terminal
|-- Dockerfile          # imagem do worker
`-- docker-compose.yml  # Redis + worker + Ollama
```

## Requisitos

- Docker Desktop
- Python 3.11 ou superior
- `make`
- token do Hugging Face para o build da imagem

## Dependencias do host

A UI roda fora do container, entao as dependencias Python do host devem ser instaladas separadamente:

```bash
pip install -r requirements.host.txt
```

Observacoes:

- `requirements.host.txt` cobre a UI desktop, launcher e integracao com Redis
- `requirements.txt` fica reservado para o worker e para ambientes Python 3.11 compativeis com a stack completa de ML

## Configuracao

Copie o arquivo de exemplo:

```bash
cp .env.example .env
```

Preencha pelo menos:

```env
HF_TOKEN=hf_...
WHISPER_MODEL=medium
OLLAMA_MODEL=mistral
```

Outras variaveis uteis:

```env
OUTPUT_DIR=output
DB_PATH=data/scribly.db
REDIS_HOST=localhost
REDIS_PORT=6379
AUDIO_SAMPLE_RATE=16000
LIVE_TRANSCRIPTION_CHUNK_SECONDS=5
```

## Primeiro setup

### 1. Liberar acesso aos modelos do Pyannote

No Hugging Face:

- crie um token com permissao de leitura
- acesse: [Hugging Face](https://huggingface.co/)
- aceite os termos de uso de:
  - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
  - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)

### 2. Build da imagem do worker

Esse passo baixa Whisper e Pyannote e deixa tudo embutido na imagem:

```bash
make build
```

### 3. Subir os servicos

```bash
make up
```

Isso sobe:

- Redis
- worker ARQ
- Ollama

### 4. Baixar o modelo do Ollama

```bash
make pull-model
```

Para usar outro modelo:

```bash
make pull-model MODEL=llama3.2:3b
```

Depois disso, o fluxo normal pode rodar offline, desde que os modelos ja tenham sido baixados.

## Fluxo principal

Para abrir a interface principal:

```bash
make run
```

`make run` sobe os servicos se necessario e executa `python main.py`, que abre a UI.

### Controles da UI

- `Iniciar`: comeca uma nova gravacao
- `Ignorar`: descarta o ultimo trecho capturado
- `Mudo`: pausa a captura sem encerrar a sessao
- `Encerrar`: finaliza a gravacao e dispara o pipeline completo

### Estados visiveis na interface

- `IDLE`
- `RECORDING`
- `PROCESSING`
- `DONE`

Durante a gravacao:

- o indicador fica vermelho piscando
- o cronometro avanca em tempo real
- a transcricao ao vivo aparece na caixa de texto

Quando o processamento termina:

- o status muda para `Concluido`
- o indicador fica verde
- a reuniao pode ser reiniciada pela propria UI

## Launcher sem terminal

Em ambientes Windows, voce pode abrir `scribly.pyw` para iniciar a UI sem janela de terminal.

Esse launcher:

- executa `docker compose up -d`
- adiciona a raiz do projeto ao `sys.path`
- abre `ui.app`

Observacao: o Docker Desktop precisa estar aberto.

## Reprocessar um WAV existente

Se voce ja tiver um arquivo `.wav`, pode reprocessar sem abrir a UI:

```bash
make process FILE=output/reuniao_20260318_143000.wav
```

Ou diretamente, se o host tambem tiver a stack completa do worker instalada:

```bash
python main.py --file output/reuniao_20260318_143000.wav
```

## Saidas geradas

Arquivos produzidos em `output/`:

- `reuniao_YYYYMMDD_HHMMSS.wav`: audio completo
- `reuniao_YYYYMMDD_HHMMSS.md`: transcript diarizado + regras de negocio extraidas

Banco local:

- `data/scribly.db`

O SQLite guarda:

- reunioes
- participantes
- segmentos da transcricao
- markdown de regras de negocio

## Comandos principais

```bash
make build
make run
make up
make down
make logs
make process FILE=output/arquivo.wav
make pull-model
make clean
```

## Arquitetura resumida

### UI host

- `ui/app.py` controla estados da interface
- `infrastructure/workers/audio_worker.py` captura audio localmente
- a UI envia jobs para o worker via Redis

### Worker em Docker

- `settings.WorkerSettings` registra `transcribe_chunk` e `process_meeting`
- `WhisperTranscriber` faz transcricao rapida e completa
- `PyannoteDiarizer` identifica speakers
- `OllamaExtractor` gera o markdown final

### Persistencia

- `SQLiteMeetingRepository` grava tudo em `data/scribly.db`
- o Markdown final tambem e salvo em `output/`

## Padroes usados no codigo

- `Chain of Responsibility`: pipeline de transcricao, diarizacao e extracao
- `Strategy`: interfaces para transcricao, diarizacao e extracao
- `Repository`: persistencia desacoplada do dominio
- `Factory Method`: criacao centralizada em `settings.py`
- `Producer-Consumer`: UI captura audio e o worker consome jobs via ARQ/Redis
