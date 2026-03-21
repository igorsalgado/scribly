from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass

import redis
from arq import create_pool

from settings import OLLAMA_MODEL, OLLAMA_URL, REDIS_SETTINGS, REDIS_URL

try:
    import httpx
except ImportError:  # pragma: no cover - depende do ambiente do host
    httpx = None


@dataclass(slots=True)
class HealthCheckResult:
    name: str
    ok: bool
    detail: str
    action: str

    @property
    def badge(self) -> str:
        return f"{self.name}: {'ok' if self.ok else 'erro'}"


@dataclass(slots=True)
class HealthReport:
    checks: list[HealthCheckResult]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def summary_line(self) -> str:
        return " | ".join(check.badge for check in self.checks)

    def first_failure(self) -> HealthCheckResult | None:
        for check in self.checks:
            if not check.ok:
                return check
        return None

    def failure_message(self) -> str | None:
        failure = self.first_failure()
        if failure is None:
            return None
        return f"{failure.detail} {failure.action}".strip()


def collect_health_report() -> HealthReport:
    return HealthReport(
        checks=[
            _check_docker(),
            _check_redis(),
            _check_worker(),
            _check_ollama(),
        ]
    )


def _check_docker() -> HealthCheckResult:
    try:
        completed = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        return HealthCheckResult(
            name="Docker",
            ok=False,
            detail="Docker CLI nao encontrada.",
            action="Instale o Docker Desktop e reinicie a aplicacao.",
        )
    except subprocess.TimeoutExpired:
        return HealthCheckResult(
            name="Docker",
            ok=False,
            detail="Docker nao respondeu ao health check.",
            action="Abra o Docker Desktop e aguarde o daemon iniciar.",
        )

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        return HealthCheckResult(
            name="Docker",
            ok=False,
            detail="Docker daemon indisponivel."
            if not stderr
            else f"Docker daemon indisponivel: {stderr}",
            action="Abra o Docker Desktop e tente novamente.",
        )

    return HealthCheckResult(
        name="Docker",
        ok=True,
        detail="Docker daemon acessivel.",
        action="",
    )


def _check_redis() -> HealthCheckResult:
    client = redis.Redis.from_url(REDIS_URL)
    try:
        client.ping()
    except Exception as exc:
        return HealthCheckResult(
            name="Redis",
            ok=False,
            detail=f"Redis indisponivel em {REDIS_URL}: {exc}",
            action="Execute `docker compose up -d redis` ou suba o ambiente completo.",
        )
    finally:
        client.close()

    return HealthCheckResult(
        name="Redis",
        ok=True,
        detail="Redis respondeu ao ping.",
        action="",
    )


def _check_worker() -> HealthCheckResult:
    try:
        worker_ok = asyncio.run(_run_worker_healthcheck())
    except Exception as exc:
        return HealthCheckResult(
            name="Worker",
            ok=False,
            detail=f"Worker ARQ indisponivel: {exc}",
            action="Execute `docker compose up -d worker` ou suba o ambiente completo.",
        )

    if not worker_ok:
        return HealthCheckResult(
            name="Worker",
            ok=False,
            detail="Worker ARQ nao confirmou o health check.",
            action="Verifique os logs do worker e reinicie o servico.",
        )

    return HealthCheckResult(
        name="Worker",
        ok=True,
        detail="Worker ARQ respondeu ao health check.",
        action="",
    )


async def _run_worker_healthcheck() -> bool:
    pool = await create_pool(REDIS_SETTINGS)
    try:
        job = await pool.enqueue_job("healthcheck")
        if job is None:
            return False
        result = await job.result(timeout=10)
        return result == "ok"
    finally:
        await pool.aclose()


def _check_ollama() -> HealthCheckResult:
    if httpx is None:
        return HealthCheckResult(
            name="Ollama",
            ok=False,
            detail="Dependencia `httpx` nao instalada no ambiente do host.",
            action="Atualize o host com `pip install -r requirements.host.txt`.",
        )

    try:
        response = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=8.0)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return HealthCheckResult(
            name="Ollama",
            ok=False,
            detail=f"Ollama indisponivel em {OLLAMA_URL}: {exc}",
            action="Suba o servico Ollama e confirme que a porta esta acessivel.",
        )

    models = payload.get("models", [])
    requested = _normalize_model_name(OLLAMA_MODEL)
    installed = {
        _normalize_model_name(model.get("name", ""))
        for model in models
        if model.get("name")
    }

    if requested not in installed:
        return HealthCheckResult(
            name="Ollama",
            ok=False,
            detail=f"Modelo `{OLLAMA_MODEL}` nao encontrado no Ollama.",
            action=f"Execute `make pull-model MODEL={OLLAMA_MODEL}` e tente novamente.",
        )

    return HealthCheckResult(
        name="Ollama",
        ok=True,
        detail=f"Modelo `{OLLAMA_MODEL}` disponivel.",
        action="",
    )


def _normalize_model_name(model_name: str) -> str:
    return model_name.strip().lower().split(":")[0]
