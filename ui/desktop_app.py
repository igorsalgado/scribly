from __future__ import annotations

import asyncio
import os
import queue
import subprocess
import threading
from concurrent.futures import Future
from contextlib import suppress
from enum import Enum, auto

import customtkinter as ctk
from arq import create_pool

from application.audio_policy import AudioTooShortError, format_duration_label
from application.business_rules_report import parse_report_sections
from application.meeting_markdown import get_meeting_markdown_path
from application.system_health import HealthReport, collect_health_report
from domain.meeting import Meeting
from infrastructure.audio.recorder import list_input_devices
from infrastructure.workers.audio_worker import AudioWorker
from settings import (
    APP_NAME,
    REDIS_PROGRESS_CHANNEL,
    REDIS_SETTINGS,
    REDIS_URL,
    create_repository,
    load_app_state,
    save_app_state,
    to_project_path,
)
from ui.tray import SystemTrayController

PROGRESS_LABELS: dict[str, str] = {
    "transcribing": "Transcrevendo...",
    "diarizing": "Identificando speakers...",
    "extracting": "Extraindo regras de negocio...",
    "done": "Concluido",
}

INDICATOR_IDLE = "#555555"
INDICATOR_RECORDING = "#ff4444"
INDICATOR_PROCESSING = "#ffaa00"
INDICATOR_DONE = "#44ff44"

MESSAGE_STYLES = {
    "error": {"fg": "#5c1f24", "label": "#f6d5d8", "button": "#8b2c34"},
    "warning": {"fg": "#5a4717", "label": "#f6e7b5", "button": "#8a6b17"},
    "info": {"fg": "#1d4257", "label": "#d5ebff", "button": "#326c8f"},
}


class AppState(Enum):
    IDLE = auto()
    RECORDING = auto()
    PROCESSING = auto()
    DONE = auto()


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class ScriblyApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title(APP_NAME)
        self.geometry("1040x720")
        self.minsize(940, 620)

        self._state = AppState.IDLE
        self._ui_queue: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self._repository = create_repository()
        self._audio_worker: AudioWorker | None = None
        self._timer_seconds = 0
        self._timer_job = None
        self._muted = False
        self._blink_on = True
        self._blink_job = None
        self._async_loop: asyncio.AbstractEventLoop | None = None
        self._async_thread: threading.Thread | None = None
        self._progress_future: Future | None = None
        self._progress_client = None
        self._progress_pubsub = None
        self._closing = False
        self._health_check_running = False
        self._pending_record_after_health = False
        self._health_report: HealthReport | None = None
        self._device_options: list[dict] = []
        self._device_lookup: dict[str, dict] = {}
        self._selected_device_name: str | None = None
        self._history_meetings: list[Meeting] = []
        self._selected_history_meeting: Meeting | None = None
        self._history_button_refs: dict[str, ctk.CTkButton] = {}
        self._tray_hidden = False
        self._tray = SystemTrayController(
            on_open=lambda: self.after(0, self._restore_from_tray),
            on_exit=lambda: self.after(0, self._quit_app),
        )
        self._app_state = load_app_state()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_async_bridge()
        self._ensure_progress_subscription()
        self._tray.start()
        self._tray.update(recording=False, hidden=False)
        self._load_audio_devices(initial=True)
        self._load_history()
        self._set_state(AppState.IDLE)
        self._refresh_health_status(show_failure=False)
        self._poll_ui_queue()

    def _build_ui(self) -> None:
        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)

        title_bar = ctk.CTkFrame(self, height=36, corner_radius=0)
        title_bar.grid(row=0, column=0, sticky="ew")
        title_bar.grid_columnconfigure(1, weight=1)

        self._indicator = ctk.CTkLabel(
            title_bar,
            text="  ",
            width=12,
            height=12,
            corner_radius=6,
            fg_color=INDICATOR_IDLE,
        )
        self._indicator.grid(row=0, column=0, padx=(10, 4), pady=10)

        self._timer_label = ctk.CTkLabel(
            title_bar,
            text="00:00:00",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._timer_label.grid(row=0, column=1, sticky="w", padx=4)

        title_text = ctk.CTkLabel(
            title_bar,
            text=APP_NAME,
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        title_text.grid(row=0, column=2, padx=8)

        self._tray_hint = ctk.CTkLabel(
            title_bar,
            text="Fechar minimiza para a bandeja",
            font=ctk.CTkFont(size=11),
            text_color="#9aa4b2",
        )
        self._tray_hint.grid(row=0, column=3, padx=(8, 12), sticky="e")

        self._setup_drag(title_bar)

        self._message_frame = ctk.CTkFrame(self, corner_radius=8, fg_color="#5c1f24")
        self._message_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(8, 0))
        self._message_frame.grid_columnconfigure(0, weight=1)
        self._message_label = ctk.CTkLabel(
            self._message_frame,
            text="",
            justify="left",
            anchor="w",
            wraplength=840,
        )
        self._message_label.grid(row=0, column=0, padx=12, pady=8, sticky="w")
        self._message_close = ctk.CTkButton(
            self._message_frame,
            text="Dispensar",
            width=96,
            command=self._clear_message,
        )
        self._message_close.grid(row=0, column=1, padx=12, pady=8)
        self._message_frame.grid_remove()

        health_bar = ctk.CTkFrame(self, corner_radius=8)
        health_bar.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 0))
        health_bar.grid_columnconfigure(0, weight=1)

        self._health_label = ctk.CTkLabel(
            health_bar,
            text="Dependencias: verificando...",
            anchor="w",
            justify="left",
        )
        self._health_label.grid(row=0, column=0, padx=12, pady=8, sticky="w")

        self._health_refresh_btn = ctk.CTkButton(
            health_bar,
            text="Atualizar",
            width=100,
            command=lambda: self._refresh_health_status(show_failure=True),
        )
        self._health_refresh_btn.grid(row=0, column=1, padx=12, pady=8)

        self._tabview = ctk.CTkTabview(self, corner_radius=10)
        self._tabview.grid(row=3, column=0, sticky="nsew", padx=12, pady=12)
        self._tabview.add("Gravacao")
        self._tabview.add("Historico")

        self._build_recording_tab()
        self._build_history_tab()

    def _build_recording_tab(self) -> None:
        recording_tab = self._tabview.tab("Gravacao")
        recording_tab.grid_rowconfigure(3, weight=1)
        recording_tab.grid_columnconfigure(0, weight=1)

        device_frame = ctk.CTkFrame(recording_tab)
        device_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 6))
        device_frame.grid_columnconfigure(1, weight=1)

        device_label = ctk.CTkLabel(
            device_frame,
            text="Dispositivo de audio",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        device_label.grid(row=0, column=0, padx=12, pady=10, sticky="w")

        self._device_combo = ctk.CTkComboBox(
            device_frame,
            values=["Carregando dispositivos..."],
            command=self._on_device_selected,
            state="readonly",
        )
        self._device_combo.grid(row=0, column=1, padx=(0, 8), pady=10, sticky="ew")
        self._device_combo.bind("<Button-1>", lambda _event: self._load_audio_devices())

        self._device_refresh_btn = ctk.CTkButton(
            device_frame,
            text="Atualizar lista",
            width=120,
            command=self._load_audio_devices,
        )
        self._device_refresh_btn.grid(row=0, column=2, padx=(0, 12), pady=10)

        controls = ctk.CTkFrame(recording_tab, corner_radius=8, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 6))
        controls.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self._btn_play = ctk.CTkButton(
            controls,
            text="Iniciar",
            width=100,
            fg_color="#1a6b1a",
            hover_color="#145014",
            command=self._on_play,
        )
        self._btn_play.grid(row=0, column=0, padx=4)

        self._btn_ignore = ctk.CTkButton(
            controls,
            text="Ignorar",
            width=90,
            state="disabled",
            command=self._on_ignore,
        )
        self._btn_ignore.grid(row=0, column=1, padx=4)

        self._btn_mute = ctk.CTkButton(
            controls,
            text="Mudo",
            width=80,
            state="disabled",
            command=self._on_mute,
        )
        self._btn_mute.grid(row=0, column=2, padx=4)

        self._btn_stop = ctk.CTkButton(
            controls,
            text="Encerrar",
            width=100,
            state="disabled",
            fg_color="#8b1a1a",
            hover_color="#6b0000",
            command=self._on_stop,
        )
        self._btn_stop.grid(row=0, column=3, padx=4)

        self._status_label = ctk.CTkLabel(
            recording_tab,
            text="Pronto para gravar",
            font=ctk.CTkFont(size=12),
            anchor="w",
        )
        self._status_label.grid(row=2, column=0, sticky="w", padx=16, pady=(0, 2))

        transcript_frame = ctk.CTkFrame(recording_tab, corner_radius=8)
        transcript_frame.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))
        transcript_frame.grid_rowconfigure(0, weight=1)
        transcript_frame.grid_columnconfigure(0, weight=1)

        self._transcript_box = ctk.CTkTextbox(
            transcript_frame,
            wrap="word",
            font=ctk.CTkFont(size=12),
            activate_scrollbars=True,
        )
        self._transcript_box.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self._transcript_box.configure(state="disabled")

    def _build_history_tab(self) -> None:
        history_tab = self._tabview.tab("Historico")
        history_tab.grid_rowconfigure(1, weight=1)
        history_tab.grid_columnconfigure(0, weight=0)
        history_tab.grid_columnconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(history_tab)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 6))
        toolbar.grid_columnconfigure(1, weight=1)

        toolbar_label = ctk.CTkLabel(
            toolbar,
            text="Buscar",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        toolbar_label.grid(row=0, column=0, padx=(12, 8), pady=10, sticky="w")

        self._history_search = ctk.CTkEntry(
            toolbar,
            placeholder_text="Filtrar por texto, participante ou resumo...",
        )
        self._history_search.grid(row=0, column=1, padx=(0, 8), pady=10, sticky="ew")
        self._history_search.bind(
            "<KeyRelease>", lambda _event: self._render_history_list()
        )

        self._history_refresh_btn = ctk.CTkButton(
            toolbar,
            text="Atualizar",
            width=90,
            command=self._load_history,
        )
        self._history_refresh_btn.grid(row=0, column=2, padx=(0, 8), pady=10)

        self._history_open_btn = ctk.CTkButton(
            toolbar,
            text="Abrir Markdown",
            width=130,
            state="disabled",
            command=self._open_selected_markdown,
        )
        self._history_open_btn.grid(row=0, column=3, padx=(0, 12), pady=10)

        self._history_list_frame = ctk.CTkScrollableFrame(history_tab, width=320)
        self._history_list_frame.grid(
            row=1, column=0, sticky="nsw", padx=(8, 6), pady=(0, 8)
        )

        detail_frame = ctk.CTkFrame(history_tab, corner_radius=8)
        detail_frame.grid(row=1, column=1, sticky="nsew", padx=(6, 8), pady=(0, 8))
        detail_frame.grid_rowconfigure(1, weight=1)
        detail_frame.grid_columnconfigure(0, weight=1)

        self._history_meta_label = ctk.CTkLabel(
            detail_frame,
            text="Selecione uma reuniao para ver os detalhes.",
            anchor="w",
            justify="left",
        )
        self._history_meta_label.grid(
            row=0, column=0, padx=12, pady=(12, 8), sticky="ew"
        )

        self._history_detail_box = ctk.CTkTextbox(
            detail_frame,
            wrap="word",
            font=ctk.CTkFont(size=12),
            activate_scrollbars=True,
        )
        self._history_detail_box.grid(
            row=1, column=0, padx=12, pady=(0, 12), sticky="nsew"
        )
        self._history_detail_box.configure(state="disabled")

    def _setup_drag(self, widget: ctk.CTkFrame) -> None:
        widget.bind("<ButtonPress-1>", self._drag_start)
        widget.bind("<B1-Motion>", self._drag_motion)

    def _drag_start(self, event) -> None:
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()

    def _drag_motion(self, event) -> None:
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.geometry(f"+{x}+{y}")

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
        self._progress_future = asyncio.run_coroutine_threadsafe(
            self._subscribe_progress(),
            self._async_loop,
        )

    async def _subscribe_progress(self) -> None:
        import redis.asyncio as aioredis

        client = None
        pubsub = None
        try:
            client = aioredis.from_url(REDIS_URL)
            pubsub = client.pubsub()
            self._progress_client = client
            self._progress_pubsub = pubsub
            await pubsub.subscribe(REDIS_PROGRESS_CHANNEL)
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                stage = message["data"]
                if isinstance(stage, bytes):
                    stage = stage.decode()
                self._ui_queue.put(("progress", stage))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if not self._closing:
                self._ui_queue.put(("error", f"Falha ao ouvir progresso: {exc}"))
        finally:
            if pubsub is not None:
                with suppress(Exception):
                    await pubsub.unsubscribe(REDIS_PROGRESS_CHANNEL)
                with suppress(Exception):
                    await pubsub.aclose()
            if client is not None:
                with suppress(Exception):
                    await client.aclose(close_connection_pool=True)
            self._progress_pubsub = None
            self._progress_client = None

    def _poll_ui_queue(self) -> None:
        try:
            while True:
                event, payload = self._ui_queue.get_nowait()
                if event == "live_text" and isinstance(payload, str):
                    self._append_transcript(payload)
                elif event == "progress" and isinstance(payload, str):
                    self._handle_progress(payload)
                elif event == "recording_started":
                    self._set_state(AppState.RECORDING)
                elif event == "error" and isinstance(payload, str):
                    self._handle_error(payload)
                elif event == "health_report" and isinstance(payload, dict):
                    self._handle_health_report(payload)
                elif event == "job_done":
                    self._handle_job_done()
        except queue.Empty:
            pass

        if not self._closing:
            self.after(50, self._poll_ui_queue)

    def _on_play(self) -> None:
        if self._state == AppState.IDLE:
            self._pending_record_after_health = True
            self._refresh_health_status(show_failure=True, before_recording=True)
            return

        if self._state == AppState.DONE:
            self._on_new_meeting()

    def _refresh_health_status(
        self,
        *,
        show_failure: bool,
        before_recording: bool = False,
    ) -> None:
        if self._health_check_running:
            return

        self._health_check_running = True
        self._health_refresh_btn.configure(state="disabled", text="Verificando")
        if before_recording:
            self._status_label.configure(text="Verificando dependencias...")

        def _run() -> None:
            report = collect_health_report()
            self._ui_queue.put(
                (
                    "health_report",
                    {
                        "report": report,
                        "show_failure": show_failure,
                        "before_recording": before_recording,
                    },
                )
            )

        threading.Thread(target=_run, daemon=True, name="health-check").start()

    def _handle_health_report(self, payload: dict) -> None:
        report = payload["report"]
        show_failure = bool(payload.get("show_failure"))
        before_recording = bool(payload.get("before_recording"))

        self._health_report = report
        self._health_check_running = False
        self._health_refresh_btn.configure(state="normal", text="Atualizar")
        self._health_label.configure(
            text=f"Dependencias: {report.summary_line()}",
            text_color="#7ce08a" if report.ok else "#f2b04d",
        )

        if report.ok and before_recording and self._pending_record_after_health:
            self._pending_record_after_health = False
            self._begin_recording()
            return

        self._pending_record_after_health = False
        if not report.ok and show_failure:
            self._show_message(
                report.failure_message() or "Dependencias indisponiveis.", kind="error"
            )

    def _begin_recording(self) -> None:
        if self._async_loop is None:
            self._show_message("Loop async indisponivel.", kind="error")
            return

        device = self._get_selected_device()
        if device is None:
            self._show_message(
                "Nenhum dispositivo de entrada disponivel. Conecte um microfone e atualize a lista.",
                kind="error",
            )
            return

        self._ensure_progress_subscription()
        self._clear_message()

        def on_live_text(text: str) -> None:
            self._ui_queue.put(("live_text", text))

        def on_audio_error(message: str) -> None:
            self._ui_queue.put(("error", message))

        self._audio_worker = AudioWorker(
            async_loop=self._async_loop,
            on_live_text=on_live_text,
            on_error=on_audio_error,
        )
        self._audio_worker.start(device=device["index"])
        self._ui_queue.put(("recording_started", None))

    def _on_stop(self) -> None:
        if self._state != AppState.RECORDING or self._audio_worker is None:
            return

        self._set_state(AppState.PROCESSING)
        self._status_label.configure(text="Finalizando gravacao...")
        worker = self._audio_worker

        def _finalize() -> None:
            try:
                wav_path, duration = worker.stop()
                if self._async_loop is None:
                    raise RuntimeError(
                        "Loop async indisponivel para enfileirar o processamento."
                    )
                asyncio.run_coroutine_threadsafe(
                    self._enqueue_process(wav_path, duration),
                    self._async_loop,
                )
            except Exception as exc:
                self._ui_queue.put(("error", self._format_exception_message(exc)))
            finally:
                self._audio_worker = None

        threading.Thread(target=_finalize, daemon=True, name="finalize").start()

    async def _enqueue_process(self, wav_path: str, duration: float) -> None:
        try:
            pool = await create_pool(REDIS_SETTINGS)
            try:
                job = await pool.enqueue_job(
                    "process_meeting",
                    to_project_path(wav_path),
                    duration,
                )
                if job is None:
                    raise RuntimeError("Worker indisponivel para processar a reuniao.")
                await job.result(timeout=3600)
                self._ui_queue.put(("job_done", None))
            finally:
                await pool.aclose()
        except Exception as exc:
            self._ui_queue.put(("error", self._format_exception_message(exc)))

    def _on_ignore(self) -> None:
        if self._audio_worker and self._state == AppState.RECORDING:
            self._audio_worker.ignore_last_chunk()
            self._show_message("Ultimo trecho de audio descartado.", kind="info")

    def _on_mute(self) -> None:
        if self._audio_worker and self._state == AppState.RECORDING:
            self._muted = not self._muted
            self._audio_worker.set_muted(self._muted)
            self._btn_mute.configure(text="Mudo" if self._muted else "Ativo")
            self._show_message(
                "Captura pausada temporariamente."
                if self._muted
                else "Captura de audio retomada.",
                kind="info",
            )

    def _on_new_meeting(self) -> None:
        self._transcript_box.configure(state="normal")
        self._transcript_box.delete("1.0", "end")
        self._transcript_box.configure(state="disabled")
        self._timer_seconds = 0
        self._muted = False
        self._audio_worker = None
        self._clear_message()
        self._set_state(AppState.IDLE)

    def _set_state(self, state: AppState) -> None:
        self._state = state

        if self._blink_job is not None:
            self.after_cancel(self._blink_job)
            self._blink_job = None
        if self._timer_job is not None:
            self.after_cancel(self._timer_job)
            self._timer_job = None

        is_recording = state == AppState.RECORDING
        allow_device_choice = state in {AppState.IDLE, AppState.DONE}

        self._device_combo.configure(
            state="readonly"
            if allow_device_choice and self._device_lookup
            else "disabled"
        )
        self._device_refresh_btn.configure(
            state="normal" if allow_device_choice else "disabled"
        )

        if state == AppState.IDLE:
            self._btn_play.configure(text="Iniciar", state="normal")
            self._btn_ignore.configure(state="disabled")
            self._btn_mute.configure(state="disabled", text="Mudo")
            self._btn_stop.configure(state="disabled")
            self._status_label.configure(text="Pronto para gravar")
            self._indicator.configure(fg_color=INDICATOR_IDLE)
            self._timer_label.configure(text="00:00:00")
        elif state == AppState.RECORDING:
            self._btn_play.configure(text="Gravando...", state="disabled")
            self._btn_ignore.configure(state="normal")
            self._btn_mute.configure(
                state="normal", text="Ativo" if not self._muted else "Mudo"
            )
            self._btn_stop.configure(state="normal")
            self._status_label.configure(text="Gravando...")
            self._timer_seconds = 0
            self._start_timer()
            self._blink_indicator()
        elif state == AppState.PROCESSING:
            self._btn_play.configure(state="disabled")
            self._btn_ignore.configure(state="disabled")
            self._btn_mute.configure(state="disabled")
            self._btn_stop.configure(state="disabled")
            self._status_label.configure(text="Processando...")
            self._indicator.configure(fg_color=INDICATOR_PROCESSING)
        elif state == AppState.DONE:
            self._btn_play.configure(text="Nova reuniao", state="normal")
            self._btn_ignore.configure(state="disabled")
            self._btn_mute.configure(state="disabled", text="Mudo")
            self._btn_stop.configure(state="disabled")
            self._status_label.configure(text="Concluido")
            self._indicator.configure(fg_color=INDICATOR_DONE)

        self._tray.update(recording=is_recording, hidden=self._tray_hidden)

    def _start_timer(self) -> None:
        self._timer_seconds = 0
        self._tick_timer()

    def _tick_timer(self) -> None:
        self._timer_label.configure(text=format_duration_label(self._timer_seconds))
        self._timer_seconds += 1
        self._timer_job = self.after(1000, self._tick_timer)

    def _blink_indicator(self) -> None:
        if self._state != AppState.RECORDING:
            return

        color = INDICATOR_RECORDING if self._blink_on else INDICATOR_IDLE
        self._indicator.configure(fg_color=color)
        self._blink_on = not self._blink_on
        self._blink_job = self.after(600, self._blink_indicator)

    def _handle_progress(self, stage: str) -> None:
        self._status_label.configure(text=PROGRESS_LABELS.get(stage, stage))
        if stage == "done":
            self._load_history()
            self._set_state(AppState.DONE)
            self._show_message("Processamento concluido com sucesso.", kind="info")

    def _handle_job_done(self) -> None:
        if self._state == AppState.PROCESSING:
            self._load_history()
            self._set_state(AppState.DONE)

    def _handle_error(self, message: str) -> None:
        if self._state == AppState.RECORDING and self._audio_worker is not None:
            with suppress(Exception):
                self._audio_worker.abort()
            self._audio_worker = None

        if self._state in {AppState.RECORDING, AppState.PROCESSING}:
            self._set_state(AppState.IDLE)

        self._status_label.configure(text="Erro")
        self._show_message(message, kind="error")

    def _append_transcript(self, text: str) -> None:
        self._transcript_box.configure(state="normal")
        if self._transcript_box.get("1.0", "end").strip():
            self._transcript_box.insert("end", " " + text)
        else:
            self._transcript_box.insert("end", text)
        self._transcript_box.see("end")
        self._transcript_box.configure(state="disabled")

    def _show_message(self, text: str, *, kind: str) -> None:
        styles = MESSAGE_STYLES[kind]
        self._message_frame.configure(fg_color=styles["fg"])
        self._message_label.configure(text=text, text_color=styles["label"])
        self._message_close.configure(
            fg_color=styles["button"],
            hover_color=styles["button"],
            text_color=styles["label"],
        )
        self._message_frame.grid()

    def _clear_message(self) -> None:
        self._message_frame.grid_remove()
        self._message_label.configure(text="")

    def _load_audio_devices(self, initial: bool = False) -> None:
        try:
            devices = list_input_devices()
        except Exception as exc:
            self._device_options = []
            self._device_lookup = {}
            self._device_combo.configure(
                values=["Falha ao carregar dispositivos"], state="disabled"
            )
            self._show_message(
                f"Falha ao listar dispositivos de audio: {exc}", kind="error"
            )
            return

        self._device_options = devices
        self._device_lookup = {
            self._device_display_label(device): device for device in devices
        }

        if not self._device_lookup:
            self._device_combo.configure(
                values=["Nenhum dispositivo encontrado"], state="disabled"
            )
            self._selected_device_name = None
            self._show_message(
                "Nenhum microfone de entrada encontrado. Conecte um dispositivo e atualize a lista.",
                kind="warning",
            )
            return

        display_values = list(self._device_lookup.keys())
        self._device_combo.configure(values=display_values)

        saved_device_name = self._app_state.get("selected_input_device_name")
        matched_label = None
        if self._selected_device_name is not None:
            matched_label = self._find_device_label(self._selected_device_name)
        elif saved_device_name:
            matched_label = self._find_device_label(saved_device_name)

        if matched_label is None:
            matched_label = display_values[0]
            self._selected_device_name = self._device_lookup[matched_label]["name"]
            self._persist_app_state()
            if saved_device_name and initial:
                self._show_message(
                    "O dispositivo salvo nao esta mais disponivel. O app voltou para o microfone padrao listado.",
                    kind="warning",
                )

        self._device_combo.set(matched_label)
        if self._state in {AppState.IDLE, AppState.DONE}:
            self._device_combo.configure(state="readonly")

    def _device_display_label(self, device: dict) -> str:
        return f"{device['name']} ({device['channels']} canais)"

    def _find_device_label(self, device_name: str) -> str | None:
        for label, device in self._device_lookup.items():
            if device["name"] == device_name:
                return label
        return None

    def _on_device_selected(self, display_label: str) -> None:
        device = self._device_lookup.get(display_label)
        if device is None:
            return
        self._selected_device_name = device["name"]
        self._persist_app_state()

    def _get_selected_device(self) -> dict | None:
        if not self._device_lookup:
            return None

        current_label = self._device_combo.get()
        device = self._device_lookup.get(current_label)
        if device is not None:
            return device

        if self._selected_device_name is not None:
            matched = self._find_device_label(self._selected_device_name)
            if matched is not None:
                self._device_combo.set(matched)
                return self._device_lookup[matched]

        return next(iter(self._device_lookup.values()), None)

    def _persist_app_state(self) -> None:
        self._app_state["selected_input_device_name"] = self._selected_device_name
        save_app_state(self._app_state)

    def _load_history(self) -> None:
        self._history_meetings = self._repository.find_all()
        if self._selected_history_meeting is not None:
            selected_id = self._selected_history_meeting.id
            self._selected_history_meeting = next(
                (
                    meeting
                    for meeting in self._history_meetings
                    if meeting.id == selected_id
                ),
                None,
            )
        self._render_history_list()

    def _render_history_list(self) -> None:
        for child in self._history_list_frame.winfo_children():
            child.destroy()
        self._history_button_refs = {}

        query = self._history_search.get().strip().lower()
        visible_meetings = [
            meeting
            for meeting in self._history_meetings
            if self._history_matches_query(meeting, query)
        ]

        if not visible_meetings:
            empty_label = ctk.CTkLabel(
                self._history_list_frame,
                text="Nenhuma reuniao encontrada.",
                justify="left",
                anchor="w",
            )
            empty_label.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
            self._selected_history_meeting = None
            self._history_open_btn.configure(state="disabled")
            self._history_meta_label.configure(text="Nenhuma reuniao selecionada.")
            self._set_history_details("")
            return

        for row_index, meeting in enumerate(visible_meetings):
            title, preview = self._meeting_history_title(meeting)
            button = ctk.CTkButton(
                self._history_list_frame,
                text=(
                    f"{meeting.date.strftime('%d/%m/%Y %H:%M')}\n"
                    f"{format_duration_label(meeting.duration_seconds)}\n"
                    f"{title}\n{preview}"
                ),
                anchor="w",
                justify="left",
                height=94,
                command=lambda item=meeting: self._select_history_meeting(item),
            )
            button.grid(row=row_index, column=0, sticky="ew", padx=8, pady=6)
            self._history_button_refs[str(meeting.id)] = button

        if (
            self._selected_history_meeting is None
            or self._selected_history_meeting not in visible_meetings
        ):
            self._select_history_meeting(visible_meetings[0])
        else:
            self._select_history_meeting(self._selected_history_meeting)

    def _select_history_meeting(self, meeting: Meeting) -> None:
        self._selected_history_meeting = meeting
        markdown_path = get_meeting_markdown_path(meeting)
        title, preview = self._meeting_history_title(meeting)
        participants = (
            ", ".join(participant.label for participant in meeting.participants)
            or "Nao identificado"
        )

        self._history_meta_label.configure(
            text=(
                f"{meeting.date.strftime('%d/%m/%Y %H:%M')} | "
                f"Duracao {format_duration_label(meeting.duration_seconds)}\n"
                f"Participantes: {participants}\n"
                f"Titulo: {title}\n"
                f"Preview: {preview}"
            )
        )

        self._set_history_details(self._build_history_details(meeting))
        self._history_open_btn.configure(
            state="normal" if markdown_path.exists() else "disabled"
        )

        for button_id, button in self._history_button_refs.items():
            button.configure(
                fg_color="#1f6aa5"
                if button_id == str(meeting.id)
                else ("#3B8ED0", "#1F6AA5")
            )

    def _build_history_details(self, meeting: Meeting) -> str:
        transcript = (
            meeting.transcript.diarized_text
            if meeting.transcript
            else "(nao identificado)"
        )
        report = (
            meeting.business_rules.raw_markdown
            if meeting.business_rules
            else "# Relatorio da Reuniao\n\n(nao identificado)"
        )
        return f"# Transcript Diarizado\n\n{transcript}\n\n---\n\n{report}"

    def _set_history_details(self, text: str) -> None:
        self._history_detail_box.configure(state="normal")
        self._history_detail_box.delete("1.0", "end")
        if text:
            self._history_detail_box.insert("1.0", text)
        self._history_detail_box.configure(state="disabled")

    def _meeting_history_title(self, meeting: Meeting) -> tuple[str, str]:
        summary = "(nao identificado)"
        if meeting.business_rules:
            summary = (
                parse_report_sections(meeting.business_rules.raw_markdown).get(
                    "summary"
                )
                or summary
            )

        transcript_snippet = ""
        if meeting.transcript:
            transcript_snippet = meeting.transcript.diarized_text.replace(
                "\n", " "
            ).strip()

        title = (
            summary
            if summary != "(nao identificado)"
            else transcript_snippet or "Reuniao sem resumo"
        )
        preview = transcript_snippet or summary
        return self._truncate_text(title, 90), self._truncate_text(preview, 120)

    def _history_matches_query(self, meeting: Meeting, query: str) -> bool:
        if not query:
            return True

        fields = [
            meeting.date.strftime("%d/%m/%Y %H:%M"),
            " ".join(participant.label for participant in meeting.participants),
        ]
        if meeting.transcript:
            fields.append(meeting.transcript.diarized_text)
        if meeting.business_rules:
            fields.append(meeting.business_rules.raw_markdown)

        return query in " ".join(fields).lower()

    def _open_selected_markdown(self) -> None:
        if self._selected_history_meeting is None:
            return

        markdown_path = get_meeting_markdown_path(self._selected_history_meeting)
        if not markdown_path.exists():
            self._show_message(
                f"O arquivo Markdown nao foi encontrado em {markdown_path}.",
                kind="warning",
            )
            self._history_open_btn.configure(state="disabled")
            return

        try:
            if hasattr(os, "startfile"):
                os.startfile(str(markdown_path))
            else:
                subprocess.Popen(["xdg-open", str(markdown_path)])
        except Exception as exc:
            self._show_message(f"Falha ao abrir o Markdown: {exc}", kind="error")

    def _truncate_text(self, value: str, size: int) -> str:
        compact = " ".join(value.split())
        if len(compact) <= size:
            return compact
        return compact[: size - 1].rstrip() + "..."

    def _format_exception_message(self, exc: Exception) -> str:
        if isinstance(exc, AudioTooShortError):
            return exc.user_message

        message = str(exc).strip() or exc.__class__.__name__
        lowered = message.lower()
        if "worker indisponivel" in lowered or "arq" in lowered:
            return (
                f"{message} Execute `docker compose up -d worker redis` "
                "ou suba o ambiente completo antes de tentar novamente."
            )
        if "connection" in lowered or "redis" in lowered:
            return (
                f"{message} Verifique se Redis e worker estao ativos com "
                "`docker compose up -d`."
            )
        if "ollama" in lowered or "model" in lowered:
            return (
                f"{message} Verifique o servico Ollama e baixe o modelo com "
                "`make pull-model`."
            )
        return message

    def _on_close(self) -> None:
        if not self._closing and self._tray.available:
            self._minimize_to_tray()
            return
        self._quit_app()

    def _minimize_to_tray(self) -> None:
        self._tray_hidden = True
        self.withdraw()
        self._tray.update(recording=self._state == AppState.RECORDING, hidden=True)

    def _restore_from_tray(self) -> None:
        self._tray_hidden = False
        self.deiconify()
        self.lift()
        self.focus_force()
        self._tray.update(recording=self._state == AppState.RECORDING, hidden=False)

    def _quit_app(self) -> None:
        if self._closing:
            return

        self._closing = True
        self._pending_record_after_health = False

        if self._audio_worker is not None:
            with suppress(Exception):
                self._audio_worker.abort()
            self._audio_worker = None

        if self._timer_job is not None:
            self.after_cancel(self._timer_job)
            self._timer_job = None
        if self._blink_job is not None:
            self.after_cancel(self._blink_job)
            self._blink_job = None

        self._tray.stop()

        if self._async_loop is not None and self._async_loop.is_running():
            shutdown_future = asyncio.run_coroutine_threadsafe(
                self._shutdown_progress_subscription(),
                self._async_loop,
            )
            with suppress(Exception):
                shutdown_future.result(timeout=2)

        if self._progress_future is not None:
            with suppress(Exception):
                self._progress_future.cancel()
                self._progress_future.result(timeout=2)
            self._progress_future = None

        if self._async_loop is not None and self._async_loop.is_running():
            self._async_loop.call_soon_threadsafe(self._async_loop.stop)
        if self._async_thread is not None and self._async_thread.is_alive():
            self._async_thread.join(timeout=2)
        if self._async_loop is not None and not self._async_loop.is_closed():
            self._async_loop.close()
            self._async_loop = None

        self.destroy()

    async def _shutdown_progress_subscription(self) -> None:
        if self._progress_pubsub is not None:
            with suppress(Exception):
                await self._progress_pubsub.unsubscribe(REDIS_PROGRESS_CHANNEL)
            with suppress(Exception):
                await self._progress_pubsub.aclose()
        if self._progress_client is not None:
            with suppress(Exception):
                await self._progress_client.aclose(close_connection_pool=True)


def main() -> None:
    app = ScriblyApp()
    app.mainloop()


if __name__ == "__main__":
    main()
