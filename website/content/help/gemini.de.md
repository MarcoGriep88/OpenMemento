---
title: "Gemini & KI-Kosten"
description: "Den eigenen API-Schlüssel hinterlegen und bewusst entscheiden, welches Material Google analysiert."
slug: "gemini"
weight: 40
group: "workflow"
---

## Deinen API-Schlüssel einrichten

Öffne **Gemini-Einstellungen**. Erstelle einen Schlüssel in [Google AI Studio](https://aistudio.google.com/app/apikey), füge ihn in das Passwortfeld ein und speichere ihn. Verwende ein Modell, auf das dein Google-Konto tatsächlich Zugriff hat.

OpenMemento speichert den Schlüssel über den unterstützten Betriebssystem-Schlüsselspeicher. Bei einer Fehlermeldung zum sicheren Speicher muss zuerst dieser Zugriff funktionieren. Unter Linux muss der Schlüsselspeicher in derselben Desktop-Sitzung entsperrt sein.

## Lokale Analyse zuerst

Starte die OpenCV-Analyse, bevor du **Gemini-Analyse vorbereiten** öffnest. OpenCV erkennt lokal unter anderem Shots, Bewegung und technische Eigenschaften. Gemini ergänzt das Verständnis von Handlung und Ton innerhalb der Videos.

## Umfang prüfen und freigeben

Der Analysedialog zeigt den vorgesehenen Umfang und die Übertragung an Google. Lies die Angaben, bevor du **An Google senden** auswählst. Übertragen werden ausgewählte, lokal verkleinerte Videoabschnitte mit Ton; auch diese können private Personen, Gespräche und Orte enthalten.

## Ergebnisse und Kosten

Dein Google-Konto trägt die Kosten der API-Nutzung. Die Anzeigen der Anwendung helfen bei der Einschätzung des Umfangs; sie ersetzen keine Abrechnung oder verbindliche Preisangabe von Google.

Erfolgreiche Antworten werden lokal gespeichert. Ein anderer Filmzeitraum oder eine neue Ziellänge verlangt für sich genommen keine neue KI-Analyse. Ein geänderter Analyseprompt, ein anderes Modell oder eine neue Analyseversion kann dagegen eigene Ergebnisse erfordern. Prüfe den Umfang erneut, bevor du einen weiteren Auftrag freigibst.

## Unterbrechungen und Fehler

Bei Verbindungsfehlern, Kontingentgrenzen oder einem nicht verfügbaren Modell prüfst du die angezeigte Meldung und deinen Google-Zugang. Nutze die Fortsetzungsfunktion für noch fehlende Analysen. Gib deinen API-Schlüssel niemals in öffentlichen Fehlerberichten an.
