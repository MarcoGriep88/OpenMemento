# Windows-Installer mit NSIS

Voraussetzungen: Windows x64, die Python-3.12-Entwicklungsumgebung aus README.md
und NSIS 3 (`makensis.exe`). Der Builder findet NSIS im PATH oder unter
`C:\Program Files (x86)\NSIS`. Ein eigener Compilerpfad ist mit
`--makensis "D:\Tools\NSIS\makensis.exe"` möglich.

## Bauen

```powershell
cd C:\GitHub\OpenMemento\Memento_v2
.\build_installer.ps1
```

Der Befehl prüft/installiert die festgelegten Python-Buildabhängigkeiten, führt die
Tests aus, erzeugt das PyInstaller-Verzeichnispaket, prüft die gebaute EXE und
kompiliert anschließend den NSIS-Installer. Die Versionsnummer stammt aus
`pyproject.toml`. Das Ergebnis liegt unter `dist/Memento_v2-Setup-0.2.0.exe`
(entsprechend der jeweils eingetragenen Version).

Wenn das aktuelle Programmpaket bereits gebaut ist:

```powershell
.\build_installer.ps1 -UseExisting
```

Auch hierbei werden Quell-/EXE-Prüfsummen und der Offline-Funktionstest geprüft.
Ein veraltetes Paket wird zurückgewiesen. Direktaufruf:

```powershell
.venv\Scripts\python scripts/build_installer.py --use-existing
```

## Installation und Aktualisierung

- Deutsche Installationsoberfläche; Installation für das aktuelle Benutzerkonto,
  ohne Administratorrechte. Standard: `%LOCALAPPDATA%\Programs\Memento_v2`.
- Vor der Installation zeigt eine eigene Lizenzseite die vollständige
  **GNU General Public License, Version 3 vom 29. Juni 2007** aus der
  [Projektlizenz](../../LICENSE). Dieselbe Datei wird unverändert als `LICENSE`
  im Programmordner mitinstalliert und liegt auch im portablen Verzeichnispaket.
- Ein eigener leerer Programmordner mit dem Namen `Memento_v2` kann gewählt werden.
  Fremde nicht leere Ordner werden zurückgewiesen.
- Startmenüeintrag, Programmeintrag in Windows und optionale Desktop-Verknüpfung.
- Memento-Herz/Play-Icon für Anwendung, Desktop, Setup und Deinstallation.
- Eine bestehende, markierte Installation wird vor dem Kopieren der neuen Version
  über ihre bisherige Deinstallation bereinigt. Memento muss geschlossen sein.
- Bibliothek und Projekte unter `%LOCALAPPDATA%\Memento_v2` sowie Zugangsdaten im
  Windows-Schlüsselspeicher werden weder installiert noch gelöscht. Beim ersten
  Start einer neuen Programmversion können reguläre Bibliotheksmigrationen nötig sein.
- Die Deinstallation entfernt nur die im Paket enthaltenen Dateien. Nachträglich
  im Programmordner abgelegte fremde Dateien bleiben erhalten.

Unbeaufsichtigt: `Memento_v2-Setup-0.2.0.exe /S`. Ein anderer Zielordner kann mit
`/D=C:\Ziel\Memento_v2` angegeben werden; `/D=` muss das letzte Argument sein und
darf nicht separat in Anführungszeichen stehen. Deinstallation: `Uninstall.exe /S`.

## Automatische Prüfung und Grenzen

Der Builder kompiliert zusätzlich eine Testvariante mit eigener zufälliger
Registry-/Startmenükennung. Er prüft einen Pfad mit Leerzeichen, Neuinstallation,
Aktualisierung, Programmeintrag, Startmenü, den Funktionstest der tatsächlich
installierten EXE und Deinstallation. Testdaten und fremde Dateien müssen erhalten
bleiben. Die normale Memento-Installation und der Gemini-Schlüssel werden dafür
nicht verwendet. Berichte und Compilerlogs liegen unter `build/installer-*`,
das letzte erfolgreiche Ergebnis unter `build/latest-installer-report.json`.
Die Setup-Datei wird erst nach erfolgreicher Prüfung nach `dist` übernommen.
Die installierte GPLv3 wird dabei per SHA-256 mit der Projektlizenz verglichen;
der Prüfbericht enthält auch ihre Prüfsumme. Änderungen an Projektlizenz oder
festgelegten Laufzeitabhängigkeiten machen vorhandene Programmpakete für die
Wiederverwendung ungültig.

Der Installer ist derzeit **nicht digital signiert**. Authenticode-Signierung
benötigt ein eigenes Zertifikat und bleibt ein separater Veröffentlichungsschritt.
Es ist ein lokaler Entwicklungsbuild, kein vollständig freigegebenes kommerzielles
Release. Der Test auf dem Entwicklungsrechner ersetzt keine frische Windows-VM.
Lizenz-/Quellbereitstellungspflichten der gebündelten Komponenten bleiben gemäß
`THIRD_PARTY_NOTICES.md` vor öffentlicher Weitergabe zu klären.

Das NSIS-Skript liegt unter `installer/Memento.nsi`; die exakte Dateiliste für
die Deinstallation wird aus dem geprüften Paket erzeugt. Referenz:
[NSIS-Skriptreferenz](https://nsis.sourceforge.io/Docs/Chapter4.html).
