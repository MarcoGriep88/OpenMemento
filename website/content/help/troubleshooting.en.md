---
title: "Troubleshooting & common questions"
description: "Investigate missing clips, incorrect dates, Gemini failures and shorter-than-expected movies."
slug: "troubleshooting"
weight: 100
group: "reference"
---

## My videos are missing

Check that the folder belongs to your current project, the drive is connected and the file extension is supported. Use **Check availability**, then reindex. If a date filter is enabled, incorrect recording dates can exclude clips from the visible range.

## Dates or chronological order are wrong

Check recording times in the index. Copied files and missing metadata can produce uncertain dates. Correct them using **Check recording times**, then regenerate the selection.

## My Gemini key will not save

Read the operating system credential store message. On Linux, a supported secure store must be running and unlocked in your desktop session. An insecure file backend is not a substitute. Local features remain usable without a stored API key.

## Gemini reports an error

Check your internet connection, model access and Google account quota. Use the specific error message rather than repeatedly restarting a complete job. Successful results remain saved; use the available resume option for missing analyses.

## Do I need to analyze again for every movie?

No. Analysis and movie planning are separate. Suitable saved results are reused for new date ranges and target durations. Changed prompts, models or analysis versions can require new analyses.

## The movie is shorter than requested

Target duration is not a guarantee. Check the range, exclusions and available footage. A source that ends before its metadata suggests can also shorten the export. Expand the range or adjust selection if more suitable moments are available.

## Preview or export fails

Reconnect source drives and check that files still exist at their stored paths. Verify write permissions and free space at the output location. Try a smaller selection to isolate a problematic clip.

## How do I report a problem?

Open a [GitHub issue](https://github.com/MarcoGriep88/OpenMemento/issues) with your operating system, application version, workflow step and exact error message. Explain how to reproduce it. Remove API keys and private paths, and do not attach private family videos.
