include .env
export

IMAGE   := scribly
DB_PATH := scribly.db

# Auto-detect platform for audio device passthrough
UNAME_S := $(shell uname -s 2>/dev/null || echo Windows)
ifeq ($(UNAME_S),Linux)
  COMPOSE_OVERRIDE := -f docker-compose.linux.yml
else
  COMPOSE_OVERRIDE :=
endif

COMPOSE := docker compose -f docker-compose.yml $(COMPOSE_OVERRIDE)

.DEFAULT_GOAL := help

.PHONY: help build run process pull-model up down logs clean

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

build: ## Build image with all models baked in — required once (5-15 min, ~6GB)
	$(COMPOSE) build \
		--build-arg HF_TOKEN=$(HF_TOKEN) \
		--build-arg WHISPER_MODEL=$(WHISPER_MODEL)

run: up ## Record a new meeting — Ctrl+C stops recording and starts processing
	$(COMPOSE) run --rm scribly

process: up ## Reprocess an existing WAV  →  make process FILE=output/recording.wav
	$(COMPOSE) run --rm scribly python main.py --file /app/$(FILE)

pull-model: ## Pull Ollama LLM model (default: mistral)  →  make pull-model MODEL=llama3.2:3b
	docker compose exec scribly-ollama ollama pull $(or $(MODEL),$(OLLAMA_MODEL))

up: ## Start Ollama service in background
	docker compose up -d ollama

down: ## Stop all services
	docker compose down

logs: ## Follow container logs
	$(COMPOSE) logs -f

clean: ## Remove containers, volumes and local image
	docker compose down -v
	docker rmi $(IMAGE) 2>/dev/null || true
