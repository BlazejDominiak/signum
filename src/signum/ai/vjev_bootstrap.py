"""Samodzielny proces Python 3.11; GUI nie importuje Torch ani Transformers."""

from __future__ import annotations

import ctypes
import json
import os
import secrets
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any


def main() -> None:
    manifest_path = Path(sys.argv[1])
    port = int(sys.argv[2])
    root = manifest_path.parent
    # Frozen GUI can pass its DLL search directory to the external interpreter.
    if os.name == "nt":
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sys.path.insert(0, manifest["packages"])
    # Keep one loader per port, including simultaneous starts by GUI and CLI.
    lock = (root / f"server-{port}.lock").open("a+b")
    if os.name == "nt":
        import msvcrt  # noqa: PLC0415

        lock.seek(0)
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl  # noqa: PLC0415

        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]

    from vjev.server import (  # type: ignore[import-not-found] # noqa: PLC0415
        ModelEngine,
        make_handler,
    )

    print("Loading vjev-vision on CUDA from local weights", flush=True)
    engine = ModelEngine(
        Path(manifest["model_dir"]).as_posix(), max_tokens=4096,
        max_image_side=512, prefix_cache_mb=256, device="cuda",
    )
    token = secrets.token_urlsafe(32)
    base_handler: Any = make_handler(engine, "Signum local vjev")

    class ManagedHandler(base_handler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/signum/shutdown":
                supplied = self.headers.get("X-Signum-Control", "")
                if not secrets.compare_digest(supplied, token):
                    self._json({"detail": "forbidden"}, 403)
                    return
                self._json({"ok": True})
                self.close_connection = True
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                super().do_POST()

    server = ThreadingHTTPServer(("127.0.0.1", port), ManagedHandler)
    state_path = root / f"service-{port}.json"
    state_path.write_text(
        json.dumps({"pid": os.getpid(), "control_token": token}), encoding="utf-8",
    )
    print(f"Ready: http://127.0.0.1:{port}/v1, model={engine.model_id}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        state_path.unlink(missing_ok=True)
        lock.close()


if __name__ == "__main__":
    main()
