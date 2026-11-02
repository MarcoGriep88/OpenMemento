"""Build NSIS setup from a verified bundle; exercise an isolated install lifecycle."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import time
import uuid

import build_windows as desktop

ROOT = desktop.ROOT
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def payload_files(payload):
    files = []
    for path in sorted(payload.rglob("*")):
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(payload.resolve()):
            raise ValueError("Das Installationspaket darf keine Verknüpfungen nach außen enthalten.")
        if path.is_file():
            files.append(path.relative_to(payload))
    if Path("OpenMemento.exe") not in files:
        raise ValueError("Das geprüfte Programmpaket fehlt.")
    return files


def nsis_text(value):
    return str(value).replace("$", "$$").replace('"', '$\\"')


def ownership_list(files):
    lines = [f'Delete "$INSTDIR\\{nsis_text(path)}"' for path in files]
    directories = {parent for path in files for parent in path.parents if parent != Path(".")}
    lines += [f'RMDir "$INSTDIR\\{nsis_text(path)}"' for path in sorted(directories, key=lambda value: (-len(value.parts), str(value)))]
    return "\n".join(lines) + "\n"


def compile_setup(compiler, payload, files, workspace, output, version, product_id):
    owned = workspace / (product_id + "-owned.nsh")
    owned.write_text(ownership_list(files), encoding="utf-8-sig")
    numbers = version.split(".")
    if not 1 <= len(numbers) <= 4 or any(not part.isdecimal() or int(part) > 65535 for part in numbers):
        raise ValueError("NSIS benötigt eine numerische Version mit höchstens vier Teilen.")
    quad = ".".join(numbers + ["0"] * (4 - len(numbers)))
    definitions = {"APP_VERSION": version, "VERSION_QUAD": quad, "PRODUCT_ID": product_id,
        "APP_ICON": payload / "_internal" / "memento" / "resources" / "memento.ico",
        "PAYLOAD_DIR": payload, "SETUP_OUTPUT": output, "UNINSTALL_LIST": owned,
        "INSTALLED_KB": max(1, sum((payload / path).stat().st_size for path in files) // 1024)}
    if product_id != "OpenMemento":
        definitions["TEST_INSTALLER"] = 1
        definitions["TEST_LOG"] = workspace / "installer-runtime.log"
    print(f"NSIS: {product_id} wird kompiliert ...", flush=True)
    result = subprocess.run([str(compiler), "/V3", "/INPUTCHARSET", "UTF8", *[f"/D{key}={nsis_text(value)}" for key, value in definitions.items()],
        str(ROOT / "installer" / "Memento.nsi")], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=FLAGS)
    (workspace / (product_id + "-compiler.log")).write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"NSIS fehlgeschlagen: {result.stdout[-2000:]} {result.stderr[-2000:]}")


def install(setup, target, *, desktop_shortcut=False):
    # NSIS /D must be last, without quotes around its directory argument.
    return subprocess.run(subprocess.list2cmdline([str(setup), "/S", *(["/DESKTOP=1"] if desktop_shortcut else [])]) + " /D=" + str(target),
        timeout=180, creationflags=FLAGS).returncode


def uninstall(target):
    executable = str(target / "Uninstall.exe").replace("'", "''")
    # Start-Process -Wait includes the temporary uninstaller child process tree.
    command = f"$process = Start-Process -FilePath '{executable}' -ArgumentList '/S' -WindowStyle Hidden -Wait -PassThru; exit $process.ExitCode"
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True, timeout=120, creationflags=FLAGS)


def verify_lifecycle(setup, product_id, workspace, payload):
    import winreg

    target = desktop.checked_directory(workspace / "Install With Spaces" / "OpenMemento")
    invalid = desktop.checked_directory(workspace / "Unowned" / "OpenMemento")
    invalid.mkdir(parents=True)
    sentinel = invalid / "private-video.mp4"
    sentinel.write_bytes(b"unrelated file; never remove")
    if install(setup, invalid) == 0 or sentinel.read_bytes() != b"unrelated file; never remove":
        raise RuntimeError("Installer hat einen fremden nicht leeren Ordner akzeptiert.")
    key_name = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + product_id
    shortcuts = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / product_id
    install_status = install(setup, target, desktop_shortcut=True)
    if install_status:
        raise RuntimeError(f"Die isolierte Testinstallation ist fehlgeschlagen ({install_status}): "
                           + (workspace / "installer-runtime.log").read_text(encoding="utf-16-le", errors="replace"))
    try:
        if digest(target / "OpenMemento.exe") != digest(payload / "OpenMemento.exe"):
            raise RuntimeError("Die installierte EXE stimmt nicht mit dem Paket überein.")
        if digest(target / "LICENSE") != digest(ROOT.parent / "LICENSE"):
            raise RuntimeError("Die installierte GPLv3 stimmt nicht mit der Projektlizenz überein.")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            if Path(winreg.QueryValueEx(key, "InstallLocation")[0]) != target:
                raise RuntimeError("Der Programmeintrag verweist auf den falschen Ordner.")
        if not (shortcuts / "OpenMemento.lnk").is_file():
            raise RuntimeError("Der Startmenüeintrag fehlt.")
        keep = target / "keep-user-note.txt"
        keep.write_bytes(b"unowned note")
        environment = dict(os.environ, MEMENTO_DATA_DIR=str(workspace / "running-app-data"), QT_QPA_PLATFORM="offscreen")
        running = subprocess.Popen([str(target / "OpenMemento.exe")], env=environment, creationflags=FLAGS)
        try:
            deadline = time.monotonic() + 20
            while not (workspace / "running-app-data" / "library.sqlite3").exists():
                if running.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Die installierte Testanwendung wurde nicht bereit.")
                time.sleep(0.1)
            if running.poll() is not None or install(setup, target) == 0:
                raise RuntimeError("Aktualisierung einer laufenden Anwendung wurde nicht zurückgewiesen.")
        finally:
            if running.poll() is None:
                running.terminate()
                running.wait(timeout=10)
        if install(setup, target) or keep.read_bytes() != b"unowned note":
            raise RuntimeError("Aktualisierung hat fremde Dateien verändert.")
        desktop.smoke(target / "OpenMemento.exe", workspace)
        data_files = [path for folder in workspace.glob("smoke-*/data") for path in folder.rglob("*")
                      if path.is_file() and path.suffix in {".sqlite3", ".json", ".mov", ".mp4"}]
        before = {path: digest(path) for path in data_files}
        if not before:
            raise RuntimeError("Der installierte Funktionstest hat keine Prüfdaten erzeugt.")
    finally:
        if (target / "Uninstall.exe").exists():
            uninstall(target)
    if (target / "OpenMemento.exe").exists() or (target / "Uninstall.exe").exists() or shortcuts.exists():
        raise RuntimeError("Deinstallation hat Programmdateien oder Verknüpfungen zurückgelassen.")
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY).Close()
    except FileNotFoundError:
        pass
    else:
        raise RuntimeError("Deinstallation hat den Programmeintrag zurückgelassen.")
    if keep.read_bytes() != b"unowned note" or any(not path.exists() or digest(path) != value for path, value in before.items()):
        raise RuntimeError("Deinstallation hat fremde Dateien oder Anwendungsdaten verändert.")
    return {"fresh_install": True, "upgrade": True, "installed_app_smoke": True, "uninstall": True, "running_app_rejected": True,
            "foreign_directory_rejected": True, "unowned_file_preserved": True, "test_data_preserved": True,
            "project_license_installed": True,
            "test_product_id": product_id, "install_directory": str(target)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--use-existing", action="store_true", help="Vorhandenes Programmpaket prüfen und verwenden")
    parser.add_argument("--makensis", type=Path, help="Pfad zu makensis.exe")
    parser.add_argument("--bundle", type=Path, help="Separates Programmpaket innerhalb des Projekts (mit --use-existing)")
    options = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("Der Installer wird unter Windows gebaut und geprüft.")
    compiler = options.makensis or shutil.which("makensis") or Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "NSIS" / "makensis.exe"
    compiler = Path(compiler)
    if not compiler.is_file():
        raise RuntimeError("NSIS fehlt. NSIS 3 installieren oder --makensis angeben.")
    if options.bundle:
        if not options.use_existing:
            parser.error("--bundle benötigt --use-existing")
        bundle = desktop.checked_directory(options.bundle)
        provenance = json.loads((bundle / "build-info.json").read_text(encoding="utf-8"))
        if (provenance["source_sha256"] != desktop.source_digest()
                or provenance["executable_sha256"] != digest(bundle / "OpenMemento.exe")):
            raise RuntimeError("Das separate Programmpaket ist veraltet oder verändert.")
        desktop.smoke(bundle / "OpenMemento.exe", ROOT / "build")
    else:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_windows.py"),
                        *(["--verify-existing"] if options.use_existing else [])], check=True)
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    workspace = desktop.checked_directory(ROOT / "build" / ("installer-" + uuid.uuid4().hex))
    workspace.mkdir()
    payload = desktop.checked_directory(options.bundle or ROOT / "dist" / "OpenMemento")
    files = payload_files(payload)
    provenance = json.loads((payload / "build-info.json").read_text(encoding="utf-8"))
    snapshot = {str(path): digest(payload / path) for path in files}
    script_digest = digest(ROOT / "installer" / "Memento.nsi")
    license_digest = digest(ROOT.parent / "LICENSE")
    production = workspace / f"OpenMemento-Setup-{version}.exe"
    test_id = "OpenMemento-Test-" + uuid.uuid4().hex
    test_setup = workspace / "OpenMemento-Test-Setup.exe"
    compile_setup(compiler, payload, files, workspace, test_setup, version, test_id)
    result = verify_lifecycle(test_setup, test_id, workspace, payload)
    compile_setup(compiler, payload, files, workspace, production, version, "OpenMemento")
    if {str(path): digest(payload / path) for path in payload_files(payload)} != snapshot:
        raise RuntimeError("Das Programmpaket wurde während des Installer-Builds verändert.")
    if digest(ROOT / "installer" / "Memento.nsi") != script_digest:
        raise RuntimeError("Das NSIS-Skript wurde während des Builds verändert.")
    if digest(ROOT.parent / "LICENSE") != license_digest:
        raise RuntimeError("Die Projektlizenz wurde während des Builds verändert.")
    if desktop.source_digest() != provenance["source_sha256"]:
        raise RuntimeError("Die Anwendungsquellen wurden während des Builds verändert.")
    output = desktop.checked_directory(ROOT / "dist" / production.name)
    os.replace(production, output)
    report = {"status": "complete", "version": version, "installer": str(output), "installer_sha256": digest(output),
        "bundle_source_sha256": provenance["source_sha256"], "payload_files": len(files), "lifecycle": result,
        "nsis_script_sha256": script_digest,
        "license_sha256": license_digest,
        "signature": "unsigned", "scope": "development Windows machine; isolated test registration; not fresh-machine acceptance"}
    (ROOT / "build" / "latest-installer-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
