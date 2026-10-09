"""Fail delivery checks if local input documents or credentials are included."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path, PurePosixPath


def is_local_data(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return (
        path.suffix.lower()
        in {
            ".pdf",
            ".doc",
            ".docx",
            ".odt",
            ".rtf",
            ".xls",
            ".xlsx",
            ".ods",
            ".ppt",
            ".pptx",
            ".odp",
        }
        or any(
            part.lower() in {"scratch", "examples", "experiments", "notes"} for part in path.parts
        )
        or (path.name.startswith(".env") and path.name != ".env.example")
    )


def check_repository(root: Path) -> list[str]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True)
    return [
        name for name in result.stdout.decode("utf-8").split("\0") if name and is_local_data(name)
    ]


def check_bundle(bundle: Path) -> list[str]:
    if not bundle.is_dir():
        raise FileNotFoundError(f"Bundle directory does not exist: {bundle}")
    return [
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and is_local_data(path.relative_to(bundle).as_posix())
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, help="Also check a built application directory")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    violations = [f"repository: {name}" for name in check_repository(root)]
    if args.bundle is not None:
        violations.extend(f"bundle: {name}" for name in check_bundle(args.bundle))
    if violations:
        print("Local documents/credentials must not be distributed:")
        print("\n".join(violations))
        return 1
    print("OK: no input documents, local research/notes or .env credentials in delivery inputs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
