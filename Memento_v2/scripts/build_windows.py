"""Build and verify the desktop directory bundle, without accessing user media."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]


def source_digest():
    digest = hashlib.sha256()
    paths = (sorted((ROOT / "src").rglob("*.py"))
             + sorted((ROOT / "src" / "memento" / "resources").glob("*"))
             + [ROOT / "desktop_entry.py", ROOT / "pyproject.toml",
                ROOT / "requirements-runtime.lock", ROOT.parent / "LICENSE"])
    for path in paths:
        digest.update(path.relative_to(ROOT.parent).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def checked_directory(path):
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT.resolve()) or resolved == ROOT.resolve():
        raise RuntimeError("Build- und Ausgabepfade müssen innerhalb von Memento_v2 liegen.")
    return resolved


def inventory(destination):
    import imageio_ffmpeg

    destination.mkdir(parents=True, exist_ok=True)
    pending = ["memento-family-video-editor", "PyInstaller", "setuptools"]
    visited, records = set(), []
    while pending:
        name = pending.pop()
        dist = metadata.distribution(name)
        canonical = dist.metadata["Name"].lower().replace("_", "-")
        if canonical in visited:
            continue
        visited.add(canonical)
        licenses = []
        for item in dist.files or []:
            relative = Path(str(item))
            if ".." in relative.parts:
                continue
            if any(token in relative.name.lower() for token in ("license", "licence", "copying", "notice", "copyright")):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    target = destination / canonical / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    licenses.append(target.relative_to(destination).as_posix())
        records.append({"name": dist.metadata["Name"], "version": dist.version, "license_files": licenses})
        for text in dist.requires or []:
            requirement = Requirement(text)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(requirement.name)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copyfile(python_license, destination / "Python-LICENSE.txt")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for option, filename in (("-version", "ffmpeg-version.txt"), ("-L", "ffmpeg-license.txt")):
        result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), option], capture_output=True, timeout=15, creationflags=flags)
        (destination / filename).write_bytes(result.stdout + result.stderr)
    payload = {"python": sys.version.split()[0], "packages": sorted(records, key=lambda row: row["name"].casefold()),
               "public_distribution_review": "pending; inventory is not a licensing clearance"}
    (destination / "inventory.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def copy_documentation(destination):
    for name in ("README.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copyfile(ROOT / name, destination / name)
    shutil.copytree(ROOT / "docs", destination / "docs", dirs_exist_ok=True)
    shutil.copyfile(ROOT.parent / "LICENSE", destination / "LICENSE")


def smoke(executable, build):
    workspace = build / ("smoke-" + uuid.uuid4().hex)
    workspace.mkdir()
    report = workspace / "report.json"
    environment = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "MEMENTO_FFPROBE", "IMAGEIO_FFMPEG_EXE"):
        environment.pop(key, None)
    environment["MEMENTO_DATA_DIR"] = str(workspace / "data")
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PATH"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")
    completed = subprocess.run([str(executable), "--smoke-test", str(report)], env=environment,
                               capture_output=True, timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    (workspace / "process-output.txt").write_bytes(completed.stdout + completed.stderr)
    if not report.is_file():
        raise RuntimeError(f"Der Windows-Funktionstest lieferte keinen Bericht: {workspace}")
    result = json.loads(report.read_text(encoding="utf-8"))
    shutil.copyfile(report, build / "latest-smoke-report.json")
    if (completed.returncode or result.get("status") != "complete" or not result.get("preview_frame")
            or not result.get("recovery_roundtrip") or not result.get("capture_time_correction")
            or not result.get("date_range_page") or type(result.get("rendered_frames")) is not int
            or not result.get("application_icon")
            or result.get("editing_template") != "crossfade"
            or not 17 <= result.get("editing_template_frames", 0) <= 19
            or not 23 <= result["rendered_frames"] <= 25
            or not all(result.get(field) for field in ("planner_profile", "local_analysis_profile", "render_profile"))):
        raise RuntimeError(f"Der Windows-Funktionstest ist fehlgeschlagen: {report}")
    if result.get("credential_backend") != "keyring.backends.Windows.WinVaultKeyring" or not result.get("credential_roundtrip"):
        raise RuntimeError("Windows-Schlüsselspeicher wurde nicht in das Paket eingebunden.")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-existing", action="store_true", help="Nur das vorhandene Paket erneut prüfen")
    options = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("Dieser Build muss auf Windows ausgeführt werden.")
    build = checked_directory(ROOT / "build")
    destination = checked_directory(ROOT / "dist")
    checked_directory(build / "pyinstaller")
    checked_directory(destination / "Memento_v2")
    build.mkdir(exist_ok=True)
    executable = destination / "Memento_v2" / "Memento_v2.exe"
    if not options.verify_existing:
        initial_digest = source_digest()
        subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, check=True)
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
                   "--icon", str(ROOT / "src" / "memento" / "resources" / "memento.ico"),
                   "--collect-data", "memento",
                   "--name", "Memento_v2", "--noupx", "--paths", str(ROOT / "src"),
                   "--distpath", str(destination), "--workpath", str(build / "pyinstaller"), "--specpath", str(build),
                   "--collect-all", "imageio_ffmpeg", "--collect-all", "cv2",
                   "--hidden-import", "keyring.backends.Windows", "--copy-metadata", "keyring",
                   "--exclude-module", "pytest", "--exclude-module", "matplotlib", "--exclude-module", "IPython",
                   str(ROOT / "desktop_entry.py")]
        environment = dict(os.environ)
        environment["PYINSTALLER_CONFIG_DIR"] = str(checked_directory(build / "pyinstaller-config"))
        subprocess.run(command, cwd=ROOT, env=environment, check=True)
        copy_documentation(executable.parent)
        inventory(executable.parent / "third-party")
        if source_digest() != initial_digest:
            raise RuntimeError("Die Quellen wurden während des Builds verändert. Bitte neu bauen.")
        provenance = {"source_sha256": initial_digest, "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                      "pyinstaller": metadata.version("PyInstaller"), "python": sys.version.split()[0]}
        (executable.parent / "build-info.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    else:
        provenance = json.loads((executable.parent / "build-info.json").read_text(encoding="utf-8"))
        if provenance["source_sha256"] != source_digest() or provenance["executable_sha256"] != hashlib.sha256(executable.read_bytes()).hexdigest():
            raise RuntimeError("Das Paket stimmt nicht mit den aktuellen Quellen oder seiner EXE-Prüfsumme überein. Bitte neu bauen.")
    smoke(executable, build)
    print(f"Geprüfter lokaler Build: {executable}")


if __name__ == "__main__":
    main()
