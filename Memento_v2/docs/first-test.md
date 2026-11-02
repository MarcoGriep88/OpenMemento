# Erster praktischer Test

Starte `Memento.exe` aus dem vollständigen Ordner `dist/Memento`.
Der Ordner `_internal` und die übrigen Paketdateien müssen dabei bleiben.
Die Tests unten benötigen keine Entwicklungsumgebung. Der bisherige technische
Nachweis verwendet synthetische Videos; die Qualität echter Familienfilme ist
noch nicht abgenommen.

## Material und Erwartungen

Wähle zunächst etwa 20–50 Aufnahmen aus mindestens zwei unterschiedlichen
Aktivitäten, zum Beispiel Geburtstag und Ausflug. Notiere **vor** der automatischen
Auswahl drei bis fünf Momente, die unbedingt im Film vorkommen sollten:

| Datei | Ungefährer Bereich | Warum wichtig? |
| --- | --- | --- |
| | | |
| | | |
| | | |

Die automatische Auswahl soll diese Erwartungen nicht nachträglich vorgeben.
Für systematische Vergleiche beschreibt [evaluation.md](evaluation.md) das
lokale Referenzformat und die Auswertung gespeicherter Filmpläne.

## Lokal beginnen

1. „Ordner hinzufügen“ → „Alle Ordner indexieren“.
2. Während eines ausreichend langen Imports abbrechen und über „Fortsetzen“
   weiterarbeiten. Bereits erfasste Aufnahmen sollten erhalten bleiben.
3. „Alle Videos lokal analysieren“ ausführen. Fehler einzelner Videos unter
   „Fehler anzeigen“ prüfen; andere Videos sollten weiterverarbeitet werden.
4. Zeitraum einstellen und „Aufnahmen finden“ öffnen. Datum, Quelle,
   Zeitzonenunsicherheit und Dateiname prüfen. Bei mehr als 200 Treffern blättern.
5. Bei falschen oder fehlenden Daten „Aufnahmezeiten prüfen“ verwenden und den
   Zeitraum anschließend erneut suchen.

Diese Schritte übertragen keine Medien an Gemini. Aufnahmezeitkorrekturen
ändern den lokalen Index, nicht die Originaldateien.

## Einen ersten Film beurteilen

1. In „Einstellungen“ den eigenen Gemini-Schlüssel hinterlegen.
2. „Erinnerungen analysieren“ öffnen, ausgewählte Bereiche und Übertragungsmenge
   prüfen und ein kleines Anfragelimit wählen. Erst „An Google senden“ überträgt
   temporäre Videoabschnitte mit Ton direkt an Google und kann API-Kosten auslösen.
3. Nach erfolgreicher Analyse zum Beispiel 60 Sekunden Zielzeit einstellen:
   „Film erstellen“ → „Auswahl erzeugen / neu planen“.
4. „Ereignisse und Zeitverteilung“ und die vorgeschlagenen Momente prüfen.
   Den gesamten Film als Vorschau ansehen und mit den zuvor notierten Erwartungen
   vergleichen. Noch keine manuellen Korrekturen vornehmen, wenn der erste Schnitt
   unabhängig bewertet werden soll.
5. Fehlende oder störende Momente notieren. Danach Ein-/Ausschlüsse, Schnittgrenzen
   und Ereignisgewichte ausprobieren; über „Neu planen“ anwenden. Rückgängig und
   Wiederholen prüfen.
6. Eine andere Zielzeit aus derselben Analyse erzeugen. Dafür ist keine erneute
   Gemini-Analyse erforderlich.
7. Als neue MP4-Datei exportieren und in einem externen Player vollständig ansehen
   und anhören. Bildreihenfolge, Schnittstellen, Hochformat und Originalton prüfen.
8. Filmprojekt schließen und erneut öffnen; Auswahl und eigene Korrekturen sollten
   erhalten sein. Die Undo-Historie gilt nur innerhalb der Bearbeitungssitzung.

## Ergebnis lokal festhalten

- Material: Anzahl, Gesamtdauer, Geräte/Formate, ungefährer Zeitraum.
- Modell und Zielzeit; falls relevant, Aufnahmezeitkorrekturen.
- Welche erwarteten Momente fehlen? Datei und Quellzeit angeben.
- Welche Szenen sind redundant, zu lang oder unpassend?
- Wo wird eine Handlung oder Sprache ungünstig abgeschnitten?
- Wie viel Nacharbeit war nötig? Welche konkreten Änderungen haben geholfen?
- Gab es Export-, Vorschau- oder Tonfehler? Aktion und Fehlermeldung notieren.

Ein technisch erfolgreicher Export allein ist keine Qualitätsabnahme.
Private Aufnahmen und Notizen können für diesen Test vollständig lokal bleiben;
nur ausdrücklich gestartete Gemini-Analysebereiche werden an Google übertragen.
