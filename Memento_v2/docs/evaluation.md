# Auswahlqualität lokal vergleichen

Die Auswertung vergleicht einen gespeicherten Filmplan mit unabhängig markierten
Schlüsselmomenten. Sie öffnet keine Videos, ruft keine KI auf und ändert weder
Bibliothek noch Filmprojekt. Das Ergebnis ist eine Messung der Quellzeitabdeckung,
keine automatische Bewertung von Erzählfluss, emotionaler Wirkung oder Tonqualität.

## Referenz vor dem Vergleich festlegen

1. Eine lokal nutzbare Sammlung und einen festen Zeitraum wählen.
2. Zielzeit und gewünschte Schlüsselmomente **vor** dem Vergleich festhalten.
   Auch wichtige, vom Plan ausgelassene Dateien berücksichtigen. Eine Referenz
   ausschließlich aus der automatischen Auswahl würde deren Fehler übernehmen.
3. Ereignisse frei benennen. Jeder Moment bekommt eine eindeutige Kennung,
   Beschreibung, ein Gewicht zwischen 0,001 und 1000 sowie mindestens einen
   Quellbereich. Start und Ende beziehen sich auf das Originalvideo in Sekunden.
4. Mehrere Kameras desselben Moments als `alternatives` eines Moments angeben.
   Jede Alternative muss den vollständigen gemeinten Moment repräsentieren.
   Die Auswertung nimmt die höchste Abdeckung einer Alternative; Teilstücke
   verschiedener Kameras werden ohne gemeinsame Ereigniszeitbasis nicht addiert.
5. Dieselbe Referenz, Zielzeit und Mindestabdeckung für alle Varianten verwenden.
   Für Urlaub, Geburtstag und Alltag getrennte Referenzen aufbauen. Ergebnisse
   mit menschlichem Ansehen und Anhören der tatsächlichen Filme ergänzen.

## Referenzformat 1

```json
{
  "format_version": 1,
  "reference_id": "urlaub-referenz-1",
  "request": {
    "date_from": "2026-07-12",
    "date_to": "2026-07-26",
    "target_seconds": 720
  },
  "sources": [
    {
      "source_id": "strandaufnahme",
      "asset_id": "KENNUNG_AUS_DEM_MEDIENINDEX",
      "content_sha256": null,
      "size_bytes": 123456,
      "modified_at": "2026-07-12T10:00:00.000000+02:00",
      "duration_seconds": 90
    }
  ],
  "moments": [
    {
      "moment_id": "erstes-schwimmen",
      "description": "Erster gemeinsamer Sprung ins Wasser und Reaktion",
      "event": "Strandtag",
      "weight": 3,
      "alternatives": [
        {"source_id": "strandaufnahme", "start_seconds": 18, "end_seconds": 30}
      ]
    }
  ]
}
```

Das Beispiel enthält Platzhalter für den Quellstand. `asset_id`, Dateigröße,
Änderungszeit und Dauer müssen aus dem Index beziehungsweise dem gespeicherten
Quellstand stammen. Wenn vorhanden, `content_sha256` aus dem Index übernehmen.
Dann werden identische Inhalte auch unter anderen Medienkennungen zugeordnet.
Ohne Hash passen nur Kennung, Größe und Änderungszeit des gespeicherten Stands;
der Bericht kennzeichnet diese schwächere Zuordnung. Aktuelle Dateiinhalte werden
bei der Auswertung nicht erneut geprüft. Ein unbekannter oder anderer Inhalt
erhält keine Abdeckung nur wegen ähnlicher Namen.

Für ein Quellenverzeichnis **aller** indexierten Aufnahmen im Zeitraum kann die
bestehende Bibliotheks-API verwendet werden, unabhängig von der automatischen
Auswahl. Folgendes Entwicklungsbeispiel erstellt eine Referenzvorlage ohne
Momente; menschliche Markierungen müssen anschließend ergänzt werden:

```python
import json
from datetime import date
from pathlib import Path
from memento.library.database import MediaLibrary, default_database_path

library = MediaLibrary(default_database_path())
start, end = date(2026, 7, 12), date(2026, 7, 26)
assets = library.list_assets_in_capture_date_range(start, end)
sources = []
for asset in assets:
    if asset.duration_seconds is None or asset.duration_seconds <= 0:
        print("Dauer zuerst prüfen:", asset.asset_id, asset.path)
        continue
    sources.append({
        "source_id": asset.asset_id, "asset_id": asset.asset_id,
        "content_sha256": asset.content_sha256,
        "size_bytes": asset.size_bytes,
        "modified_at": asset.modified_at.isoformat(timespec="microseconds"),
        "duration_seconds": asset.duration_seconds,
    })
    print(asset.asset_id, asset.path)  # Nur lokale Zuordnung für die Annotation.
template = {
    "format_version": 1, "reference_id": "urlaub-referenz-1",
    "request": {"date_from": start.isoformat(), "date_to": end.isoformat(), "target_seconds": 720},
    "sources": sources, "moments": [],
}
with Path("reference.json").open("x", encoding="utf-8") as stream:
    json.dump(template, stream, ensure_ascii=False, indent=2, allow_nan=False)
```

Die direkte Bibliotheks-API gehört zum Entwicklungsworkflow; wie bei anderen
direkten API-Zugriffen darf dabei kein paralleler Medienauftrag schreiben.
Das Vergleichswerkzeug selbst benötigt nur die fertige Referenz und den Filmplan.
Leere Referenzen, doppelte IDs oder JSON-Felder, unbekannte Felder, nicht endliche
Werte und ungültige Quellgrenzen werden zurückgewiesen.

## Vergleich starten

Im Ordner `Memento`:

```powershell
.venv\Scripts\python -m memento.evaluate film.memento.json reference.json --output bericht.json
```

Ohne `--output` erscheint der JSON-Bericht im Terminal. Vorhandene Berichte und
andere Dateien werden nicht überschrieben. Quellpfade werden für den Vergleich
nicht benötigt; frei gewählte Beschreibungen, Kennungen und Ereignisnamen können
dennoch private Inhalte verraten.

`--retained-fraction 0.8` ist die Voreinstellung: Ein Moment zählt ab 80 Prozent
Abdeckung einer seiner Alternativen als erhalten. Diese Schwelle ist eine
konfigurierbare Vergleichsregel und kein Nachweis, dass die entscheidende Handlung
oder der wichtigste Satz tatsächlich im Film verbleibt.

## Bericht interpretieren

| Feld | Bedeutung |
| --- | --- |
| `weighted_moment_coverage` | Gewichteter Mittelwert der kontinuierlichen Abdeckung von 0 bis 1. |
| `weighted_moment_recall` | Anteil des Referenzgewichts, dessen Moment die Mindestabdeckung erreicht. |
| `event_coverage` | Anteil menschlich benannter Ereignisse mit mindestens einem erhaltenen Schlüsselmoment. |
| `moments` | Abdeckung und Erhalt je Moment; `best_alternative` ist ein nullbasierter Index oder `null` ohne Abdeckung. |
| `missing_events` | Ereignisse ohne ausreichend erhaltenen Referenzmoment. |
| `annotated_unique_seconds` | Eindeutige ausgewählte Quellzeit innerhalb der Vereinigungsmenge aller Referenzbereiche. |
| `annotated_unique_fraction_of_output` | Dieser Quellzeitanteil an der geplanten Laufzeit; bei leerem Film `null`. |
| `exact_repeated_source_seconds` | Mehrfach verwendete Quellzeit derselben gespeicherten Inhaltsidentität. Kein visueller Redundanztest. |
| `duration_seconds`, `target_difference_seconds` | Geplante Ausgabezeit und Abweichung zur vereinbarten Zielzeit, keine Messung eines Renderergebnisses. |
| `reference_sha256`, `timeline_sha256` | Prüfsummen der Referenz und ausgewählten Quellstände/-bereiche zur Zuordnung von Vergleichsläufen. |
| `notes` | Fehlende aktive Quellen und Referenzquellen ohne Inhaltsnachweis. |

Nicht annotierte Szenen sind nicht automatisch schlecht. Die Referenz kann
unvollständig sein, und unterschiedliche Perspektiven können erzählerisch sinnvoll
sein. Deshalb ist der annotierte Anteil keine Präzisions- oder Qualitätsnote.
Überlappende Markierungen zählen bei der Quellzeitmessung nur einmal; verschiedene
Referenzmomente behalten ihre vom Menschen vergebenen Gewichte. Doppelte
Beschreibungen desselben Moments sollten daher vor dem Vergleich bereinigt werden.

Die Tests verwenden synthetische Pläne und explizite Referenzbereiche. Reale
menschliche Annotationen und die qualitative Abnahme der Familienfilme stehen aus.
