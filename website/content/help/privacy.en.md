---
title: "Data & privacy"
description: "Understand what stays local, what Gemini receives and where credentials are stored."
slug: "privacy"
weight: 80
group: "reference"
---

## What happens on your computer

Discovery, metadata extraction, local OpenCV analysis, movie planning and FFmpeg export run on your computer. Original files stay in place and are not modified. The media index and analysis results are stored in the local library.

On Windows, the current project workflow defaults to `%LOCALAPPDATA%\Memento_v2`. `MEMENTO_DATA_DIR` overrides the data location. Existing or older libraries and Linux can use different locations; check the library path displayed in your application.

## What is sent to Google

After your explicit approval, Gemini analysis sends selected, locally reduced video sections with audio directly to Google. Reduced files can still contain private images and sound. The complete workflow with Gemini is therefore not offline.

The terms applicable to your Google access govern how Google handles processed data. Review them before approving private family footage. OpenMemento does not promise that Google never stores data or that processing has no further provider conditions.

## API keys

Your Gemini key is managed through a supported secure operating system credential store. Do not put it in project files, screenshots or public bug reports. You can remove the stored key in settings.

## Website and support

Help search loads its index from this website and searches it in your browser. It uses no external search service. The Ko-fi link opens an external support service; no Ko-fi widget is embedded here.

See the [privacy notice](/en/privacy/) for further information.
