---
title: "Installation & language"
description: "Start OpenMemento on Windows or Linux and change the interface language."
slug: "installation"
weight: 20
group: "start"
---

## Windows installer

If you have received a built Windows package, run **OpenMemento-Setup**. It installs the app for your user account without requesting administrator privileges. A desktop shortcut is optional. Close the application before updating.

The installer is a development build and is currently unsigned. Check the [GitHub project](https://github.com/MarcoGriep88/OpenMemento) for public package availability. This guide does not imply that a stable release has been published.

## Portable Windows package

Keep the entire application folder and launch **OpenMemento.exe**. Its `_internal` subfolder is required and must be copied with it. Built packages do not require a separate Python installation.

## Run from source

Development requires **Python 3.12** and the dependencies in `OpenMemento/pyproject.toml`. See the [project README](https://github.com/MarcoGriep88/OpenMemento#getting-started) for Windows and Linux instructions. Saving a Gemini key on Linux additionally requires an unlocked, supported operating system credential store.

## Change language

Open **Gemini settings**, choose German or English under **Sprache / Language**, save and restart OpenMemento. Saving the language preference does not interrupt running jobs.

Project names, custom prompts and previously saved AI descriptions retain their original language. Changing the interface language does not start another AI analysis.

## Updates and uninstalling

Updates and uninstalling preserve the local media index, projects and credentials. Uninstalling removes the files distributed with the program. Still maintain independent backups of your recordings and important project data.
