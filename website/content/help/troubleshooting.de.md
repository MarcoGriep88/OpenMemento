---
title: "Fehlerbehebung & häufige Fragen"
description: "Fehlende Videos, falsche Daten, Gemini-Probleme und zu kurze Filme gezielt prüfen."
slug: "fehlerbehebung"
weight: 100
group: "reference"
---

## Meine Videos fehlen

Prüfe, ob der richtige Ordner zum aktuellen Projekt gehört, das Laufwerk verbunden ist und die Dateiendung unterstützt wird. Nutze **Erreichbarkeit prüfen** und indexiere danach erneut. Wenn ein Zeitraum aktiv ist, können falsche Aufnahmedaten Clips aus dem sichtbaren Bereich ausschließen.

## Die Reihenfolge oder das Datum stimmt nicht

Prüfe die Aufnahmezeit im Index. Dateikopien und fehlende Metadaten können zu unsicheren Zeitangaben führen. Korrigiere sie über **Aufnahmezeiten prüfen** und erzeuge anschließend die Auswahl erneut.

## Mein Gemini-Schlüssel lässt sich nicht speichern

Lies die Meldung zum Betriebssystem-Schlüsselspeicher. Unter Linux muss ein unterstützter sicherer Speicher in deiner Desktop-Sitzung laufen und entsperrt sein. Ein unsicheres Datei-Backend ist kein Ersatz. Lokale Funktionen lassen sich auch ohne gespeicherten API-Schlüssel nutzen.

## Gemini meldet einen Fehler

Kontrolliere Internetverbindung, Modellzugriff und Kontingent deines Google-Kontos. Beachte die konkrete Meldung statt wiederholt einen kompletten Auftrag neu zu starten. Erfolgreiche Ergebnisse bleiben gespeichert; setze fehlende Analysen über die angebotene Fortsetzung fort.

## Muss ich für jeden Film neu analysieren?

Nein. Analyse und Filmplanung sind getrennt. Gespeicherte passende Ergebnisse werden für neue Zeiträume und Filmlängen wiederverwendet. Geänderte Prompts, Modelle oder Analyseversionen können dagegen neue Analysen erfordern.

## Der Film ist kürzer als gewünscht

Die Zielzeit ist keine Garantie. Prüfe Zeitraum, Ausschlüsse und verfügbares Material. Auch eine Quelle, die früher endet als ihre Metadaten erwarten lassen, kann den Export verkürzen. Erweitere den Zeitraum oder ändere die Auswahl, wenn du mehr passende Momente hast.

## Vorschau oder Export funktioniert nicht

Verbinde die Quelllaufwerke und prüfe, ob die Dateien noch an ihren gespeicherten Pfaden liegen. Kontrolliere Schreibrechte und freien Speicher am Ausgabeort. Teste eine kleinere Auswahl, um einen problematischen Clip einzugrenzen.

## Wie melde ich ein Problem?

Eröffne ein [GitHub-Issue](https://github.com/MarcoGriep88/OpenMemento/issues) mit Betriebssystem, verwendeter Version, Arbeitsschritt und genauer Fehlermeldung. Beschreibe, wie sich der Fehler nachvollziehen lässt. Entferne API-Schlüssel und private Pfade aus dem Bericht und hänge keine privaten Familienvideos an.
