---
title: "Preview & export"
description: "Check your sources and render the finished movie locally as MP4 with FFmpeg."
slug: "export"
weight: 70
group: "workflow"
---

## Before exporting

Check the selection, segment boundaries and audio in the movie plan. Connect every required drive. Rendering still needs the original sources after analysis; the library does not replace video files.

Use **Preview entire movie** to check the planned sequence. If a preview cannot play, check its source and codec and read the error message.

## Create an MP4 file

Choose **Export movie locally as MP4** and select a new output file outside your original recordings. FFmpeg processes it on your computer. Export itself does not send recordings to a cloud renderer.

Allow enough free space for the output and temporary processing. The job area shows progress and controlled cancellation. An interrupted or failed export is not a finished movie.

## Watch the finished movie

Open the result with **Open exported movie** or from the dashboard. Check picture, audio, orientation and transitions. Actual duration can differ from the target if suitable or readable footage is missing.

## If export fails

Check that every source is reachable and the output location is writable with sufficient free space. Damaged or partially decodable footage can shorten the available movie. Keep the specific error message for [troubleshooting](../troubleshooting/).
