import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

subprocess.Popen(
    ["docker", "compose", "up", "-d"],
    cwd=ROOT,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

sys.path.insert(0, str(ROOT))

from ui.app import main

main()
