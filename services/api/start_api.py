"""Start the Linux App Service release after applying database migrations."""

import os
import site
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    os.chdir(root)
    packages = root / ".python_packages" / "lib" / "site-packages"
    if not packages.is_dir():
        raise RuntimeError("Missing packaged Python dependencies")
    site.addsitedir(str(packages))
    os.environ["PYTHONPATH"] = str(packages)
    os.environ["COPILOT_CLI_EXTRACT_DIR"] = str(root / "copilot-runtime")
    os.environ["COPILOT_SKIP_CLI_DOWNLOAD"] = "true"
    from copilot._cli_download import get_cached_cli_path

    binary = get_cached_cli_path()
    if not binary:
        raise RuntimeError("Missing pinned Copilot runtime in the release")
    for name in ("copilot", "copilot-runtime"):
        path = Path(binary).with_name(name)
        path.chmod(path.stat().st_mode | 0o111)
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"], check=True,
    )
    os.execv(sys.executable, [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", "0.0.0.0", "--port", "8000", "--workers", "1",
    ])


if __name__ == "__main__":
    main()
