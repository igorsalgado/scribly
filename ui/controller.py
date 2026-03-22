from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from typing import Any, Callable

from application.audio_policy import AudioTooShortError
from application.scribly_service import ScriblyApplicationService
from application.system_health import HealthReport
from settings import load_app_state, save_app_state
from ui.constants import AppState


class ScriblyController:
    def __init__(self, event_callback: Callable[[str, Any], None]) -> None:
        self._event_callback = event_callback
        self._async_loop: asyncio.AbstractEventLoop | None = None
        self._async_thread: threading.Thread | None = None
        self._progress_future: Future | None = None

        self._start_async_bridge()

        self._service = ScriblyApplicationService(self._async_loop)

        self._closing = False
        self._health_check_running = False
        self._pending_record_after_health = False
        self._health_report: HealthReport | None = None
        self._app_state = load_app_state()
        self._selected_device_name = self._app_state.get("selected_input_device_name")
        self._state = AppState.IDLE
        self._muted = False

        self._ensure_progress_subscription()

    def _start_async_bridge(self) -> None:
        self._async_loop = asyncio.new_event_loop()
        self._async_thread = threading.Thread(
            target=self._async_loop.run_forever,
            daemon=True,
            name="async-bridge",
        )
        self._async_thread.start()

    def _ensure_progress_subscription(self) -> None:
        if self._async_loop is None:
            return
        if self._progress_future is not None and not self._progress_future.done():
            return

        def _callback(stage: str) -> None:
            self._event_callback("progress", stage)

        self._progress_future = asyncio.run_coroutine_threadsafe(
            self._service.subscribe_progress(_callback),
            self._async_loop,
        )

    def refresh_health(
        self, show_failure: bool, before_recording: bool = False
    ) -> None:
        if self._health_check_running:
            return
        self._health_check_running = True
        self._event_callback("health_checking", (show_failure, before_recording))

        def _run() -> None:
            report = self._service.collect_health()
            self._event_callback(
                "health_report",
                {
                    "report": report,
                    "show_failure": show_failure,
                    "before_recording": before_recording,
                },
            )

        threading.Thread(target=_run, daemon=True, name="health-check").start()

    def handle_health_report(self, payload: dict) -> None:
        report = payload["report"]
        before_recording = bool(payload.get("before_recording"))
        self._health_report = report
        self._health_check_running = False

        if report.ok and before_recording and self._pending_record_after_health:
            self._pending_record_after_health = False
            self.begin_recording()
            return

        self._pending_record_after_health = False

    def start_recording_flow(self) -> None:
        if self._state == AppState.IDLE:
            self._pending_record_after_health = True
            self.refresh_health(show_failure=True, before_recording=True)
        elif self._state == AppState.DONE:
            self.new_meeting()

    def begin_recording(self) -> None:
        if self._async_loop is None:
            self._event_callback("error", "Loop async indisponivel.")
            return

        device = self._get_selected_device_info()
        if device is None:
            self._event_callback("error", "Nenhum dispositivo de entrada disponivel.")
            return

        self._ensure_progress_subscription()

        def on_live_text(text: str) -> None:
            self._event_callback("live_text", text)

        def on_audio_error(message: str) -> None:
            self._event_callback("error", message)

        self._service.start_recording(
            device_index=device["index"],
            on_live_text=on_live_text,
            on_error=on_audio_error,
        )
        self._set_state(AppState.RECORDING)
        self._event_callback("recording_started", None)

    def stop_recording(self) -> None:
        if self._state != AppState.RECORDING:
            return

        self._set_state(AppState.PROCESSING)

        try:
            future = self._service.stop_recording()

            def _on_done(f: Future[tuple[str, float]]) -> None:
                try:
                    wav_path, duration = f.result()
                    if self._async_loop is None:
                        raise RuntimeError("Loop async indisponivel.")

                    asyncio.run_coroutine_threadsafe(
                        self._enqueue_process(wav_path, duration),
                        self._async_loop,
                    )
                except Exception as exc:
                    self._event_callback("error", self._format_exception_message(exc))

            future.add_done_callback(_on_done)
        except Exception as exc:
            self._event_callback("error", self._format_exception_message(exc))

    async def _enqueue_process(self, wav_path: str, duration: float) -> None:
        try:
            await self._service.enqueue_processing(wav_path, duration)
            self._event_callback("job_done", None)
        except Exception as exc:
            self._event_callback("error", self._format_exception_message(exc))

    def ignore_last_chunk(self) -> None:
        if self._state == AppState.RECORDING:
            self._service.ignore_last_chunk()
            self._event_callback(
                "message", ("Ultimo trecho de audio descartado.", "info")
            )

    def toggle_mute(self) -> bool:
        if self._state == AppState.RECORDING:
            self._muted = not self._muted
            self._service.set_muted(self._muted)
            msg = (
                "Captura pausada temporariamente."
                if self._muted
                else "Captura de audio retomada."
            )
            self._event_callback("message", (msg, "info"))
            return self._muted
        return False

    def new_meeting(self) -> None:
        self._muted = False
        self._set_state(AppState.IDLE)
        self._event_callback("new_meeting", None)

    def _set_state(self, state: AppState) -> None:
        self._state = state
        self._event_callback("state_changed", state)

    def get_history(self) -> list[Any]:
        return self._service.get_history()

    def open_markdown(self, meeting: Any) -> None:
        if not self._service.open_meeting_markdown(meeting):
            self._event_callback(
                "message", ("Arquivo Markdown nao encontrado.", "warning")
            )

    def list_devices(self) -> list[dict]:
        return self._service.list_devices()

    def _get_selected_device_info(self) -> dict | None:
        devices = self.list_devices()
        if not devices:
            return None
        if self._selected_device_name:
            for d in devices:
                if d["name"] == self._selected_device_name:
                    return d
        return devices[0]

    def set_selected_device(self, device_name: str) -> None:
        self._selected_device_name = device_name
        self._app_state["selected_input_device_name"] = device_name
        save_app_state(self._app_state)

    def get_selected_device_name(self) -> str | None:
        return self._selected_device_name

    def _format_exception_message(self, exc: Exception) -> str:
        if isinstance(exc, AudioTooShortError):
            return exc.user_message
        message = str(exc).strip() or exc.__class__.__name__
        lowered = message.lower()
        if "worker indisponivel" in lowered or "arq" in lowered:
            return f"{message}. Verifique o worker Docker."
        if "connection" in lowered or "redis" in lowered:
            return f"{message}. Verifique o Redis Docker."
        return message

    def shutdown(self) -> None:
        self._closing = True
        self._pending_record_after_health = False
        self._service.shutdown()

        if self._progress_future is not None:
            self._progress_future.cancel()

        if self._async_loop is not None and self._async_loop.is_running():
            self._async_loop.call_soon_threadsafe(self._async_loop.stop)
        if self._async_thread is not None and self._async_thread.is_alive():
            self._async_thread.join(timeout=2)
        if self._async_loop is not None and not self._async_loop.is_closed():
            self._async_loop.close()
