# Scribly

Scribly grava reunioes, mostra a transcricao ao vivo na UI desktop, diariza speakers e extrai regras de negocio offline.

## Fluxo principal

1. A UI desktop e a visualizacao principal do projeto.
2. O usuario grava a reuniao pela UI.
3. O worker em Docker transcreve, diariza e extrai as regras.
4. Os arquivos ficam em `output/` e o banco SQLite em `data/scribly.db`.

## Estrutura

```text
scribly/
|-- application/
|-- domain/
|-- infrastructure/
|-- ui/
|-- settings.py
|-- main.py
|-- Dockerfile
`-- docker-compose.yml
```

- `settings.py`: configuracoes centralizadas do projeto, factories e `WorkerSettings`.
- `main.py`: entrypoint unico. Sem argumentos abre a UI; com `--file` reprocessa um WAV.
- `ui/`: interface desktop principal.
- `infrastructure/`: audio, Whisper, Pyannote, Ollama, SQLite e worker.

## Requisitos

- Docker Desktop
- Python 3.11+
- `make`
- token do Hugging Face para o build da imagem

## Configuracao

```bash
cp .env.example .env
```

Variaveis mais importantes:

```env
HF_TOKEN=hf_...
WHISPER_MODEL=medium
OLLAMA_MODEL=mistral
OUTPUT_DIR=output
DB_PATH=data/scribly.db
REDIS_HOST=localhost
REDIS_PORT=6379
```

## Comandos

```bash
make build
make up
make run
make process FILE=output/reuniao_20260318_143000.wav
make logs
make down
```

- `make run`: sobe os servicos necessarios e abre a UI principal.
- `make process`: reprocessa um WAV usando o mesmo pipeline do worker.

## Docker

- O unico Dockerfile do projeto agora e `Dockerfile`.
- O worker usa `settings.WorkerSettings`.
- O banco fica em `./data/scribly.db` para facilitar localizacao e inspecao.

## Observacoes

- O build baixa e deixa os modelos prontos na imagem.
- Em runtime, o projeto usa as configuracoes centralizadas em `settings.py`.
- A UI consome Redis para acompanhar progresso e transcricao ao vivo.
