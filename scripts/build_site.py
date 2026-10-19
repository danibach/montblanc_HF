"""Assemble the static website: the in-browser track check, ready for GitHub Pages.

    python scripts/build_site.py --out _site

The folder gets the page (site/), the web app's stylesheet, the analysis package (src/mbhf, without
the Flask app), the pure-Python wheels it needs, and Pyodide (Python compiled for the browser).
Pyodide and the wheels are downloaded with npm and pip, so the network must reach their registries.
Pass --pyodide-dir to reuse an already extracted Pyodide package instead.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYODIDE_VERSION = "314.0.7"
PYODIDE_FILES = ("pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json")
WHEELS = ("defusedxml==0.7.1", "fitdecode==0.11.0", "tzdata")
SKIP_IN_ENGINE = ("web",)  # the Flask app is not needed in the browser


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def fetch_pyodide(dest: Path, given: Path | None) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if given is None:
        tmp = Path(tempfile.mkdtemp(prefix="pyodide-"))
        run(["npm", "pack", f"pyodide@{PYODIDE_VERSION}", "--silent"], cwd=tmp)
        tgz = next(tmp.glob("pyodide-*.tgz"))
        with tarfile.open(tgz) as tf:
            tf.extractall(tmp, filter="data")
        given = tmp / "package"
    version = json.loads((given / "package.json").read_text())["version"]
    if version != PYODIDE_VERSION:
        sys.exit(f"Pyodide {version} found, {PYODIDE_VERSION} expected")
    for name in PYODIDE_FILES:
        shutil.copy2(given / name, dest / name)
    shutil.copy2(given / "LICENSE", dest / "LICENSE") if (given / "LICENSE").exists() else None


def fetch_wheels(dest: Path) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    run([sys.executable, "-m", "pip", "download", "--quiet", "--no-deps", "--only-binary=:all:",
         "--dest", str(dest), *WHEELS])
    names = sorted(p.name for p in dest.glob("*.whl"))
    for n in names:
        if not n.endswith("-none-any.whl"):
            sys.exit(f"{n} is not a pure-Python wheel: it cannot run in the browser")
    return names


def pack_engine(dest: Path) -> str:
    dest.mkdir(parents=True, exist_ok=True)
    name = "mbhf.zip"
    src = ROOT / "src"
    with zipfile.ZipFile(dest / name, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted((src / "mbhf").rglob("*")):
            rel = path.relative_to(src)
            if path.is_dir() or "__pycache__" in rel.parts or rel.parts[1] in SKIP_IN_ENGINE:
                continue
            zf.write(path, rel.as_posix())
    return name


def build(out: Path, pyodide_dir: Path | None) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for path in (ROOT / "site").iterdir():
        shutil.copy2(path, out / path.name)
    shutil.copy2(ROOT / "src" / "mbhf" / "web" / "static" / "style.css", out / "style.css")
    (out / ".nojekyll").write_text("")
    fetch_pyodide(out / "pyodide", pyodide_dir)
    wheels = fetch_wheels(out / "py")
    engine = pack_engine(out / "py")
    sys.path.insert(0, str(ROOT / "src"))
    from mbhf import __version__

    (out / "manifest.json").write_text(
        json.dumps({"version": __version__, "pyodide": PYODIDE_VERSION, "engine": engine, "wheels": wheels}, indent=1)
    )
    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"site ready in {out} ({total / 1e6:.1f} MB)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "_site")
    ap.add_argument("--pyodide-dir", type=Path, default=None, help="an extracted pyodide npm package")
    args = ap.parse_args()
    build(args.out.resolve(), args.pyodide_dir)


if __name__ == "__main__":
    main()
