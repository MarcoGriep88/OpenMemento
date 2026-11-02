# Hinweise zu Drittkomponenten

Dieses Windows-Verzeichnispaket ist ein lokaler Entwicklungs-/Prüfbuild von
Memento. Es enthält keine Hersteller-API-Schlüssel und lädt keine Modelle.
Gemini-Anfragen erfordern einen eigenen Schlüssel und den ausdrücklichen Start
im Analysedialog. Der eingebaute Funktionstest verwendet erzeugte Medien und
eine gespeicherte Testantwort ohne Netzwerkzugriff.

Der Build legt unter `third-party` die gefundenen Lizenzdateien der tatsächlichen
Laufzeitpakete sowie `inventory.json`, Python-Lizenz und FFmpeg-Version,
Konfiguration und Lizenzanzeige ab. Dies ist ein technischer Bestandsnachweis,
keine abgeschlossene Freigabe für öffentliche oder kommerzielle Verteilung.

Besonders zu prüfen sind die Pflichten der tatsächlich verwendeten Qt-/PySide-
und FFmpeg-Komponenten, einschließlich passender Quellen und Austauschbarkeit.
Das Verzeichnispaket hält Bibliotheken getrennt; es ersetzt diese Prüfung nicht.
FFmpeg kann je nach Konfiguration unter LGPL oder GPL stehen. Die konkrete
Konfiguration wird im Paket dokumentiert. Vor öffentlicher Weitergabe müssen
zugehörige Quellbereitstellung, Hinweise und weitere Pflichten erfüllt werden.

Maßgebliche Herstellerinformationen:

- [Qt for Python: Lizenzen](https://doc.qt.io/qtforpython-6/licenses.html)
- [FFmpeg: Lizenz- und Weitergabehinweise](https://ffmpeg.org/legal.html)
- [PyInstaller: Windows-Verzeichnispakete](https://pyinstaller.org/en/stable/usage.html)

Die Bibliothek, Filmprojekte, temporäre Medien und API-Zugangsdaten werden nicht
mit dem Build gebündelt. Die Bestandsliste enthält Paketversionen und Lizenzpfade,
keine Nutzermedien oder Zugangsdaten.
