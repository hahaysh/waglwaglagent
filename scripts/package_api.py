"""Package an API release with Linux dependencies and the pinned Copilot runtime."""

import argparse
import zipfile
from pathlib import Path


def package_api(source: Path, dependencies: Path, runtime: Path, output: Path):
    for required in (
        source / "app" / "main.py", source / "migrations" / "env.py",
        source / "alembic.ini", source / "start_api.py",
        dependencies / "uvicorn" / "__init__.py",
        runtime / "prebuilds" / "linux-x64" / "copilot",
        runtime / "prebuilds" / "linux-x64" / "runtime.node",
    ):
        if not required.is_file():
            raise ValueError(f"Missing API release file: {required.name}")
    if output.exists():
        raise ValueError("Output archive already exists")
    files = []
    for directory, prefix in (
        (source / "app", Path("app")), (source / "migrations", Path("migrations")),
        (dependencies, Path(".python_packages/lib/site-packages")),
        (runtime, Path("copilot-runtime")),
    ):
        for path in directory.rglob("*"):
            relative = path.relative_to(directory)
            if path.name.startswith(".env") or any(
                part in {".git", ".local", ".azure"} for part in relative.parts
            ):
                raise ValueError("API release contains private configuration")
            if "__pycache__" not in relative.parts and path.is_file():
                files.append((path, (prefix / relative).as_posix()))
    files.extend((source / name, name) for name in ("start_api.py", "alembic.ini"))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, name in files:
            archive.write(path, name)
    print("API archive verified: source, Linux dependencies and pinned runtime; no environment files.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependencies", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package_api(
        Path(__file__).resolve().parents[1] / "services" / "api",
        args.dependencies, args.runtime, args.output,
    )
