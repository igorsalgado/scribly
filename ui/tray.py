from __future__ import annotations

import threading
from typing import Callable

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - depende do ambiente desktop
    pystray = None
    Image = None
    ImageDraw = None


class SystemTrayController:
    def __init__(
        self,
        on_open: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self._on_open = on_open
        self._on_exit = on_exit
        self._icon = None
        self._thread: threading.Thread | None = None
        self._recording = False
        self._hidden = False

    @property
    def available(self) -> bool:
        return pystray is not None and Image is not None and ImageDraw is not None

    def start(self) -> None:
        if not self.available or self._icon is not None:
            return

        self._icon = pystray.Icon(
            "scribly",
            icon=_build_icon(recording=False),
            title=self._build_title(),
            menu=pystray.Menu(
                pystray.MenuItem(
                    "Abrir",
                    self._handle_open,
                    default=True,
                ),
                pystray.MenuItem(
                    "Encerrar",
                    self._handle_exit,
                ),
            ),
        )

        self._thread = threading.Thread(
            target=self._icon.run,
            daemon=True,
            name="scribly-tray",
        )
        self._thread.start()

    def stop(self) -> None:
        if self._icon is None:
            return
        self._icon.stop()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None
        self._icon = None

    def update(self, *, recording: bool, hidden: bool) -> None:
        self._recording = recording
        self._hidden = hidden
        if self._icon is None:
            return

        self._icon.icon = _build_icon(recording=recording)
        self._icon.title = self._build_title()
        self._icon.visible = True
        self._icon.update_menu()

    def _build_title(self) -> str:
        status = "Gravando..." if self._recording else "Pronto"
        visibility = "Oculto na bandeja" if self._hidden else "Aberto"
        return f"Scribly - {status} - {visibility}"

    def _handle_open(self, icon, item) -> None:  # pragma: no cover - callback de UI
        self._on_open()

    def _handle_exit(self, icon, item) -> None:  # pragma: no cover - callback de UI
        self._on_exit()


def _build_icon(recording: bool):
    image = Image.new("RGBA", (64, 64), (20, 24, 31, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((6, 6, 58, 58), radius=14, fill=(28, 37, 48, 255))
    draw.ellipse(
        (18, 18, 46, 46),
        fill=(220, 60, 60, 255) if recording else (72, 176, 110, 255),
    )
    draw.rounded_rectangle((24, 10, 40, 14), radius=4, fill=(235, 238, 242, 255))
    return image
