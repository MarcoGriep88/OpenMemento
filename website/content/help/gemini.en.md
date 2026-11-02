---
title: "Gemini & AI costs"
description: "Store your own API key and make an informed choice about the footage Google analyzes."
slug: "gemini"
weight: 40
group: "workflow"
---

## Set up your API key

Open **Gemini settings**. Create a key in [Google AI Studio](https://aistudio.google.com/app/apikey), paste it into the password field and save. Select a model your Google account can actually access.

OpenMemento stores the key using a supported operating system credential store. If secure storage reports an error, resolve that access first. On Linux, the credential store must be unlocked in the same desktop session.

## Run local analysis first

Run OpenCV analysis before opening **Prepare Gemini analysis**. OpenCV detects shots, motion and technical properties locally. Gemini adds understanding of action and audio within the videos.

## Review and approve the scope

The analysis dialog describes the planned scope and transfer to Google. Read it before selecting **Send to Google**. Selected video sections are reduced locally and sent with audio; these can still contain private people, conversations and locations.

## Results and costs

API usage is billed to your Google account. The app's volume information helps you assess the scope; it is not a bill or a binding Google price quotation.

Successful responses are stored locally. Changing only the movie date range or target duration does not require another AI analysis. Changing an analysis prompt, model or analysis version can require separate results. Review the scope again before approving another job.

## Interruptions and errors

For connection failures, quota limits or unavailable models, check the displayed message and your Google access. Use the resume option to process missing analyses. Never include your API key in a public bug report.
