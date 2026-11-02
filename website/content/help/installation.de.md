---
title: "Installation & Sprache"
description: "OpenMemento unter Windows oder Linux starten und die Sprache der Oberfläche ändern."
slug: "installation"
weight: 20
group: "start"
---

## Windows-Installer

Wenn du ein gebautes Windows-Paket erhalten hast, starte **OpenMemento-Setup**. Der Installer richtet OpenMemento für dein Benutzerkonto ein; Administratorrechte sind dafür nicht vorgesehen. Eine Desktop-Verknüpfung ist optional. Schließe die Anwendung vor einem Update.

Das Setup ist ein Entwicklungsbuild und derzeit nicht digital signiert. Die Verfügbarkeit öffentlicher Pakete findest du im [GitHub-Projekt](https://github.com/MarcoGriep88/OpenMemento). Diese Hilfe verspricht keine bereits veröffentlichte stabile Version.

## Portables Windows-Paket

Verwende den vollständigen Programmordner und starte **OpenMemento.exe**. Der Unterordner `_internal` gehört zur Anwendung und muss mitkopiert werden. Für das gebaute Paket ist keine separate Python-Installation nötig.

## Start aus dem Quellcode

Für Entwicklung werden **Python 3.12** und die Abhängigkeiten aus `OpenMemento/pyproject.toml` benötigt. Die Schritte für Windows und Linux stehen in der [Projekt-README](https://github.com/MarcoGriep88/OpenMemento#getting-started). Unter Linux ist für das Speichern des Gemini-Schlüssels zusätzlich ein entsperrter, unterstützter Betriebssystem-Schlüsselspeicher nötig.

## Sprache ändern

Öffne **Gemini-Einstellungen** und wähle unter **Sprache / Language** Deutsch oder Englisch. Speichere und starte OpenMemento neu. Laufende Aufträge werden durch das Speichern der Sprachwahl nicht unterbrochen.

Projektnamen, eigene Prompts und bereits gespeicherte KI-Beschreibungen werden nicht nachträglich übersetzt. Die Sprachwahl startet keine neue KI-Analyse.

## Update und Deinstallation

Updates und Deinstallation erhalten den lokalen Medienindex, Projekte und Zugangsdaten. Die Deinstallation entfernt die mitgelieferten Programmdateien. Sichere deine Aufnahmen und wichtigen Projektdaten trotzdem unabhängig von der Anwendung.
