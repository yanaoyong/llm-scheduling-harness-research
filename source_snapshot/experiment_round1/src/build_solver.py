"""Build the unchanged upstream native clingo-dl entry point on macOS.

The PyPI package supplies the theory library but its Python entry point omits
--minimize-variable.  Linking upstream's two C++ files preserves that controller.
"""
from __future__ import annotations

import importlib
from importlib.metadata import version as package_version
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sysconfig

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "4f91f6233b441864ccc39195b6b7b515d92bd848"


def build() -> Path:
    if platform.system() != "Darwin":
        raise RuntimeError("This measured build is macOS-specific; build upstream with CMake on other platforms.")
    for package, expected in {"clingo": "5.8.2", "clingo-dl": "1.5.0.post1"}.items():
        actual = package_version(package)
        if actual != expected:
            raise RuntimeError(f"Dependency {package} must be {expected}, got {actual}; install requirements.lock.")
    vendor = ROOT / "vendor" / "clingo-dl"
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=vendor, text=True).strip()
    if commit != SOURCE_COMMIT:
        raise RuntimeError(f"Unexpected clingo-dl source: {commit}")
    clingo = Path(importlib.import_module("clingo").__file__).parent
    clingodl = Path(importlib.import_module("clingodl").__file__).parent
    clingo_lib = next(clingo.glob("_clingo*.so"))
    clingodl_lib = next(clingodl.glob("_clingodl*.so"))
    build_dir = vendor / "build"
    build_dir.mkdir(exist_ok=True)
    binary = build_dir / "clingo-dl"
    compiler = shutil.which("clang++")
    if not compiler:
        raise RuntimeError("clang++ is required (Apple command line tools).")
    framework = sysconfig.get_config_var("PYTHONFRAMEWORK")
    framework_prefix = sysconfig.get_config_var("PYTHONFRAMEWORKPREFIX")
    if not framework or not framework_prefix:
        raise RuntimeError("This build requires a framework Python providing its C runtime.")
    command = [compiler, "-std=c++17", "-O2", "-I", str(clingo), "-I", str(clingodl),
               "-I", str(vendor / "app/lib"), str(vendor / "app/src/main.cc"),
               str(vendor / "app/lib/src/app.cc"), str(clingo_lib), str(clingodl_lib),
               "-F", str(framework_prefix), "-framework", str(framework)]
    for directory in (clingo, clingodl):
        command.append("-Wl,-rpath,@executable_path/" + os.path.relpath(directory, build_dir))
    command += ["-o", str(binary)]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
    (build_dir / "build.stdout.log").write_text(completed.stdout)
    (build_dir / "build.stderr.log").write_text(completed.stderr)
    if completed.returncode:
        raise RuntimeError(completed.stderr)
    version = subprocess.check_output([str(binary), "--version"], cwd=ROOT, text=True)
    metadata = {"source_commit": commit, "source_modified": False, "command": command,
                "cwd": str(ROOT), "version": version, "platform": platform.platform(),
                "package_versions": {name: package_version(name) for name in ("clingo", "clingo-dl", "cffi")}}
    (build_dir / "build.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    return binary


if __name__ == "__main__":
    print(build())
