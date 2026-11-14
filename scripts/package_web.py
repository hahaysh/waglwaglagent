"""Package a Next.js standalone build without configuration or development files."""

import argparse
import zipfile
from pathlib import Path


def package_web(root: Path, output: Path):
    standalone = root / "apps" / "web" / ".next" / "standalone"
    static = root / "apps" / "web" / ".next" / "static"
    public = root / "apps" / "web" / "public"
    for required in (standalone / "server.js", standalone / "package.json", static, public):
        if not required.exists():
            raise ValueError(f"Missing build output: {required.name}; run npm run build first")
    if output.exists():
        raise ValueError("Output archive already exists; choose a fresh output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, prefix in (
            (standalone, Path()), (static, Path(".next") / "static"), (public, Path("public")),
        ):
            for path in sorted(source.rglob("*")):
                relative = path.relative_to(source)
                if path.name.startswith(".env") or any(
                    part in {".git", ".local", ".azure", ".copilot-azure"}
                    for part in relative.parts
                ):
                    raise ValueError("Build output contains private configuration; refusing to package")
                if path.is_file():
                    archive.write(path, (prefix / relative).as_posix())
        archive.writestr(
            "release.json",
            '{"format":"next-standalone-v1","startup":"node server.js"}\n',
        )
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        if "server.js" not in names or not any(name.startswith(".next/static/") for name in names):
            raise ValueError("Standalone archive failed verification")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package_web(Path(__file__).resolve().parents[1], args.output)
    print("Standalone archive verified; no environment files included.")
