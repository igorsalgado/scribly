import asyncio
import os
import queue
import threading
from enum import Enum, auto
from pathlib import Path

import customtkinter as ctk
from arq import create_pool
from arq.connections import RedisSettings
from dotenv import load_dotenv

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}"

PROGRESS_LABELS: dict[str, str] = {
    "transcribing": "Transcrevendo...",
    "diarizing": "Identificando speakers...",
    "extracting": "Extraindo regras de negócio...",
    "done": "Concluído ✓",
}

INDICATOR_IDLE = "#555555"
INDICATOR_RECORDING = "#ff4444"
INDICATOR_PROCESSING = "#ffaa00"
INDICATOR_DONE = "#44ff44"


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

        self.title("Scribly")
        self.geometry("440x340")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        self._state = AppState.IDLE
        self._ui_queue: queue.Queue = queue.Queue()
        self._audio_worker = None
        self._timer_seconds = 0
        self._timer_job = None
        self._muted = False
        self._blink_on = True
        self._blink_job = None
        self._async_loop: asyncio.AbstractEventLoop | None = None
        self._process_job = None

        self._build_ui()
        self._start_async_bridge()
        self._poll_ui_queue()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_rowconfigure(0, weight=0)  # title bar
        self.grid_rowconfigure(1, weight=0)  # controls
        self.grid_rowconfigure(2, weight=0)  # status
        self.grid_rowconfigure(3, weight=1)  # transcript
        self.grid_columnconfigure(0, weight=1)

        # Title bar
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
            title_bar, text="00:00:00", font=ctk.CTkFont(size=13, weight="bold")
        )
        self._timer_label.grid(row=0, column=1, sticky="w", padx=4)

        title_text = ctk.CTkLabel(
            title_bar, text="Scribly", font=ctk.CTkFont(size=14, weight="bold")
        )
        title_text.grid(row=0, column=2, padx=8)

        self._setup_drag(title_bar)

        # Controls
        controls = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=12, pady=(10, 4))
        controls.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self._btn_play = ctk.CTkButton(
            controls,
            text="Iniciar",
            width=90,
            fg_color="#1a6b1a",
            hover_color="#145014",
            command=self._on_play,
        )
        self._btn_play.grid(row=0, column=0, padx=4)

        self._btn_ignore = ctk.CTkButton(
            controls,
            text="Ignorar",
            width=80,
            state="disabled",
            command=self._on_ignore,
        )
        self._btn_ignore.grid(row=0, column=1, padx=4)

        self._btn_mute = ctk.CTkButton(
            controls,
            text="Mudo",
            width=60,
            state="disabled",
            command=self._on_mute,
        )
        self._btn_mute.grid(row=0, column=2, padx=4)

        self._btn_stop = ctk.CTkButton(
            controls,
            text="Encerrar",
            width=90,
            state="disabled",
            fg_color="#8b1a1a",
            hover_color="#6b0000",
            command=self._on_stop,
        )
        self._btn_stop.grid(row=0, column=3, padx=4)

        # Status
        self._status_label = ctk.CTkLabel(
            self,
            text="Pronto para gravar",
            font=ctk.CTkFont(size=12),
            anchor="w",
        )
        self._status_label.grid(row=2, column=0, sticky="w", padx=16, pady=(4, 2))

        # Transcript scroll
        transcript_frame = ctk.CTkFrame(self, corner_radius=6)
        transcript_frame.grid(
            row=3, column=0, sticky="nsew", padx=12, pady=(2, 12)
        )
        transcript_frame.grid_rowconfigure(0, weight=1)
        transcript_frame.grid_columnconfigure(0, weight=1)

        self._transcript_box = ctk.CTkTextbox(
            transcript_frame,
            wrap="word",
            font=ctk.CTkFont(size=12),
            activate_scrollbars=True,
        )
        self._transcript_box.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self._transcript_box.configure(state="disabled")

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

    # ------------------------------------------------------------------
    # Async bridge
    # ------------------------------------------------------------------

    def _start_async_bridge(self) -> None:
        self._async_loop = asyncio.new_event_loop()
        t = threading.Thread(
            target=self._async_loop.run_forever, daemon=True, name="async-bridge"
        )
        t.start()
        asyncio.run_coroutine_threadsafe(
            self._subscribe_progress(), self._async_loop
        )

    async def _subscribe_progress(self) -> None:
        import redis.asyncio as aioredis

        try:
            client = aioredis.from_url(REDIS_URL)
            pubsub = client.pubsub()
            await pubsub.subscribe("scribly:progress")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    stage = message["data"]
                    if isinstance(stage, bytes):
                        stage = stage.decode()
                    self._ui_queue.put(("progress", stage))
        except Exception:
            pass

    def _poll_ui_queue(self) -> None:
        try:
            while True:
                event, payload = self._ui_queue.get_nowait()
                if event == "live_text":
                    self._append_transcript(payload)
                elif event == "progress":
                    self._handle_progress(payload)
                elif event == "recording_started":
                    self._set_state(AppState.RECORDING)
                elif event == "processing_started":
                    self._set_state(AppState.PROCESSING)
                elif event == "error":
                    self._status_label.configure(text=f"Erro: {payload}")
        except queue.Empty:
            pass
        self.after(50, self._poll_ui_queue)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_play(self) -> None:
        if self._state == AppState.IDLE:
            self._start_recording()
        elif self._state == AppState.DONE:
            self._on_new_meeting()

    def _start_recording(self) -> None:
        from infrastructure.workers.audio_worker import AudioWorker

        def on_live_text(text: str) -> None:
            self._ui_queue.put(("live_text", text))

        self._audio_worker = AudioWorker(
            redis_url=REDIS_URL,
            async_loop=self._async_loop,
            on_live_text=on_live_text,
        )
        self._audio_worker.start(device=None)
        self._ui_queue.put(("recording_started", None))

    def _on_stop(self) -> None:
        if self._state != AppState.RECORDING:
            return

        self._set_state(AppState.PROCESSING)
        self._status_label.configure(text="Finalizando gravação...")

        def _finalize() -> None:
            try:
                wav_path, duration = self._audio_worker.stop()
                asyncio.run_coroutine_threadsafe(
                    self._enqueue_process(wav_path, duration), self._async_loop
                )
            except Exception as exc:
                self._ui_queue.put(("error", str(exc)))

        threading.Thread(target=_finalize, daemon=True, name="finalize").start()

    async def _enqueue_process(self, wav_path: str, duration: float) -> None:
        try:
            rs = RedisSettings(host=REDIS_HOST, port=REDIS_PORT)
            pool = await create_pool(rs)
            await pool.enqueue_job("process_meeting", wav_path, duration)
            await pool.aclose()
        except Exception as exc:
            self._ui_queue.put(("error", str(exc)))

    def _on_ignore(self) -> None:
        if self._audio_worker and self._state == AppState.RECORDING:
            self._audio_worker.ignore_last_chunk()

    def _on_mute(self) -> None:
        if self._audio_worker and self._state == AppState.RECORDING:
            self._muted = not self._muted
            self._audio_worker.set_muted(self._muted)
            self._btn_mute.configure(text="🔇 Mudo" if self._muted else "🎤 Ativo")

    def _on_new_meeting(self) -> None:
        self._transcript_box.configure(state="normal")
        self._transcript_box.delete("1.0", "end")
        self._transcript_box.configure(state="disabled")
        self._timer_seconds = 0
        self._muted = False
        self._audio_worker = None
        self._set_state(AppState.IDLE)

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def _set_state(self, state: AppState) -> None:
        self._state = state

        if self._blink_job is not None:
            self.after_cancel(self._blink_job)
            self._blink_job = None
        if self._timer_job is not None:
            self.after_cancel(self._timer_job)
            self._timer_job = None

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
            self._btn_mute.configure(state="normal")
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
            self._btn_play.configure(text="Nova reunião", state="normal")
            self._btn_ignore.configure(state="disabled")
            self._btn_mute.configure(state="disabled")
            self._btn_stop.configure(state="disabled")
            self._status_label.configure(text="Concluído ✓")
            self._indicator.configure(fg_color=INDICATOR_DONE)

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------

    def _start_timer(self) -> None:
        self._timer_seconds = 0
        self._tick_timer()

    def _tick_timer(self) -> None:
        h = self._timer_seconds // 3600
        m = (self._timer_seconds % 3600) // 60
        s = self._timer_seconds % 60
        self._timer_label.configure(text=f"{h:02d}:{m:02d}:{s:02d}")
        self._timer_seconds += 1
        self._timer_job = self.after(1000, self._tick_timer)

    # ------------------------------------------------------------------
    # Indicator blink
    # ------------------------------------------------------------------

    def _blink_indicator(self) -> None:
        if self._state != AppState.RECORDING:
            return
        color = INDICATOR_RECORDING if self._blink_on else INDICATOR_IDLE
        self._indicator.configure(fg_color=color)
        self._blink_on = not self._blink_on
        self._blink_job = self.after(600, self._blink_indicator)

    # ------------------------------------------------------------------
    # Progress updates from worker
    # ------------------------------------------------------------------

    def _handle_progress(self, stage: str) -> None:
        label = PROGRESS_LABELS.get(stage, stage)
        self._status_label.configure(text=label)
        if stage == "done":
            self._set_state(AppState.DONE)

    # ------------------------------------------------------------------
    # Transcript
    # ------------------------------------------------------------------

    def _append_transcript(self, text: str) -> None:
        self._transcript_box.configure(state="normal")
        if self._transcript_box.get("1.0", "end").strip():
            self._transcript_box.insert("end", " " + text)
        else:
            self._transcript_box.insert("end", text)
        self._transcript_box.see("end")
        self._transcript_box.configure(state="disabled")


def main() -> None:
    app = ScriblyApp()
    app.mainloop()


if __name__ == "__main__":
    main()
