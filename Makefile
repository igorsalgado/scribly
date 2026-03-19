include .env
export

IMAGE_WORKER := scribly-worker
DB_PATH := data/scribly.db

ifeq ($(OS),Windows_NT)
  COMPOSE_OVERRIDE :=
else
  UNAME_S := $(shell uname -s)
  ifeq ($(UNAME_S),Linux)
    COMPOSE_OVERRIDE := -f docker-compose.linux.yml
  else
    COMPOSE_OVERRIDE :=
  endif
endif

COMPOSE := docker compose -f docker-compose.yml $(COMPOSE_OVERRIDE)

.DEFAULT_GOAL := help

.PHONY: help build ui run up down logs process pull-model clean

help: ## Show available commands
	@python -c "import re; from pathlib import Path; text = Path('Makefile').read_text(encoding='utf-8'); pattern = re.compile(r'^([a-zA-Z_-]+):.*?## (.*)$$', re.MULTILINE); [print(f'  {name:<16} {desc}') for name, desc in pattern.findall(text)]"

build: ## Build the worker image with baked models
	$(COMPOSE) build \
		--build-arg HF_TOKEN=$(HF_TOKEN) \
		--build-arg WHISPER_MODEL=$(WHISPER_MODEL)

ui: up ## Launch the desktop UI
	python main.py

run: ui ## Alias for the main UI flow

up: ## Start Redis, worker and Ollama in background
	$(COMPOSE) up -d

process: up ## Reprocess an existing WAV file
	$(COMPOSE) run --rm scribly-worker python main.py --file /app/$(FILE)

pull-model: up ## Pull the configured Ollama model
	$(COMPOSE) exec ollama ollama pull $(or $(MODEL),$(OLLAMA_MODEL))

down: ## Stop all services
	$(COMPOSE) down

logs: ## Follow container logs
	$(COMPOSE) logs -f

clean: ## Remove containers, volumes and the local image
	$(COMPOSE) down -v
	docker rmi $(IMAGE_WORKER) 2>/dev/null || true
