---
title: "Vorschau & Export"
description: "Quellen prüfen und den fertigen Film mit FFmpeg lokal als MP4 rendern."
slug: "export"
weight: 70
group: "workflow"
---

## Vor dem Export

Prüfe im Filmplan die Auswahl, Segmentgrenzen und den Ton. Verbinde alle benötigten Laufwerke. Auch nach abgeschlossener Analyse braucht der Renderer die Originalquellen; die Bibliothek ersetzt keine Videodateien.

Mit **Gesamten Film als Vorschau ansehen** kontrollierst du den geplanten Ablauf. Wenn eine Vorschau nicht abgespielt werden kann, prüfe Quelle und Codec sowie die angezeigte Fehlermeldung.

## Eine MP4-Datei erstellen

Klicke auf **Film lokal als MP4 exportieren** und wähle eine neue Datei außerhalb deiner Originalaufnahmen. Die Verarbeitung läuft mit FFmpeg auf deinem Computer. Für den Export selbst werden keine Aufnahmen an einen Cloud-Renderer übertragen.

Lass genügend freien Speicherplatz für Ausgabedatei und temporäre Verarbeitung. Der Fortschritt und ein kontrollierter Abbruch sind im Auftragsbereich sichtbar. Ein abgebrochener oder fehlgeschlagener Export ist noch kein fertiger Film.

## Den fertigen Film ansehen

Öffne das Ergebnis über **Exportierten Film öffnen** beziehungsweise im Dashboard. Prüfe Bild, Ton, Orientierung und Übergänge. Die tatsächliche Länge kann von der Zielzeit abweichen, wenn geeignetes oder lesbares Material fehlt.

## Wenn der Export scheitert

Kontrolliere die Erreichbarkeit jeder Quelle, Schreibrechte und freien Speicher am Ziel. Eine beschädigte oder nicht vollständig decodierbare Datei kann die verfügbare Filmlänge verkürzen. Behalte die konkrete Fehlermeldung für die [Fehlerbehebung](../fehlerbehebung/).
