# Geführter Projektworkflow v2

Bestandsaufnahme: Prototype enthält den ursprünglichen OpenCV/Qt-Editor.
Memento und die vorhandene Kopie Memento_v2 haben bereits unabhängige Dienste
für Indexierung, lokale Analyse, semantische Analyse, Planung und FFmpeg-Export,
SQLite-Jobs, sichere Gemini-Zugangsdaten und versionierte Filmpläne. Diese
Bausteine werden weiterverwendet. Bisher fehlen leere Projekte, eine
Projektübersicht und eine durchgehende Navigation; Material und Analyse beziehen
sich auf die ganze Bibliothek. Der bestehende Renderer unterstützt feste
Übergangsvorlagen, bisher aber keine Musik.

Inkrementelles Ziel: eine zusätzliche WorkflowWindow auf der bestehenden
MainWindow-Verarbeitung. Sechs Seiten: Dashboard, Projekt, Material, Analyse,
Schnitt/Musik, Film/Export. Ein atomarer lokaler Projektkatalog speichert Titel,
Zielzeit, Materialordner, Datumsfilter, Schnitt- und Musikwünsche sowie den
separaten Filmplanpfad. Die gemeinsame v2-Medienbibliothek behält Analysen;
Projektfilter begrenzen lokale Analyse, Gemini und Planung auf Projektmaterial.
Filmpläne bleiben unabhängig editierbar. Keine Änderung an Memento/Prototype.

v2 erhält eigene Betriebssystem-Einstellungen, Zugangsdaten und Standarddaten
unter Memento_v2. Zufällige Übergänge sind reproduzierbar pro Clipwechsel;
klassische Schnitte bleiben wählbar. Musik wird lokal in Vorschau und Export
gemischt. Ein Suno-Prompt entsteht aus gespeicherten semantischen Momenten.
Der Prompt wird lokal erstellt, kann bearbeitet und kopiert werden. Der Nutzer
erzeugt das Lied in Suno, lädt es selbst herunter und importiert die Musikdatei.
Es gibt keine Suno-API-Anbindung und keinen automatischen Musikdownload.
