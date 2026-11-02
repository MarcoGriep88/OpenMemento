# Workflow v2: Umsetzung und Prüfung

Die sechs Seiten sind als zusätzliche Qt-Oberfläche umgesetzt. Import- und
Analyse-Worker sowie der vorhandene Filmplaneditor und Renderer bleiben die
Verarbeitungsgrundlage. Leere Projekte, Projektordner, Zielzeit, Gemini-Prompt,
Datumsfilter, Schnittart, Musik und Exportpfad werden lokal gespeichert.
Die gemeinsame v2-Bibliothek kann ihre Analysen zwischen Projekten wiederverwenden.
Der Projektfilter berücksichtigt sämtliche gespeicherten Dateikopien eines Assets.
Geänderte Gemini-Prompts verwenden getrennte, wiederaufnehmbare Analyseprofile.

Der Originalton bleibt bei ausgeschalteter Hintergrundmusik erhalten. Importierte
Musik wird im Export und in der Gesamtfilmvorschau lokal mit 22 Prozent Lautstärke
gemischt, bei Bedarf wiederholt und am Ende ausgeblendet. Es gibt noch keine
automatische Sprach-Ducking-Funktion. Der Suno-Prompt entsteht lokal aus den
vorhandenen semantischen Beschreibungen und kann bearbeitet und kopiert werden.
Der Nutzer erzeugt das Lied in Suno, lädt es selbst herunter und importiert die
Musikdatei. Es gibt keine Suno-API-Anbindung und keinen automatischen Download.

Eigene Standarddaten liegen unter `%LOCALAPPDATA%/Memento_v2` bzw.
`$XDG_DATA_HOME/Memento_v2`; Qt-Einstellungen und OS-Schlüssel verwenden ebenfalls
den Namen Memento_v2. Die alte Bibliothek wird nicht automatisch übernommen.
Der explizite Entwicklungsparameter `MEMENTO_DATA_DIR` überschreibt diesen
Standard weiterhin und sollte für v1 und v2 auf getrennte Verzeichnisse zeigen.

Die Tests prüfen Projektneuanlage, Wiederöffnung, isolierte Auswahl und lokale
Jobs, Prompt-Cachetrennung, Wiederaufnahme ohne weitere Provideranfrage, Prompt
im Gemini-Request, beschädigte Projektdateien und den geführten Qt-Ablauf.
Echte FFmpeg-Tests prüfen Übergänge, Filmlänge, hörbare Musik im ursprünglich
tonlosen Abschnitt und unveränderte Originale. Die Renderertests prüfen außerdem
Abbruch, Wiederaufnahme und Zielschutz.
Die bestehende Testsuite wurde weiterverwendet. Die sechs Seiten wurden mit
synthetischen Daten gerendert und visuell geprüft. Kein kostenpflichtiger
Gemini- oder Suno-Aufruf wurde im Entwicklungsprozess gestartet.

Die älteren Statusdokumente beschreiben die übernommene Ausgangsversion.
Eine Abnahme mit echten Familienvideos und persönlichen API-Konten steht aus.

Prüfstand 01.11.2026: **321 Tests bestanden** (94,19 Sekunden), einschließlich
sieben Workflow-v2-Tests für Projekte, Prompt-Cache, Gemini-Request und Musikexport.
Der Windows-Verzeichnisbuild unter `dist/Memento_v2/Memento_v2.exe` wurde erstellt
und hat den Offline-Funktionstest bestanden: Fenster, Import, lokale Analyse,
Filmplan, FFmpeg-Export mit Ton, Videovorschau, Datumskorrektur, Wiederherstellung,
Übergänge und Windows-Schlüsselspeicher. Der Build enthält eine Quell-/EXE-Prüfsumme
in `build-info.json`; der Testbericht liegt unter `build/latest-smoke-report.json`.
