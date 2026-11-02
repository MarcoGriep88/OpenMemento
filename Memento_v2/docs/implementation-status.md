# Umsetzungsstand und verbleibende Abnahme

Stand: 22. Oktober 2026. Diese Liste ergänzt den ausführlichen Aufgabenplan;
sie ersetzt nicht die Produktanforderungen der übergeordneten AGENTS.md.

## Linux-Start und nicht erreichbare Medienordner

- Gespeicherte Medienordner werden beim Start ohne Dateisystemauflösung geladen.
  Videozahlen und Aufnahmezeiträume stammen aus SQLite. Die Anwendung öffnet
  sich auch mit nicht erreichbaren Freigaben.
- Separate Qt-Prozesse prüfen die Erreichbarkeit mit fünf Sekunden Zeitlimit
  pro Ordner. Die Tabelle meldet „Derzeit nicht zugreifbar“; „Erreichbarkeit
  prüfen“ ermöglicht erneutes Prüfen nach dem Verbinden eines Laufwerks.
- Ein Import behandelt Auflösungsfehler einzelner Ordner als gespeicherte
  Importfehler und verarbeitet andere Ordner weiter.
- Der Schlüsseladapter unterstützt native Secret-Service-/KWallet-/libsecret-
  Backends unter Linux und behält Windows Vault bei. Backend-Ketten werden auf
  einen ausdrücklich unterstützten sicheren Speicher begrenzt. Klartext- und
  Null-Backends werden abgewiesen. SecretStorage wird unter Linux mitinstalliert.
- Neue Linux-Bibliotheken verwenden XDG-Datenpfade. Vorhandene ältere
  Bibliotheken unter `~/AppData/Local/Memento` bleiben weiterhin nutzbar.
- `start_linux.sh` startet die lokale Entwicklungsinstallation mit Python 3.12.
  Ein Linux-Installationspaket wurde nicht erstellt.
- Bei der Linux-Abnahme wurde ein Qt/Shiboken-Absturz bei der Worker-Freigabe
  reproduziert. Explizite UI-Slots und synchronisierter Threadabschluss
  verhindern die gleichzeitige Freigabe von Qt- und Python-Workerobjekten.
- Linux-Verifikation: Python 3.12.15, PySide6 6.11.2, OpenCV 4.13.0.92.
  Die vollständige Testsuite bestand nach der Korrektur zweimal hintereinander:
  **311 bestanden, ein Windows-spezifischer Test übersprungen**.
- Der Offline-Funktionstest bestand sowohl mit Qt-Offscreen als auch im echten
  Linux-Desktopfenster: Import, Aufnahmezeitkorrektur, lokale Analyse,
  Testsemantik, Filmplan, Projektdatei, MP4 mit Ton, Crossfade, decodiertes
  Vorschaubild und Sicherung/Wiederherstellung. Ein temporärer Testeintrag wurde
  im tatsächlichen `keyring.backends.SecretService.Keyring` geschrieben,
  gelesen und gelöscht. Kein Gemini-Schlüssel wurde ausgelesen und keine
  Gemini-Anfrage gesendet.

## NSIS-Installer und aktuelles Windows-Paket

`build_installer.ps1` erstellt ein deutsches NSIS-Setup für Windows x64 mit
Installation pro Benutzer, Programmeintrag, Startmenü und optionalem Desktop-Link.
Version aus `pyproject.toml`, genauer Dateibesitz für Deinstallation und isolierter
Lebenszyklustest sind unter `docs/installer.md` beschrieben. Fremde nicht leere
Zielordner und Updates bei laufender Anwendung werden zurückgewiesen. Updates
entfernen zuerst die mitgelieferten Dateien der vorherigen Installation;
Bibliothek, Filmprojekte, fremde Dateien und Windows-Vault bleiben erhalten.

Die unkomprimierte Testvariante verwendet eine eigene zufällige Registry- und
Startmenükennung, der endgültige Installer LZMA-Kompression. Neuinstallation,
Update, Fremddateierhalt, App-Sperre, installierte EXE und Deinstallation bestehen
den isolierten Test. Der aktuelle Quellstand enthält Planer v10, lokale
Analyse v3 und Renderer v3; 280 Tests bestanden im Build-Lauf in 71,79 Sekunden.
Die Zielzeit ist ein Richtwert: Kürzeres verfügbares Material wird exportiert,
auch wenn Quelldauer-Metadaten mehr Videobilder erwarten lassen. Die Prüfung
des fertigen Films richtet sich nach den tatsächlich vorbereiteten Bildern.
Regressionen decken 454,40 Sekunden Material bei 454,40, 454 und 600 Sekunden
Zielzeit sowie kürzere Zielzeiten und sehr kurze Momente ab.
Der erweiterte EXE-Test prüft auch die Zeitraumtabelle und decodierte Bildanzahl
mit maximal einem Bild Rundung (23 von nominal 24 Bildern beim 12fps-Test).
Alle erzeugten Testmedien bleiben lokal; Gemini-Antwort ist eine Fixture.

Berichte liegen unter `build/latest-smoke-report.json` und nach erfolgreichem
Setup-Build unter `build/latest-installer-report.json`. Historische Prüfstände
weiter unten beschreiben ältere Builds. Signierung, öffentliche Lizenzfreigabe,
frische Windows-VM und tatsächliche Familienfilmqualität bleiben offen.

## Bestandsaufnahme und inkrementelle Architektur

Memento verwendet bereits Qt-unabhängige Dienste für rekursiven Import und
Shot-Erkennung, SQLite mit Migrationen, persistente Aufträge, Datumsabfragen
und einen Qt-Worker pro lokalem Auftrag. UltraCut bleibt erhalten und seine
Analyse-, Planungs-, Projekt- und Renderkomponenten sind als Referenz geprüft.
Insbesondere die normalisierten FFmpeg-Segmente, das atomare Ersetzen der
Ausgabedatei und die genaue Quellbereichsrepräsentation lassen sich übernehmen.
Sein globales Score-Ranking und die importabhängige Reihenfolge genügen dem
neuen Produktziel nicht.

Nächste Architekturabschnitte bleiben:

1. Quellen → persistenter Index → lokale Shots / Merkmale.
2. Versionierte semantische Analyse → persistente Quellbereiche.
3. Ereignisbildung und vielfältige Auswahl aus diesen Bereichen, ohne KI-Aufrufe.
4. Unabhängig gespeicherter, editierbarer Filmplan.
5. Lokaler FFmpeg-Export aus dem Filmplan; Worker bleiben reine Qt-Adapter.

Alle fünf Stufen sind jetzt angeschlossen und mit synthetischen Medien getestet.
Der vollständige Workflow ist weiterhin nicht qualitativ abgenommen: echte
Gemini-Antworten, reale Smartphone-Aufnahmen und die resultierenden Familienfilme
müssen noch beurteilt werden.

## Sicherung und Wiederherstellung

- `library/recovery.py` und `ui/recovery_dialog.py` ergänzen explizite Sicherungen,
  Prüfung und bestätigte Wiederherstellung im Hintergrund. Die Seitenleiste öffnet
  die Verwaltung; eine unlesbare Bibliothek oder `--restore-backup` führt beim
  Start in denselben Dialog. Ein laufender Medienauftrag muss vorher beendet sein.
- SQLite-Backup übernimmt auch bestätigte WAL-Daten. Sicherungsziele werden nicht
  überschrieben. Ausgewählte Quellen bleiben unverändert; Migrationen erfolgen
  ausschließlich an der vorbereiteten Kopie.
- Vor dem Austausch werden Integrität, Fremdschlüssel, unterstützte Version,
  Anwendungsschema, JSON-Aufträge und Medienwerte geprüft. Nicht unterstützte
  Trigger/Views und unsichere Medienkennungen werden zurückgewiesen.
- Der bisherige Stand wird separat erhalten. Ist er unlesbar, werden Originaldatei
  und vorhandene Sidecars als Notfallkopien gesichert. Ein Schreibfehler in dieser
  Sicherungsphase verhindert den Austausch.
- Ein dauerhaft gespeicherter Auftrag enthält die Prüfsumme der vorbereiteten
  Bibliothek. Nach Prozessabbruch vor oder nach dem atomaren Austausch wird er
  beim nächsten Start unter der Bibliothekssperre abgeschlossen, bevor SQLite
  geöffnet wird. Der laufende Abschluss wird dabei im Startdialog angezeigt.
- Vorbereitungs-/Kopierphasen sind abbrechbar und starten bei einem neuen Versuch
  neu. Nach dem gespeicherten Auftrag ist der abschließende Austausch nicht mehr
  abbrechbar. Eine explizit neu ausgewählte Sicherung kann einen unlesbaren alten
  Auftrag ersetzen; der alte Auftrag bleibt archiviert.
- Originalmedien, Filmprojekte und Schlüssel bleiben außerhalb der Wiederherstellung.
  Medienordner werden aus gespeicherten Importaufträgen ergänzt. Fehlende generierte
  Vorschaubilder können über den lokalen Analyseschritt neu erzeugt werden.
- Grundlage sind die [SQLite-Backup-API](https://www.sqlite.org/backup.html) und
  die Python-SQLite-Schnittstelle. Ein Stromausfalltest und Fremdprogramme mit
  eigenen offenen Schreibverbindungen sind noch nicht abgenommen.

## Aufnahmezeit, Desktop-Start und Windows-Build

- Schema 7 ergänzt eine eigenständige Metadatenversion. Alte Extraktionsergebnisse
  werden beim nächsten Indexlauf aktualisiert; bei unverändertem, verifiziertem
  Inhalt werden weder Hash noch lokale/KI-Analyse neu berechnet.
- Auch ohne FFprobe werden strukturierte globale und Video-Tags über das gebündelte
  FFmpeg ausgelesen. Ein ungültiger bevorzugter Wert verdeckt keinen gültigen
  Ersatzwert. QuickTime, verfügbare EXIF-Original-/Digitalisierungszeiten und
  explizite Offsets werden berücksichtigt; fehlende oder ungültige Zeitzonen
  bleiben unsicher. Date-only-Werte erhalten geringere Konfidenz.
- FFprobe überspringt eingebettete Coverbilder bei der Wahl der eigentlichen
  Videospur. Nicht endliche technische Dauerwerte werden verworfen. EXIF-Felder
  werden nur verarbeitet, wenn das Medienwerkzeug sie ausgibt.
- Die Desktop-Anwendung hält ab Start eine Betriebssystemsperre je Bibliothek,
  bevor Migrationen oder Jobs beginnen. Ein zweiter Prozess wird abgewiesen;
  eine zurückbleibende Lockdatei ist nach Prozessende kein Sperrgrund.
- `MEMENTO_DATA_DIR` trennt Bibliothek und Qt-Einstellungen für Test-/Arbeitsbereiche.
- Ein Windows-Verzeichnispaket wird aus der Testsuite und festgehaltenen Laufzeit-
  sowie Buildversionen erzeugt. Quell- und EXE-Prüfsummen, tatsächliche Paketversionen,
  gefundene Lizenztexte und FFmpeg-Konfiguration werden beigelegt.
- Der installierte Offline-Funktionstest verwendet erzeugte Video-/Audiodaten und
  eine gespeicherte semantische Testantwort, keine echten Gemini-Anfragen. Er
  prüft Import, Aufnahmedatum, lokale Merkmale, Planung, Projektdatei, tatsächliches
  Rendering, Tonspur und ein decodiertes Bild in der Qt-Vorschau. Windows-Vault
  wird mit einer separaten, danach gelöschten Testkennung geprüft; ein vorhandener
  Gemini-Schlüssel bleibt unberührt.
- Der Funktionstest läuft mit isolierten Daten und auf Windows-Systemprogramme
  reduziertem PATH. Dies belegt die gebündelten Abhängigkeiten auf diesem Rechner,
  ersetzt aber keinen Test auf einer sauberen Windows-VM.
- Das Paket ist ein lokaler Entwicklungsstand. Kommerzielle/öffentliche Weitergabe,
  zugehörige Quellbereitstellung und vollständige Lizenzprüfung sind nicht freigegeben.

## Verifizierte Inhaltsidentität

- Schema 6 ergänzt `assets.content_sha256`, einen eindeutigen Inhaltsindex,
  Standortverfügbarkeit, Alias-IDs für zusammengeführte Altbestände und die
  persistente Importoption zur vollständigen erneuten Inhaltsprüfung.
- Der Import hasht neue und bisher unverifizierte Dateien vollständig, in
  4-MiB-Blöcken mit Fortschritt, Abbruch und Prüfung des Dateistands vor/nach
  dem Lesen. Bereits verifizierte, nach Größe/Zeit unveränderte Dateien werden
  im normalen Folgescan übersprungen. Der Hash belegt den Inhalt zum Prüfzeitpunkt.
- Bytegleiche Kopien teilen sich eine Medienidentität, Analyse und Quellbereiche.
  Umbenannte Dateien werden über den Hash zugeordnet. Geänderte verifizierte
  Inhalte bekommen eine neue Identität; die alte Analyse bleibt für vorhandene
  oder später erneut importierte Originalkopien erhalten.
- Bei der erstmaligen Verifizierung unveränderter Altdateien bleiben Cache- und
  Kandidaten-IDs erhalten. Zusammengeführte historische Antworten bleiben
  inspizierbar; äquivalente Analysebereiche vermeiden neue Provideraufrufe.
- Aufnahmezeiten mit höherer Zuverlässigkeit sowie manuelle Vorgaben haben
  Vorrang vor dem Änderungsdatum einer neuen Kopie. Gleiche Dateizeitpunkte in
  unterschiedlichen Zeitzonendarstellungen invalidieren den Altbestand nicht.
- Filmformat 3 enthält optional den verifizierten Quellhash; Formate 1 und 2
  werden weiterhin gelesen. Vor dem Export werden fehlende oder ersetzt
  indexierte Quellen nur bei vollständiger Inhaltsgleichheit wiederverknüpft.
  Bestehende Schnittbereiche bleiben dabei unverändert.
- Vor dem Rendern und vor noch nicht gespeicherten semantischen Uploads werden
  Quellen mit bekanntem Hash vollständig geprüft. Eine geänderte Datei mit
  gleicher Größe und Änderungszeit wird dabei abgefangen. Normale Folgescans
  können solche Änderungen erst mit „Inhalte erneut prüfen“ feststellen.

## Lokale Qualität und visuelle Wiederholungen

- Die bestehende Shotanalyse verwendet nun die unabhängige Version
  `opencv-hsv-quality-phash-v3`. Neben Shotgrenzen und Vorschaubildern speichert
  sie räumliche Stichproben in etwa 0,5-Sekunden-Fenstern: Laplace-Schärfe,
  Helligkeit, dunkle/helle Anteile, Textur, affine Bewegung und deren Unruhe,
  sowie DCT-Bildsignaturen und mittlere Farben.
- Schärfe, Belichtung und affine Bewegungsanalyse übernehmen die Prinzipien aus
  `Prototype/video_analysis.py`; die Umsetzung bleibt unabhängig vom Prototyp.
  Bei starken Bildwechseln wird die Bewegungszustandsschätzung zurückgesetzt.
- Schema 5 speichert `local_feature_windows`. Shots, Messwerte, Analyseabschluss
  und erfolgreicher Lauf werden atomar übernommen. Änderungen einer Quelle
  invalidieren diese Werte; fehlgeschlagene oder veraltete Analysen werden nicht
  als aktuelle Messwerte verwendet.
- Der Planer bildet die technischen Werte nach zeitlicher Überlappung auf den
  jeweiligen Kandidaten ab, auch bei geänderten Schnittgrenzen. Weniger als
  50 Prozent Messabdeckung ergibt keinen Qualitätswert. Dieser bleibt eine
  kleine Präferenz gegenüber semantischer und emotionaler Relevanz.
- Visuelle Ähnlichkeit benötigt mindestens drei strukturierte Bildstichproben,
  ausreichende Abdeckung, geringe Hashdistanz und ähnliche Farben. Gleichförmige
  schwarze/helle Bilder beweisen keine Wiederholung. Die Ähnlichkeit beeinflusst
  seit Planner v5 die Auswahl im gesamten Film und ist kein sicherer Inhaltsduplikat-
  nachweis. Erzwungene Momente bleiben verwendbar.
- Die globale Bildähnlichkeit bevorzugt abwechslungsreiche Alternativen auch
  über Ereignisgrenzen hinweg, ohne ähnliche Bereiche automatisch auszuschließen.
  Wiederkehrende Beschreibungen, Aktivitäten und Personenlabels werden weiterhin
  nur innerhalb eines Ereignisses verglichen. Automatisch gekürzte Bereiche
  nutzen nicht die Bildsignaturen ihres vollständigen Kandidaten als Beleg.
  Verbleibende ähnliche Auswahlen tragen einen Prüfhinweis für Inhalt und Ton.
  Bei gleichem Abdeckungsbedarf folgt die Auswahl der chronologischen Ereignisfolge,
  damit zufällige Hashkennungen nicht über die erste Vergleichsreferenz entscheiden.
  Tests decken Alternativen in späteren Ereignissen, erzwungene und dennoch
  bedeutungsvolle ähnliche Momente, einfarbige Bilder sowie gekürzte Bereiche ab.
- Der Planer liest lokale Messwerte in Batches von 100 Assets, um nicht den
  gesamten Bildindex einer großen Bibliothek gleichzeitig im Speicher zu halten.
- Neue Filmpläne protokollieren Planerversion und verwendete lokale Analyseversion.
  Der damalige Formatstand 2 ergänzte Planerversionen; Filmformat 3 unterstützt
  auch bestehende Version-1- und Version-2-Dateien. Alte Planungen werden
  nicht nachträglich als mit dem neuen Algorithmus erzeugt ausgewiesen.
- Eine neue lokale Analyseversion invalidiert keine erfolgreichen Gemini-Ergebnisse.
  Die Oberfläche benennt den lokalen Analyseschritt jetzt entsprechend.

## Sicherung vor Migration

Vor der Migration einer bestehenden SQLite-Bibliothek wird eine Sicherung unter
`backups/` neben der Datenbank geschrieben. Die SQLite-Backup-API berücksichtigt
bestätigte WAL-Daten. Eine fehlgeschlagene Sicherung lässt die Migration nicht
beginnen. Geführte Wiederherstellung und Desktop-Instanzkoordination sind inzwischen
ergänzt; externe direkte Service-Nutzung und Stromausfälle bleiben gesondert zu prüfen.

## Ereignisse, Filmplan und lokaler Export

- Planner `event-balanced-local-v8` trennt auch dicht aufeinanderfolgende
  Aktivitäten, wenn jeweils zwei unabhängige, ausreichend sichere Aufnahmen den
  Wechsel in Ereignisbezeichnung/Aktivitäten bestätigen. Mindestens 30 Sekunden
  müssen ohne Kameraabdeckung zwischen den Gruppen liegen. Einzelne Reaktionen,
  parallele Kameras, bloße Teilbereiche einer Quelle und schwache Bestätigungen
  erzeugen dadurch keine zusätzliche Grenze. Bestehende Tages-/Pausenregeln
  bleiben erhalten. Schnittkorrekturen ändern die zugrunde liegenden Zeitpunkte
  nicht; die Analyse bleibt unverändert gecacht. Ein synthetischer Rundlauf mit
  acht Garten- und zwei Bootsaufnahmen weist getrennte Zeitbudgets, Chronologie,
  Projektöffnung und erneute Gewichtung ohne Änderung des KI-Caches nach.
  Reale Ereignisqualität und lexikalisch nicht erkennbare Wechsel bleiben offen.

- Die Filmplanung bietet jetzt „Rückgängig“ / „Wiederholen“ und Strg+Z / Strg+Y
  für bis zu 50 Änderungen in der laufenden Sitzung. Zurückgenommen werden nur
  Filmplan, Vorgaben und Neuplanung, ohne Bibliothek oder KI-Caches zu kopieren.
  Wiederhergestellte Stände werden atomar gespeichert; bei Schreibfehlern bleiben
  letzter gespeicherter Plan und Historienposition erhalten. Projektöffnung startet
  eine neue Historie; dauerhafte Versionshistorie ist nicht implementiert.
  Tests prüfen unter anderem Schnitt, Entfernen, Reihenfolge, Ereignisgewicht,
  Neuplanung, Titel, Tastenkürzel, Schreibfehler und unveränderte KI-Ergebnisse.

- Aufnahmezeiten lassen sich über „Aufnahmezeiten prüfen“ korrigieren. Die
  seitengesteuerte Liste sucht auch nach weiteren Dateikopien und zeigt fehlende
  beziehungsweise unsichere Zeiten unabhängig vom gewählten Filmzeitraum.
  Datum, Uhrzeit und optionaler UTC-Abstand werden ausdrücklich bestätigt;
  die Rechnerzeitzone wird nicht ergänzt. Manuelle Zeiten bleiben bei erneuter
  Indizierung identischer Inhalte erhalten. Analysecaches, Quelldateien und
  gespeicherte Filmpläne werden dadurch nicht geändert. Einzelkorrektur ist
  vorhanden; gemeinsame Zeitverschiebung und automatische Zeitzonenreparatur
  bleiben offen.

- `domain/movie.py`: Quellstand, Kandidaten, Ereignisse, exakte Schnittbereiche,
  Nutzerwünsche und Filmplan. Validierung verhindert nicht endliche Grenzen,
  Bereiche außerhalb der Quelle, doppelte Segmente und überlappende Quellbereiche.
- `application/movie_planning.py`: absolute Quellzeiten aus dem Analysecache,
  Chronologie nach aufgezeichneter Ortszeit, Ereignisse aus freier Beschreibung
  und Aufnahmeabständen. Unterschiedliche Tage, Lücken über 90 Minuten oder
  semantische Wechsel nach über zehn Minuten beginnen ein neues Ereignis.
- Ereignisbudgets verwenden Erinnerungswert und Nutzergewicht statt Clipanzahl.
  Bei sehr kurzen Filmen werden Vertreter aus chronologischen Ereignisgruppen
  ausgewählt, damit nicht ausschließlich unbrauchbare Sekundenbruchteile je
  Ereignis entstehen. Kurze Ereignisse können weitere Ereignisse zum Füllen des
  Budgets zulassen; erzwungene Ereignisse bleiben erhalten.
  Seit Planner `event-balanced-local-v3` wird die Kapazität je Quelle aus
  miteinander vereinbaren Bereichen berechnet, sodass überlappende Kandidaten nicht
  doppelt zählen. Bleibt nach der ersten ausgewogenen Auswahl Zeit übrig,
  werden konfliktfreie Restkandidaten erneut nach Ereigniswert und Nutzergewicht
  budgetiert. Bereits ausgewählte Momente bleiben erhalten; kürzere Ergebnisse
  sind weiterhin möglich, etwa durch vorherige Kürzungen oder fehlendes Material.
  Innerhalb der Ereignisse werden Emotion, Audio, Wichtigkeit, Einzigartigkeit,
  semantische Redundanz sowie Aktivitäts- und beschreibende Personenvielfalt
  berücksichtigt. Personenlabels sind weiterhin keine Identitäten.
- Natürliche Kandidatenbereiche werden bevorzugt, wenn ihr Wert ähnlich ist.
  Planner `event-balanced-local-v6` erlaubt zusätzlich begrenzte Zeitübertragungen
  zugunsten vollständiger vorgeschlagener Bereiche: bis zu zwei Sekunden pro
  Auswahl, bis zu 25 Prozent des empfangenden Ereignisbudgets und insgesamt bis
  zu 15 Prozent der Filmzielzeit. Andere offene Budgets finanzieren die Übertragung;
  deren vorhandener Erstanteil bis zwei Sekunden bleibt reserviert. Die Zielzeit
  steigt dadurch nicht. Auswahlgründe nennen die Umverteilung. Ein synthetischer
  Referenztest verbessert bei 16 Sekunden Zielzeit die Abdeckung der zwei fest
  vorgegebenen Bereiche von 90 auf 100 Prozent gegenüber einer rekonstruierten
  harten Budgetauswahl. Zehn Ereignisse bleiben in einer weiteren Regression
  vertreten. Reale Handlungs-/Sprachgrenzen und inhaltliche Abnahme bleiben offen.
  Planner `event-balanced-local-v4` erhält manuelle Schnittgrenzen exakt, wenn
  der Moment ausgewählt wird. Sie dürfen das weiche Ereignisbudget überschreiten,
  aber nur erzwungene Momente überschreiten die gesamte Zielzeit. Zu lange manuelle
  Bereiche blockieren andere verwendbare Aufnahmen nicht. Ereignisse bleiben an
  den ursprünglichen Analysezeiten verankert; Änderungen der Schnittanfänge
  verändern ihre IDs und gespeicherten Nutzergewichte nicht. Die Ausgabe folgt
  trotzdem den tatsächlichen Schnittanfängen. Fehlende Schnittvorgaben und über
  den vorgeschlagenen Moment hinausgehende Bereiche erhalten Prüfhinweise.
  Für knappe Zeitbudgets notwendige Kürzungen tragen einen Prüfhinweis. Erzwungene
  Momente haben Vorrang vor der Zielzeit. Fehlendes Material wird nicht wiederholt.
- `library/movies.py`: versionierte `.memento.json`-Projekte mit atomarem Speichern,
  getrennt von SQLite und dem Analysecache. Der Plan enthält Quellstände, die
  vor dem Rendern erneut geprüft werden.
- `ui/movie_dialog.py`: Hintergrundplanung, Einzelvorschau mit Ton, Schnittgrenzen,
  Entfernen, Umordnen, Ein-/Ausschluss, Ereignisgewicht, Neuplanen, Speichern,
  Öffnen, Renderfortschritt, Abbruch und Öffnen des exportierten Films.
- „Ereignisse und Zeitverteilung“ ergänzt eine schreibgeschützte Prüfung des
  tatsächlichen Films. Der Qt-unabhängige Bericht aus `domain/movie_review.py`
  erfasst Dauer, Anteil, aktive Auswahl, bekannte Kandidaten und Vorgaben je
  Ereignis. Nicht enthaltene Ereignisse bleiben sichtbar; deaktivierte Segmente
  zählen nicht. Fehlende erzwungene Momente, noch enthaltene ausgeschlossene
  Bereiche und abweichende Schnittvorgaben werden getrennt ausgewiesen; verwaiste
  Vorgaben bekommen einen Hinweis. Gewichte werden ausdrücklich als Wünsche für
  Neuplanung erklärt. Tests prüfen Anteile, leere Ausgabe, deaktivierte Bereiche,
  Vorgabenabweichungen und unveränderte Projektdateien ohne Bibliothekszugriff.
- `ui/candidate_dialog.py` zeigt Momente und historische Auswahlentscheidungen
  über ein bei Bedarf abgefragtes Qt-Tabellenmodell. Wieder geöffnete Filme laden
  Kandidaten separat im abbrechbaren Hintergrundauftrag, ohne Neuplanung oder
  Upload. Fehlende historische Momente und ihre Vorgaben bleiben sichtbar;
  veraltete Erzwungen-Vorgaben sowie manuelle Schnitte lassen sich bereinigen.
  Gegensätzliche Ein-/Ausschlüsse werden direkt gegenseitig aufgehoben.
  Abbrechen verwirft Dialogänderungen, Übernehmen speichert nur Vorgaben als
  rückgängig machbaren Schritt. Die Timeline bleibt bis zum ausdrücklichen Neuplanen
  erhalten. Tests prüfen 20.000 Modellzeilen, Tastaturbedienung, fehlende IDs,
  Projektöffnung ohne Änderung der gespeicherten Datei, Undo sowie Abbruch/Retry.
- Eine vollständige lokale Filmvorschau nutzt denselben FFmpeg-Schnittpfad mit
  640 × 360, 30 Bildern/s und Originalton. Pause und Zeitleiste erlauben die
  zusammenhängende Prüfung. Unveränderte Pläne verwenden ihre Sitzungsvorschau
  erneut; Änderungen erzeugen sie bei Bedarf neu. Vorschau und Export bleiben
  getrennt; weder Plan noch KI-Cache werden durch die Vorschauerstellung verändert.
  Abbruch nutzt die vorhandene Renderwiederaufnahme. Beim regulären Schließen
  werden fertige Vorschaufilme nach Freigabe des Players bestmöglich entfernt;
  nach Absturz oder bei gesperrten Dateien können sie im lokalen Cache verbleiben.
  Tests prüfen echte Vorschauframes, Auflösung, Dauer, Reihenfolge, Pause, Springen,
  Wiederverwendung, Änderungen, Abbruch, erneuten Versuch und Sitzungsbereinigung.
  Die Ereignisauswahl verdeckt nicht länger Qt-eigene `event()`-Aufrufe.
- `application/rendering.py`: Qt-unabhängiger lokaler FFmpeg-Dienst nach den
  normalisierten H.264-/AAC-Segmenten, Concat und atomarer Ausgabe des Prototyps.
  Unterschiedliche Seitenverhältnisse werden eingepasst; Originalton bleibt
  enthalten, fehlende Audiospuren werden durch Stille ersetzt.
- Renderaufträge und fertige Teile liegen unter `cache/renders`. Ein erneuter
  Export identischer Quellen, Bereiche und Einstellungen setzt diese Teile fort,
  auch nach Neustart. Unveröffentlichte Ausgaben werden bei Fehlern bereinigt;
  vorhandene Zieldateien werden auch bei einer Namenskollision während des
  Renderns nicht überschrieben.
- Cacheabfragen für große Auswahlen erfolgen in Batches über eine Verbindung,
  nicht mit einer Datenbankverbindung pro Aufnahme.

## Semantische Analyse

- `ai/contracts.py`: austauschbarer `AIProvider`, strukturierte Momente,
  Validierung von Typen, endlichen Zahlen, Konfidenzen und disjunkten Zeitbereichen.
- `ai/gemini.py`: direkter HTTPS-Aufruf mit BYOK-Header, Inline-MP4 mit Ton und
  strukturiertem Antwortschema. Keine Files-API, kein Herstellerdienst.
  Weiterleitungen sind gesperrt; Fehlertexte enthalten keine fremden Antwortkörper.
- `ai/segmentation.py`: Neue Bereiche orientieren sich an aktuellen lokalen
  Schnittwechseln bis zu zehn Sekunden neben der nominalen 45-Sekunden-Grenze.
  Die Zahl der Anfragen pro noch nicht analysierter Lücke steigt dadurch nicht;
  kein Abschnitt überschreitet 60 Sekunden. Kurze Restabschnitte werden nach
  Möglichkeit vermieden. Bereits bezahlte Bereiche, einschließlich leerer Antworten,
  bleiben erhalten; nur echte Lücken werden neu aufgeteilt. Historische
  Überlappungen zählen bei der Vollständigkeitsprüfung nur einmal.
- `media/analysis_proxy.py`: FFmpeg erzeugt temporäre Abschnitte von höchstens
  60 Sekunden, 640 px und 12 Bildern/s mit AAC-Ton; Metadaten und Kapitel werden
  entfernt. Quellen werden ausschließlich gelesen. Das Uploadlimit beträgt 8 MiB
  je Abschnitt vor Base64-Kodierung.
- `library/semantic.py`: Schema 4 speichert Auftrag, Quellstand, Bereich,
  Provider, Modell, Version, Momente, Konfidenzen, Begründungen, erfolgreiche
  Tokenverbräuche und Anzahl versuchter Aufrufe. Erfolgreiche Ergebnisse und
  Bereichsabschluss werden gemeinsam in einer Transaktion gespeichert.
- `application/semantic_analysis.py`: Wiederaufnahme nutzt gespeicherte Ergebnisse,
  auch nach Prozessabbruch. Modellwechsel erzeugt andere Cacheeinträge.
  Neuindexierung veränderter Dateien entfernt alte semantische Ergebnisse.
  Ein leerer, gültiger Analysebefund wird ebenfalls gespeichert.
- Ein konfigurierbares Limit begrenzt die Anbieteraufrufe je ausdrücklich
  gestartetem Durchlauf einschließlich fehlgeschlagener Aufrufe und Wiederholungen.
  Die Oberfläche startet mit höchstens 25 Aufrufen; Cachetreffer verbrauchen keinen.
  Bei Erreichen des Limits bleibt der Auftrag mit Status `request_limit`
  wiederaufnehmbar. Der nächste Start erhält ein neues Limit und nutzt erfolgreiche
  Antworten weiter. Aufrufversuche werden über die vorhandenen persistenten
  Bereichszähler summiert. Die Anzeige trennt offenen Gesamtumfang vom gedeckelten
  Übertragungsumfang des Starts. Ein Geldlimit und eine vollständige Google-
  Abrechnung sind damit nicht implementiert. Tests prüfen Neustart, Cachetreffer,
  Retry-Grenzen, Abbruch, ungültige Limits und begrenzte Desktop-Durchläufe.
- `ui/semantic_dialog.py`: Auswahl und Quellbereiche vor dem Upload, Mengenabschätzung,
  ausdrücklicher Start, Abbruch, Fortschritt, Fehler, Ergebnisse und Wiederaufnahme.
  Das Öffnen des Dialogs führt keine Gemini-Anfrage aus.
- Die Bereichstabelle liest höchstens 100 Bereiche pro Seite aus einer gemeinsamen
  Datenbankabfrage für Quelle, direkten beziehungsweise äquivalenten Cachebefund
  und Auftragsstatus. Andere Seiten werden nicht als Tabellenzellen oder JSON-
  Antworten geladen. Der Seitenwechsel benötigt eine Verbindung; Gesamtzahl und
  Seitengrenzen stammen aus einem gemeinsamen Lesestand. Ein Auftragswechsel
  beginnt auf der ersten Seite. Die Auftrags-/Uploadauswahl bleibt davon unabhängig.
  Ein Desktop-Test mit 20.000 Bereichen prüft begrenzte Verbindungen, Navigation
  bis zum letzten Bereich und das Zurücksetzen beim Auftragswechsel. Tests prüfen
  auch direkte und historische äquivalente Antworten sowie leere Seiten.

Die Implementierung folgt Googles Dokumentation zu
[Inline-Videoeingaben](https://ai.google.dev/gemini-api/docs/generate-content/video-understanding)
und [strukturierten Ausgaben](https://ai.google.dev/gemini-api/docs/structured-output).
Das Modell ist im Einstellungsdialog frei konfigurierbar.

## Grenzen und offene Nachweise

- `python -m memento.evaluate` ergänzt eine lokale Referenzauswertung mit validiertem
  Format für menschlich markierte Schlüsselmomente und alternative Kameras.
  Gemessen werden gewichtete Bereichsabdeckung, Erhalt ab festgelegter Schwelle,
  Ereignisabdeckung und wiederholte identische Quellzeit. Gleiche Zielzeit und
  gleicher Zeitraum sind Voraussetzung; Referenz und Timeline werden per Prüfsumme
  zugeordnet. Tests nutzen synthetische Referenzbereiche. Menschliche Annotationen
  echter Sammlungen und die Filmabnahme bleiben weiterhin offen. Abdeckung allein
  belegt weder emotionale Auswahlqualität noch natürliche Schnitte oder Tonqualität.
- Die Referenzauswertung besteht 19 gezielte Tests und einen direkten CLI-Probelauf.
  Ein Gesamtlauf blieb einmal ohne Abschluss stehen und wurde zur Diagnose
  unterbrochen. Der anschließende ausführliche Gesamtlauf mit Stack-Diagnose
  bestand alle 215 Tests; die Ursache des Stillstands ließ sich nicht reproduzieren.
  Die Testsuite gibt künftig nach 60 Sekunden in einem einzelnen Test einen
  Stack-Dump aus. Das ist eine Diagnosehilfe, keine Behebung oder Abnahme des
  beobachteten Stillstands.

- Tests nutzen synthetische Medien und gemockte Gemini-Antworten. Ein echter
  kostenpflichtiger Gemini-Aufruf und qualitative Tests an freigegebenen
  Familienaufnahmen stehen aus. Die tatsächliche Auswahlqualität ist unbewiesen.
- Bereits verifizierte Dateien werden bei normalen Folgescans anhand ihrer
  Attribute übersprungen. Für Änderungen unter beibehaltenen Dateiattributen
  ist eine erneute Inhaltsprüfung nötig. Alte Filmprojekte ohne Quellhash können
  nicht allein aus einem ähnlichen Dateinamen sicher wiederverknüpft werden.
- Abschnittsgrenzen berücksichtigen lokale Schnittwechsel, erkennen aber noch
  keine Sprach- oder Handlungsgrenzen. Lange ungeschnittene Handlungen und
  Beziehungen zwischen Aufnahmen benötigen zusätzliche Kontextbildung; es gibt
  noch keinen überlappenden Analysekontext. Beschreibende Personenlabels sind
  keine Identitätserkennung.
- Noch keine automatische Vorselektion anhand lokaler Qualitäts-/Ähnlichkeitswerte;
  alle noch nicht gespeicherten Bereiche der bestätigten Auswahl werden analysiert.
- Qualitäts-/Bewegungswerte und Bildähnlichkeit sind Stichprobenheuristiken und
  noch nicht an realen Smartphone-Aufnahmen kalibriert. Ähnliche Bildstichproben
  allein werden nicht zum Überspringen von KI-Uploads verwendet; dies erfolgt
  nur über gespeicherte Analysen derselben verifizierten Quelle.
- Ereigniserkennung und Redundanz verwenden lexikalische Ähnlichkeit, noch keine
  Embeddings, Ortsdaten oder verifizierten Beziehungen zwischen Personen.
- Integrierte Qt-Videowiedergabe, echte HDR/VFR-Aufnahmen, weitere Smartphone-Codecs
  sowie lange Filmexporte benötigen Tests auf dem Windows-Zielrechner. Der Renderer
  unterstützt zunächst saubere Schnitte; Musik und Effekte sind nachgelagert.
- Tokenzahlen erfassen nur erfolgreiche, empfangene Antworten, nicht die vollständige
  Google-Abrechnung. Netzwerkausfälle nach abgeschickter Anfrage können zu Kosten
  ohne Cacheeintrag führen. Solche Fehler werden nicht automatisch wiederholt.
- HTTP 429 und 5xx werden höchstens zweimal mit abbrechbarer Wartezeit wiederholt.
  Nach anhaltenden HTTP-/Netzwerkfehlern stoppt der Auftrag weitere Übertragungen;
  ein ungültiger Schlüssel löst keine Anfrage pro weiterer Quelldatei aus.
- Ein laufender HTTPS-Aufruf verwendet 60 Sekunden Socket-Timeout; das ist keine
  garantierte Gesamtlaufzeit. Er kann beim Abbruch noch weiterlaufen, bis eine
  Antwort oder ein Netzwerk-Timeout eintritt. Bereits erfolgreich empfangene Antworten
  werden vor dem Stoppen gespeichert. Ein harter Prozessabbruch kann temporäre
  Dateien im Betriebssystem-Tempordner zurücklassen.
- Direkte parallele Nutzung der Service-APIs, große echte Medienbestände, Smartphone-
  Metadaten, HDR/VFR und reale Audio-/Videoqualität benötigen weitere Integrationstests.
- Sauberes Windows-Testsystem, Installer/Updateablauf und die
  nachgelagerten kommerziellen Funktionen bleiben offen.

## Nächste Umsetzung

Die noch offenen Zuverlässigkeits- und Auslieferungsfälle umsetzen.
Anschließend echte freigegebene Familienaufnahmen und
Gemini-Antworten verwenden, um Ereignisbildung, Handlungsgrenzen und Auswahlqualität
zu bewerten. Saubere Windows-Installation, Freigabe und vollständige Produktabnahme
bleiben offen.

## Ausgeführte Prüfungen

- Aktueller Quellenstand mit Planer `event-balanced-local-v9`:
  `.venv/Scripts/python -m pytest -q` in `Memento`:
  **272 Tests bestanden in 51,56 Sekunden**. Ereignisbedeutung verwendet den
  stärksten geeigneten Moment statt des Durchschnitts aller Kandidaten.
  Ein unabhängiger synthetischer Referenzvergleich bei unverändertem 20s-Ziel
  behält beide vollständigen 10s-Schlüsselmomente trotz 99 zusätzlicher schwacher
  Geburtstagsaufnahmen; die vorherige Mittelwertregel verliert Referenzabdeckung.
  Zusätzliche Prüfungen decken schwache/überlappende Duplikatkandidaten,
  ausgeschlossene hohe Bewertungen und relative Nutzergewichte ab. KI-Cache
  bleibt unverändert; bestehende Projekte ändern sich erst bei Neuplanung.
  Ein einzelnes falsch hoch bewertetes Modellresultat kann Ereignisbedeutung
  weiterhin überschätzen. Reale Filmqualität und die vielfältigkeitsbezogene
  Zeitverteilung bleiben offen. `git diff --check` ohne Whitespacefehler;
  EXE nicht neu gebaut.

- Prüfung mit Renderprofil `hard-cut-h264-aac-v2`:
  `.venv/Scripts/python -m pytest -q` in `Memento`:
  **268 Tests bestanden in 47,48 Sekunden**. Der Renderer decodiert Bild und Ton
  normalisierter Abschnitte und des zusammengesetzten Films vor Veröffentlichung.
  Abschnittsprüfungen erlauben eine Bild-Rundungsabweichung; die Zusammenfügung
  muss die exakte Summe der decodierten Abschnittsbilder behalten. Tests belegen
  Zurückweisung einer zu kurzen Quelle trotz aufgefüllter Audiospur, Neuaufbau
  beschädigter Cachedateien bei gleicher Größe/mtime, Zurückweisung einer lesbaren
  aber unvollständigen Zusammenfügung, Wiederaufnahme intakter Teile und Bereinigung
  bei Abbruch der Prüfung. Schnitte mit 0,05 und 1,234 Sekunden prüfen zusätzlich
  explizite CFR-Ausgabebildrate und Quantisierung. Reale Farb-/Synchronitätsabnahme
  und lange Smartphone-Filme bleiben offen. Die Prüfung benötigt zusätzliche
  lokale Decodierzeit; ältere v1-Renderteile werden nicht wiederverwendet.
  `git diff --check` ohne Whitespacefehler. EXE nicht neu gebaut.

- Prüfung mit lokalem Analyseprofil v3:
  `.venv/Scripts/python -m pytest -q` in `Memento`:
  **262 Tests bestanden in 40,54 Sekunden**. Neue Prüfungen injizieren einen
  vorzeitigen Decoderabbruch beziehungsweise ein leeres Bild bei Sekunde 1,
  weisen die isolierte Fehlerbehandlung und anschließende Wiederaufnahme nach
  und vergleichen Originalbytes sowie gespeicherte KI-Antworten vor/nachher.
  Echte MJPEG-Testvideos decken die Dateiende-Toleranz von bis zu 0,5 Sekunden
  ab; injizierte ungültige Zeitstempel führen zu markierter Ersatzzeitbasis.
  Nicht endliche Dauern werden vor der Abtastung abgewiesen. Das Profil v3
  ersetzt beim nächsten lokalen Analysestart ältere lokale Ergebnisse, ohne
  den semantischen Cache oder bestehende Filmprojekte zu invalidieren.
  Dies ist keine vollständige Frameprüfung und keine reale Smartphone-Abnahme.
  `git diff --check` ohne Whitespacefehler; EXE nicht neu gebaut.

- Prüfung nach skalierter Zeitraumprüfung:
  `.venv/Scripts/python -m pytest -q` in `Memento`:
  **251 Tests bestanden in 40,00 Sekunden**. Die neue Zeitraumprüfung liest
  höchstens 200 Assets pro Desktop-Seite über eine Datenbankverbindung.
  Geprüft sind 20.000 gespeicherte Aufnahmen, Vor-/Zurücknavigation, erste/letzte
  Seite, stabile Sortierung bei gleicher Aufnahmezeit, Schrumpfen der Auswahl,
  identische Kopien, nicht erreichbare Standorte, unbekannte Zeitpunkte, inklusive
  Kalendergrenzen mit positiven/negativen UTC-Abständen und konsistente
  Seiten/Anzahlen trotz gleichzeitiger Datumskorrektur über eine zweite Verbindung.
  Zeichnen und Zellabrufe des Qt-Modells öffnen keine Datenbankverbindungen.
  Dialog mit geladenem Segoe-UI-Font und synthetischen Daten gerendert und visuell
  geprüft. Keine Medien decodiert oder übertragen; keine neue EXE gebaut.

- Prüfung nach dichter Ereignisbildung (Planner v8):
  `.venv/Scripts/python -m pytest -q` in `Memento`:
  **240 Tests bestanden in 37,80 Sekunden**, einschließlich 20.000 gespeicherter
  Assets, dichter Aktivitätswechsel, Schutz vor falschen Ereignisgrenzen und
  Filmplanung/Projektöffnung/Gewichtung mit unverändertem semantischem Cache.
  `git diff --check` ohne Whitespacefehler. Das vorhandene EXE-Paket wurde für
  diese Änderung nicht neu gebaut; frühere Paketprüfungen unten gelten für den
  dort beschriebenen älteren Stand.

- Memento: `.venv/Scripts/python -m pytest -q` im Ordner `Memento`:
  **156 Tests bestanden in 42,72 Sekunden**, einschließlich Qt-Offscreen-Workerablauf,
  Migrationen 1 → 7, 3 → 7, 4 → 7, 5 → 7 und 6 → 7,
  echter FFmpeg-Proxyerstellung, Planung, Schnittkorrektur, Projektrundlauf und Export.
- Wiederherstellung: bestätigte WAL-Daten, beschädigte Datenbank/Sidecars, unveränderte
  Originale/Projektdateien/gewählte Sicherung, ältere Schemas, Abbruch, voller Datenträger,
  unvollständige Schemas, exklusive Sperre, manipulierte Vorbereitung und beschädigte
  Aufträge. Ein echter Kindprozess endet direkt nach dem gespeicherten Auftrag;
  ein neuer Desktop-Prozess schließt ihn vor dem Öffnen der Bibliothek ab.
- Windows-Verzeichnispaket `dist/Memento/Memento.exe` tatsächlich gebaut mit
  PyInstaller 6.22.3 und Python 3.12.10. Der separate Offline-EXE-Funktionstest
  und die erneute Prüfung mit `--verify-existing` bestehen: ein Asset, vier lokale
  Messfenster, erfolgreicher Projektrundlauf, H.264/AAC-Film mit 2,02 Sekunden,
  gültiges Qt-Vorschaubild, erfolgreicher Sicherungs-/Wiederherstellungsrundlauf
  im Recovery-Dialog und bereinigter Test-Rundlauf im Windows-Vault. Der aktuelle
  EXE-Test korrigiert außerdem die Aufnahmezeit über den neuen Dialog und erzeugt
  aus demselben Cache einen Plan im korrigierten Zeitraum, während das zuvor
  gespeicherte Projekt unverändert bleibt.
  Die semantische Antwort ist dabei eine Fixture; kein Gemini-Zugang wird verwendet.
- `build-info.json` verbindet Quellprüfsumme und EXE-Prüfsumme. Der Prüfbefehl
  lehnt ein Paket ab, das nicht zum aktuellen Quellstand oder seiner EXE-Prüfsumme
  passt. Laufzeitversionen, gefundene Lizenzdateien und FFmpeg-Konfiguration liegen
  im Paket; die tatsächliche FFmpeg-Lizenzanzeige lautet GPLv3 oder später.
- Metadaten: echte erzeugte MOV-Datei mit QuickTime-Datum, EXIF-Offsetformen,
  ungültige bevorzugte Tags/Offsets, Datum ohne Uhrzeit, Stream-/Container-Vorrang,
  Coverbild-Ausschluss bei FFprobe und stufenweise Aktualisierung bei unverändertem
  Hash sowie erhaltenem semantischem Cache.
- Manuelle Aufnahmezeiten: zuvor unbekannte Daten, explizite und unbekannte
  Zeitzonen, ungültige Offsets, Suche mit Umlauten und wörtlichen Platzhalterzeichen,
  Seitenabfragen, Alias-IDs, bestätigte erneute Inhaltsprüfung und identische Kopien.
  Eine Korrektur verschiebt vorhandene Highlights ohne neue KI-Anfrage in den neuen
  Zeitraum; Originaldatei, Rohwert, Segmentkennung und gespeicherter Filmplan bleiben erhalten.
  Der neue Dialog wurde mit synthetischen Daten gerendert und visuell geprüft.
- Zusätzliche gezielte Prüfungen: Schärfe/Belichtung, Schwenk gegen alternierende
  Kamerabewegung, Bildfolgenähnlichkeit, Überlappungsgewichtung, atomarer Rollback,
  unveränderte Originale und semantische Ergebnisse, Migrationssicherung mit WAL,
  manuelle Schnittgrenzen, Versionsinvalidierung und begrenztes Laden der Messwerte.
- Inhaltsidentität: Kopien/Umbenennungen, getrennte geänderte Inhalte, Altcache-
  Übernahme und ID-Stabilität, Zusammenführung alter lokaler/KI-Analysen,
  Abbruch/Wiederaufnahme, gleiche Größe/Zeit bei anderem Inhalt, Aufnahmezeit-
  Priorität und echte Wiederverknüpfung mit anschließendem FFmpeg-Export.
- 20.000 gespeicherte Assets: Planung deckt alle 28 erkannten Tagesereignisse ab,
  verwendet höchstens drei Datenbankverbindungen und hält die gewünschte maximale
  Filmlänge ein. Dies prüft Bibliothek und Planung, keine reale Decodierlast.
- Zusätzliche Auswahlregressionen prüfen überlappende manuelle Bereiche,
  frei werdende Ereignisbudgets, unveränderte semantische Caches und zu wenig
  einzigartiges Material. Auch nach Umverteilung werden keine Quellbereiche wiederholt.
- Analyseabschnitte: aktuelle statt veralteter Schnittgrenzen, erhaltene bezahlte
  Teilabdeckung und leere Antworten, Neustart ohne neue Anfragen, historische
  Überlappungen sowie 200 reproduzierbare Aufteilungen mit vollständiger,
  disjunkter Abdeckung und unveränderter nominaler Anfragezahl. Ein echtes
  60-Sekunden-Proxyvideo behält AAC-Ton, entfernt private Metadaten und bleibt
  innerhalb der Größenbegrenzung.
- FFmpeg-Integration prüft Dauer, Reihenfolge anhand der Bildfarben, Seitenverhältnis,
  erhaltenen Ton anhand PCM-Samples, Stille für tonlose Quellen, Abbruch/Wiederaufnahme,
  geänderte Quellen, Fehlerbereinigung und konkurrierend angelegte Zieldateien.
- Qt-Offscreen-Integration: aus Cache planen, trimmen, umordnen, Projekt wieder öffnen
  und wirklich exportieren; semantische Cacheeinträge bleiben dabei unverändert.
- Prototyp: `../Memento/.venv/Scripts/python -m pytest -q` im Ordner `Prototype`:
  23 Tests bestanden.
- Analysedialog mit synthetischer Auswahl und geladenem Segoe-UI-Font im
  Qt-Offscreen-Modus gerendert und visuell geprüft; dabei kein Upload.
- Filmplan-Dialog mit Ereignissen und Quellbereichen ebenfalls gerendert und
  visuell geprüft; fehlender Kontrast der neuen Dezimalfelder anschließend behoben.
- `git diff --check`: keine Whitespacefehler.
