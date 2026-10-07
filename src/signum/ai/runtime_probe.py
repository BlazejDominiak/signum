"""Executed by an external Python; never imports Torch into the Signum GUI."""

# ruff: noqa: PLC0415
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packages", required=True)
    parser.add_argument("--runtime", default="")
    parser.add_argument("--model", required=True)
    parser.add_argument("--kind", choices=("jev", "jevk5"), required=True)
    args = parser.parse_args()
    sys.path[:0] = [p for p in (args.runtime, args.packages) if p]
    try:
        with contextlib.redirect_stdout(sys.stderr):
            import torch  # type: ignore[import-not-found]
            import transformers  # type: ignore[import-not-found]
            from safetensors import safe_open  # type: ignore[import-not-found]
            from transformers import AutoTokenizer, Qwen3_5ForCausalLM

            if args.kind == "jevk5":
                from jevk5 import JevK5  # type: ignore[import-not-found]
                from jevk5.prompt import decision_options  # type: ignore[import-not-found]

                assert JevK5 and decision_options and Qwen3_5ForCausalLM
            else:
                import torchvision  # type: ignore[import-not-found]
                import vjev.server  # type: ignore[import-not-found]

                assert torchvision and vjev.server
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA niedostępna: sprawdź kartę NVIDIA i jej sterownik.")
            properties = torch.cuda.get_device_properties(0)
            if properties.total_memory < 15000 * 1024**2:
                raise RuntimeError("Ten pakiet wymaga karty NVIDIA z 16 GB pamięci GPU.")
            # Detect driver / architecture incompatibility, not just CUDA enumeration.
            value = torch.ones((16, 16), device="cuda")
            _ = value @ value
            torch.cuda.synchronize()
            model = Path(args.model)
            AutoTokenizer.from_pretrained(model, local_files_only=True)
            weights = list(model.glob("*.safetensors"))
            if not weights:
                raise RuntimeError("Brak plików wag modelu.")
            for weight in weights:
                with safe_open(str(weight), framework="pt") as handle:
                    if not list(handle.keys()):
                        raise RuntimeError("Pusty plik wag: " + weight.name)
            details = f"Python {sys.version.split()[0]}, Torch {torch.__version__}, "
            details += f"Transformers {transformers.__version__}, {properties.name}"
        print(json.dumps({"ok": True, "message": details}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
