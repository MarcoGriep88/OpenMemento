---
title: "Daten & Privatsphäre"
description: "Was lokal bleibt, was Gemini erhält und wo deine Zugangsdaten gespeichert werden."
slug: "datenschutz"
weight: 80
group: "reference"
---

## Was auf deinem Computer passiert

Medienerfassung, Metadaten, lokale OpenCV-Analyse, Filmplanung und FFmpeg-Export laufen auf deinem Computer. Originale bleiben an ihren Speicherorten und werden nicht verändert. Medienindex und Analyseergebnisse liegen in der lokalen Bibliothek.

Unter Windows verwendet der aktuelle Projektablauf standardmäßig `%LOCALAPPDATA%\Memento_v2`. Ein mit `MEMENTO_DATA_DIR` gewähltes Verzeichnis hat Vorrang. Bestehende und ältere Bibliotheken sowie Linux können andere Speicherorte verwenden; nutze den in deiner Anwendung angezeigten Bibliothekspfad.

## Was an Google geht

Nach deiner ausdrücklichen Freigabe sendet die Gemini-Analyse ausgewählte, lokal verkleinerte Videoabschnitte mit Ton direkt an Google. Verkleinerte Dateien können weiterhin private Bild- und Toninhalte enthalten. Der vollständige Arbeitsablauf mit Gemini ist daher nicht offline.

Die Bedingungen deines Google-Zugangs bestimmen den Umgang mit den dort verarbeiteten Daten. Prüfe sie, bevor du privates Familienmaterial freigibst. OpenMemento verspricht weder eine pauschale Nicht-Speicherung bei Google noch eine Verarbeitung ohne weitere Anbieterbedingungen.

## API-Schlüssel

Dein Gemini-Schlüssel wird über den unterstützten sicheren Betriebssystem-Speicher verwaltet. Er gehört nicht in Projektdateien, Screenshots oder öffentliche Fehlerberichte. In den Einstellungen kannst du den gespeicherten Schlüssel löschen.

## Website und Unterstützung

Die Hilfe-Suche lädt ihren Index von dieser Website und durchsucht ihn im Browser. Sie verwendet keinen externen Suchdienst. Der Ko-fi-Link öffnet ein externes Unterstützungsangebot; ein Ko-fi-Widget wird hier nicht eingebettet.

Weitere Angaben findest du in der [Datenschutzerklärung](/de/datenschutz/).
