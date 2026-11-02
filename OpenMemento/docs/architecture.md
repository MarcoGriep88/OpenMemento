## OpenMemento presentation and compatibility

The desktop project now lives in `OpenMemento/`, uses a white-and-mint theme
from `memento.ui.theme`, and builds as `OpenMemento.exe`. The Python distribution
is `openmemento-family-video-editor`; both `openmemento` and the existing
`memento` command start the same application. The Python module stays `memento`.
The existing `Memento_v2` data directory, Qt organization/application IDs and
secure-store service name intentionally remain stable. No data is moved and
existing credentials are neither copied nor read during the rename.
Application screenshots for the bilingual website are generated from isolated
sample projects by `scripts/capture_website.py`, without media or AI access.

# Memento architecture

## Interface localization

`memento.i18n` provides German source strings and an English JSON catalogue,
plus diagnostic catalogues for messages originating in either language. UI code
uses `tr(source, *args)` for complete sentences with numbered placeholders.
Service diagnostics are localized with `display_message` only when displayed;
persisted error messages, planner decisions and analysis results are unchanged.
Unknown third-party messages pass through rather than being guessed or sent to AI.

`app.main` configures the language and Qt locale before constructing the windows.
The local `QSettings` key `ui/language` takes priority over system-language
detection; `--language en|de` overrides it for one run. German systems default to
German and unsupported system languages fall back to English. Settings save a
new preference for the next start, leaving running jobs and open forms intact.
Qt's bundled German translator covers standard controls. Dates retain recorded
wall time and timezone semantics; localization does not convert capture times.

The JSON resources are included by setuptools and the existing PyInstaller
`--collect-data memento` path. To add interface text, mark the complete source
sentence with `tr`, add its English translation to `resources/i18n_en.json`, and
preserve placeholder numbers. Keep stable enum values, settings keys, template
IDs and JSON field names out of translation. The localization tests check
catalogue placeholders, saved choices, English/German startup and preservation
of original project/analysis content.

## Editing templates

Movie project format 4 adds an independent `EditingStyle` (stable template ID and
transition duration); formats 1–3 still load with Cut. Analysis, selection and
manual source bounds remain unchanged. The desktop copies the style on replanning
and uses existing session history and project persistence. Full preview/export
share the renderer; source-segment playback intentionally remains unprocessed.
`duration` continues to describe selected source time for planning/evaluation;
`playback_duration` estimates output after transition overlaps.

The renderer preserves the v3 hard-cut normalization cache. Optional styles use
FFmpeg xfade (fade, hblur, fadeblack, zoomin) plus acrossfade with triangular audio
curves. Overlap frames are limited to half of either neighbor. Actual decoded part
counts determine overlaps and final validation. Clip bodies and two-input
tail/head transitions are separately encoded, cached by style and actual frame
counts, validated and concatenated. Only two normalized inputs enter each effect,
so thousands of clips do not become one unbounded xfade graph. Completed pieces
survive cancellation; pending files are removed. Template changes reuse normalized
parts, and never call the AI provider. Final concatenation must preserve the exact
prepared frame sum minus overlaps. Effects add another encode pass; color/HDR
limitations of the existing normalizer remain.

The application mark lives in `src/memento/resources/memento.svg`. The native
vector source renders deterministically with `scripts/build_icons.py` into a
512px PNG preview and a nine-size ICO (16–256px). Qt loads the packaged ICO at
startup; PyInstaller embeds it in the EXE and collects the resource data. NSIS
uses that same bundled ICO for setup and uninstall. Resource bytes contribute
to the source digest, so asset changes invalidate a previously built package.
The installed-app smoke check verifies small/large icon frames and Qt decoding.

## Current desktop workflow

Planner `event-balanced-local-v10` treats target duration as a guideline and keeps
short intact candidates eligible, including libraries containing only sub-two-second
moments. Full candidate ends are clamped to their original bounds to avoid floating
point overshoot. Exclusions, manual ranges and forced inclusion remain respected.
Renderer `hard-cut-h264-aac-v3` resets video timestamps before FPS conversion and
uses the shorter stream endpoint. Decodable normalized parts may contain fewer
frames than estimated from source metadata; progress reports this and cached parts
remain reusable. The final concatenation must still preserve the exact actual
frame sum, so losing a prepared segment remains an error. Empty or corrupt video,
changed originals and invalid paths remain errors independent of the target time.

Memento is a Python 3.12 / PySide6 desktop application for Windows and Linux.
Qt owns presentation and worker lifecycle; media discovery, metadata extraction,
SQLite persistence, indexing, and local shot analysis remain in Qt-independent
services. Original media files are read only.

The Gemini settings dialog stores the API key in the native credential store:
Windows Vault, Linux Secret Service/KWallet/libsecret, or macOS Keychain (macOS
has not been tested). The credential adapter accepts only these native backends
and selects a concrete safe backend out of keyring chains. It never delegates
operations to a chain containing arbitrary third-party/file backends. Linux
installs SecretStorage; the desktop session must supply an unlocked Secret Service.
Indexing and shot analysis remain local. A separate semantic-analysis dialog
shows the upload scope and requires an explicit start before sending temporary
video/audio proxies directly to Gemini.

The main window stores selected media roots in `QSettings`. The SQLite media library and persistent indexing/analysis jobs are separate local application data under `%LOCALAPPDATA%\Memento\library.sqlite3`; generated shot thumbnails live under `%LOCALAPPDATA%\Memento\cache\thumbnails`.

Linux defaults to `$XDG_DATA_HOME/Memento` or `~/.local/share/Memento`; an existing
legacy `~/AppData/Local/Memento/library.sqlite3` is reused if the new location
has no database. `MEMENTO_DATA_DIR` overrides both. No automatic moves occur.

Startup restores saved media roots lexically and reads folder statistics only
from SQLite. It never resolves or probes media paths on the GUI thread. A
`FolderAvailabilityChecker` uses sequential `QProcess` probes, each limited to
five seconds, to open directories. Results update folder rows without changing
the cached assets or analyses. A manual retry supports reconnected shares.
Closing cancels outstanding probes; a failed share cannot prevent window startup.
Source runs invoke `memento.media.availability`; frozen builds use the internal
`--check-media-folder` entry point before creating QApplication. Import creation
also stores roots without resolving them; discovery resolves them in the worker
and records individual root failures instead of aborting other roots.

The UI starts one indexing job for all selected roots. A `QObject` worker runs `MediaIndexService` in a `QThread`; progress and completion return through Qt signals. Users can cancel the active job, select a saved incomplete job to resume, and inspect per-file errors. Closing the application requests cancellation and waits for the worker to stop, leaving the job resumable.

Import/local-analysis UI receivers are explicit Qt slots with queued delivery.
Workers are deleted on thread completion; the GUI joins the finished thread
before releasing Python worker references. This synchronizes deferred QObject
deletion and avoids a Qt/Shiboken destruction race reproduced under Linux.

After indexing, the user can start a separate local shot-analysis job for the whole library. `ShotAnalysisService` samples frames locally, detects strong HSV-histogram changes, stores source-time ranges and one 320 px maximum-edge JPEG per shot. It persists per-asset progress and errors, can resume interrupted jobs, and skips assets already analyzed with the same version. Thumbnail paths are relative to the Memento cache; each analysis writes to a new generation directory and replaces database references only after the new files exist.

`MoviePlanningService` reads cached semantic ranges in bounded batches, converts
them to source times and infers contiguous events from recorded calendar time
and free-form semantic labels. Capped event budgets depend on semantic value and
user weights, not recording count. Marginal selection downweights repetition
and considers activity and descriptive people-label variety. Forced/excluded
moments and manual trims are independent user preferences. No provider is called
by movie planning. Current local feature windows contribute a small technical
quality preference and sampled visual redundancy. Semantic and emotional value
still dominate; missing or stale local analysis stays neutral.

Planner `event-balanced-local-v4` anchors event clustering to the original semantic
moment timestamps. Candidate playback chronology and local feature summaries use
the actual edited ranges instead, so trims cannot silently change event IDs or
discard event weights. Manual ranges are indivisible when selected. They can
borrow time from an event's soft budget while respecting the overall target;
force-inclusion remains the explicit way to exceed that target. Ranges too long
for the remaining target do not reserve budget ahead of other usable footage.
Rejection explanations distinguish overlaps and intact manual ranges that do not
fit. Missing manual references are reported. Plans own their preference snapshots.

Planner `event-balanced-local-v5` compares sampled visual sequences against intact
selections across the whole movie. It keeps semantic, activity and descriptive
people-label diversity scoped to the event, so another day's similar family
activity is not treated as the same moment merely because its words recur.
Visual comparison still requires three textured samples, comparable duration,
low hash distance and similar colors. Signatures of full candidates are not
evidence about automatically shortened ranges, either during ranking or in
rejection explanations. Similarity is a soft preference, never an automatic
exclusion; selected similar-looking moments carry a review note. Equal event
coverage priorities use chronological event order rather than hash IDs.

Planner `event-balanced-local-v6` treats event budgets as bounded soft allocations
when a whole proposed moment almost fits. It can transfer at most two seconds
per choice, at most 25% of the recipient event's budget, and at most 15% of the
movie target across all such transfers. Donor allocations decrease proportionally
to their spendable time, preserving up to two already-funded seconds for their
first selection. Global target time is unchanged. Fitting/ranking uses the expanded
whole-range allowance, including valid visual evidence for a now-intact range.
Manual trims and explicit forced moments keep their separate semantics. Transfer
decisions are recorded in segment reasons. A synthetic independent reference
regression compares intact 10s+6s moments with a reconstructed hard-budget
8s+6s+2s baseline at the same 16s target; this does not certify real action/speech
boundaries or real-world movie quality.

Movie projects live in `movies/*.memento.json`, separately from the intelligence
database. They retain source snapshots, events, exact ranges, user preferences,
selection/rejection explanations and warnings. Editing, reordering and saving
never modifies the semantic cache. Loading validates source ranges and overlaps;
the renderer checks the actual files against the stored snapshots.

Planner `event-balanced-local-v9` weights each event by its strongest eligible
moment's existing multidimensional value, rather than the average of all its
recordings. Ordinary footage can no longer dilute an important birthday memory;
additional equal/lower-valued candidates leave event importance unchanged.
Exclusions and non-fitting indivisible trims are filtered before importance is
computed. Capacity caps, user event weights, chronological representation and
within-event marginal selection remain separate: this is not a global top-clip
selection. One inaccurate high model assessment can still overstate an event;
the existing confidence factor is not a calibrated guarantee. The synthetic
regression fixes two independent 10s memories at a 20s target, adds 99 ordinary
birthday ranges and compares both planners against the same source-time reference.
No semantic cache, schema, original media or existing saved timeline changes;
v9 takes effect on explicit generation/replanning. Real event importance,
diversity allocation and narrative quality still need human evaluation.

Planner `event-balanced-local-v8` additionally separates dense activity changes
using cached event labels and activities. A boundary needs at least 30 seconds
of uncovered recording time and two distinct source assets on each side (four
in total), each with confidence >= 0.65 and at least two informative tokens.
Within-side Jaccard similarity must be >= 0.5; every cross-side comparison must
be < 0.1. Corroborating pairs stay on the same calendar day and at most ten
uncovered minutes apart. Overlapping camera coverage, isolated reactions,
generic labels and low-confidence confirmation do not trigger this new rule.
The original day/gap rules remain in place. Context uses original analysis
timestamps, so manual trims preserve event IDs and weights. Feature preparation
and the fixed-size lookaround are linear after chronological sorting; no new
provider calls, media reads, schema or cache invalidation are introduced.
Existing saved plans keep their timeline until explicitly replanned. This is a
conservative lexical heuristic; sparse transitions, synonyms and shared generic
vocabulary still need real-world evaluation.

`domain.movie_history.MovieHistory` retains up to 50 plan changes in the current
editing session. Snapshots own their nested preferences and timeline; no media,
library or analysis data is copied. The UI records edits only after atomic project
save succeeds, and restores disk before advancing the undo/redo cursor. Failed
edits revert to the last committed snapshot. Replanning is one undoable change;
opening a project resets history. Undo/redo shortcuts are disabled while a worker
owns the project. History is session-local; the current plan remains autosaved in
the existing project format without introducing a database migration.

`CandidateDialog` uses an on-demand `QAbstractTableModel` rather than one
`QTableWidgetItem` per cell. It owns a working copy of constraints until acceptance;
exclusion and force-inclusion are mutually exclusive. It merges current cached
candidates with historical IDs from the plan and its constraints. Missing forced
IDs can be cleared but cannot be newly forced; manual trims can be reset without
editing the timeline. On a reopened project, `MovieDialog` reads candidates in its
cancellable worker without calling the planner's build operation, saving the plan,
or invoking AI. The modal editor opens only after the worker stops. Inspection
preserves timeline order, ranges and history; accepting constraints uses ordinary
atomic autosave and undo/redo. Last-generation decisions are labeled as such.

Semantic analysis accepts a per-run provider-call limit. Its budget is local to
each explicit `run` invocation and checked before uncached preprocessing and every
provider call, including retries. Cache hits consume no calls. Exhaustion persists
`request_limit` on the job and leaves the current uncached item pending, so another
explicit start resumes successful coverage. Existing durable item attempts record
all attempted calls; no schema migration is needed. The UI defaults to 25 calls
per start, locks the control during a run and distinguishes total pending scope
from the bounded transmission scope for that start. This is an invocation limit,
not a monetary budget; token usage and attempts are not a provider invoice.

The semantic inspection table reads pages of at most 100 ranges. The repository
selects that page before joining preferred source locations and direct/equivalent
cache responses, using one read transaction and connection. It never loads other
pages' semantic JSON into the UI or opens per-row repository connections. Page
navigation preserves the job scope; changing jobs resets the offset. Counts and
out-of-range offsets are resolved in the same read snapshot. The scope notice
explicitly states that provider calls may include other pages of the selected job.

`domain.movie_review.review_events` derives actual event duration, movie share,
enabled selection counts and constraint differences from an editable plan alone.
It never reconstructs nominal budgets or treats historical decisions as current
selection truth. Omitted events remain visible, disabled segments do not count,
and empty output has zero shares. `EventReviewDialog` presents these immutable
summaries in an on-demand table, with details about missing forced moments,
still-included exclusions and different manual bounds. Unassigned historical
constraints receive a separate notice. Inspection requires no media, database,
AI call, project save or history mutation.

`application.evaluation` compares source-time coverage with a strict, independently
annotated reference format. It unions selected ranges, gives each reference moment
only its best alternative camera's coverage, and computes weighted coverage,
thresholded recall and human event coverage. Matching uses stored hashes or an
explicitly weaker exact file snapshot; it never opens source media. Reference and
plan must share the date range and target duration. The network-free
`python -m memento.evaluate` CLI produces reproducible JSON with reference/timeline
digests and does not overwrite files. These are coverage metrics, not an automatic
judgment of narrative/emotional quality; see `evaluation.md` for annotation rules.

`MovieRenderService` adapts UltraCut's normalized segment and concat stages into
a Qt-independent service. Output uses H.264/AAC with original audio or silent
padding for missing audio, and preserves aspect ratio inside a fixed frame.
Persistent manifests and normalized parts under `cache/renders` allow restart
after interruption. Publication uses a temporary file in the destination folder
and refuses to overwrite an existing destination, including racing file creation.
`MovieDialog` owns worker lifecycle, corrections, single-segment Qt playback and
opening the completed export in the OS player.

Renderer `hard-cut-h264-aac-v2` explicitly sets both the frame-rate filter and
output CFR rate. Without the latter, muxing very short trimmed segments could
produce an unusable timeline or a default 25fps output. Before committing a
normalized part, FFmpeg decodes its video and audio with fatal decode errors;
the decoded video frame count must match the planned range within one frame
of quantization. Padded audio/container duration cannot establish video coverage.
Cached parts are validated again even when size/mtime match; a failed part is
rebuilt while intact parts remain reusable. Before atomic publication the whole
concatenation is decoded and must preserve the exact sum of part frame counts.
Validation shares cancellable subprocess handling and cleanup with rendering.
This adds local decoding work; no media is uploaded. The versioned cache avoids
reusing older unvalidated output. Checks establish decodability and frame
coverage, not perceptual quality, color accuracy or perfect audio/video sync;
AAC/container timing still needs broader real-media testing.

The same renderer prepares an optional complete 640×360 / 30 fps / CRF 28 movie
preview with original audio. `MovieDialog` snapshots the plan and runs rendering
in its existing cancellable worker. Completed parts use the persistent render
cache; assembled previews use an owned temporary session directory. Unchanged
plans reuse the assembled preview within that session. Plan edits require a new
preview on demand, without analysis calls or replacing the full-resolution export.
Preview relinking applies only to the worker snapshot and does not edit the plan.
The player distinguishes source-segment bounds from movie-relative playback and
supports pause and movie seeking. Stopping clears playback intent before decoder
signals can arrive. Closure releases the source before best-effort session cleanup;
a crash or locked file may leave derived cache files behind.

```text
Folder roots -> discovery -> local metadata probe -> SQLite media library
                                     |                    |
                                     +-- progress/errors -+-> Qt library view
```

## Local media library and indexing (schema 7)

`memento.domain.media` defines Qt-independent value objects for media assets,
capture timestamps, shots, analysis state, and persistent indexing jobs. Capture
time retains its source, confidence, and raw metadata value.

`CaptureTimeDialog` pages canonical assets (including missing dates and offline
locations) from the local index, with path search and confidence filters.
An explicit manual correction changes only recording time/source/confidence;
the source revision, technical analysis and semantic cache stay valid. Existing
raw metadata is retained. Unknown timezone offsets remain unknown rather than
being converted through the workstation timezone. Verified import preserves
manual timestamps for identical contents; a changed source becomes a different
identity and does not inherit that correction. Saved film projects keep their
snapshot order until the user regenerates the plan.

`memento.library.database.MediaLibrary` stores the index in SQLite, by default
under `%LOCALAPPDATA%\Memento\library.sqlite3`. The database uses foreign
keys, WAL mode, bounded lock waits, and ordered schema migrations tracked by
`PRAGMA user_version`. Schema 2 adds durable index jobs, per-file work status,
and isolated discovery/file errors. Schema 3 adds durable media-analysis jobs
and per-shot thumbnail references. Each operation opens and closes its own
connection, keeping the repository independent of Qt worker lifetimes.

Schema 4 adds semantic jobs, source-range work items and versioned semantic
cache entries. `AIProvider` is independent of Qt, Gemini and movie planning.
New upload ranges favor current local shot boundaries near the nominal
45-second split, with a 60-second maximum and the same nominal request count
per uncovered gap. Existing successful ranges are retained, including empty
answers; source range identity already participates in the cache key. A new
local analysis therefore does not invalidate paid semantic coverage. Historical
overlaps are unioned when finding remaining gaps and checking completeness.
`GeminiProvider` alone handles the BYOK secret and Google's wire format.
`SemanticAnalysisService` creates temporary local proxies, validates provider
results, persists successful answers and resumes unfinished work. See
`implementation-status.md` for protocol details, verified behavior and limits.

Schema 5 adds `local_feature_windows`: half-second sampled source ranges with
numeric local measurements and an independent local-analysis version. The
shot worker reuses UltraCut's Laplacian, exposure and affine optical-flow
primitives, and adds DCT perceptual hashes with color checks. Low-texture frames
cannot establish visual redundancy. Shots, measurements, analysis state and
successful analysis record commit in one transaction. A new local version never
invalidates Gemini's cache.

Planning streams feature rows in batches of 100 assets through one connection,
summarizes measurements by overlap with each candidate (including manual trims)
and retains only three representative signatures in a candidate. It does not
load all frame measurements of a large library simultaneously. Quality is a
soft preference; similarity is not a hard duplicate rejection. Local sample
warnings and visual-redundancy decisions are persisted in the movie plan.

Before upgrading an existing schema, SQLite's backup API writes a new snapshot
under `backups/`; committed WAL content is included. A failed backup prevents
migration. Movie file format 3 additionally records verified source content hashes;
formats 1 and 2 remain readable. Format 1 is explicitly labeled as having an unspecified
legacy planner version.

`library.recovery` snapshots databases through SQLite's backup API, including WAL,
and prepares/migrates a selected snapshot in a private recovery directory. It checks
SQL integrity, foreign keys, application schema columns, JSON job data, media value
objects and supported versions before publication. Arbitrary custom triggers/views
are not supported. Backup sources are opened read-only and never migrated in place.

The previous live database is snapshotted separately; if SQLite cannot read it,
raw database/WAL/SHM/journal evidence is copied instead. A checksummed prepared
file and a durable intent precede publication. Sidecars are quarantined and the
database file is atomically replaced. Startup completes pending intents under
the library OS lock, before opening SQLite, including a crash after replacement
but before receipt creation. A late cancellation cannot interrupt publication;
preparation is cancellable and retries start a new preparation. File-system or
power-failure behavior beyond the tested process-crash cases is not certified.

`RecoveryDialog` runs backup, inspection and restore in a QThread, confirms the
concrete snapshot before exchange and prevents closure with a live worker. Startup
also offers recovery for an unreadable library; `--restore-backup` opens the same
guided workflow. Film projects, source media and credentials are never restored
or modified by this service. Missing derived thumbnails trigger local regeneration.

Schema 6 adds a unique nullable SHA-256 content identity, location availability,
legacy asset-ID aliases and a persistent force-verification flag for import jobs.
`save_verified_asset` acquires a write transaction before resolving content identity.
Byte-identical locations share one asset. Replacing a verified location with different
content detaches that location and preserves the old content's analysis for any
remaining or later reimported copy. Preferred locations favor available and recently
seen paths. Missing locations retain their metadata but cannot displace a newly
indexed usable copy.

Hashing streams 4 MiB blocks with cancellation, progress and before/after file
checks. A legacy asset first receives a verified hash only when its stored file
revision still matches; old semantic revision fields are promoted without changing
cache keys or candidate IDs. Merged legacy answers remain inspectable, and equivalent
cached source ranges satisfy new analysis jobs without another provider call.
Manual or more reliable recording dates take precedence over a copy's filesystem time.

Movie sources carry optional content identities. Missing or replaced sources may
be relinked to an indexed equal-content location only after a full hash matches.
The renderer fully checks each hashed source before using it; uncached semantic
uploads also verify the indexed source hash. Legacy plans without hashes do not
receive speculative filename-based relinking.

`memento.media.discovery` recursively scans selected roots, skips symlinked
entries, deduplicates overlapping roots, and recognizes the prototype's video
extensions. `memento.application.indexing.MediaIndexService` persists jobs,
records each file result, reports progress, isolates errors, and can resume
pending work after cancellation or restart. Already hashed, unchanged path/size/mtime
entries are skipped by ordinary scans. A force-verification job hashes them again,
including after resume. A single-location legacy path with changed unverified
content keeps its path-era ID and invalidates its stale analysis; verified content
uses content identity instead of the path-era rule.

`memento.media.metadata` prefers structured FFprobe JSON when `ffprobe` is on
`PATH` or configured with `MEMENTO_FFPROBE`. If unavailable or unusable, it uses
the local `imageio-ffmpeg` executable to export structured global and video-stream
ffmetadata tags, plus local stream diagnostics and OpenCV for limited technical
fallbacks. Original media is never written. Embedded recording dates now survive
the FFmpeg fallback; filesystem modification time is used only if no valid
supported recording tag remains. Escaped metadata and chapter sections are handled
without reading chapter dates as recording dates.

QuickTime's `com.apple.quicktime.creationdate` is preferred over generic
EXIF original/digitized times and generic `creation_time` tags. Within a tag type,
valid video-stream tags take precedence over format tags. Invalid preferred values
do not hide valid fallback values. Explicit EXIF UTC offsets are combined with the
date; a broken offset keeps an uncertain original wall time. An explicit
UTC offset is retained as part of the timestamp; timezone-free metadata remains
naive and receives lower confidence rather than being assigned a fabricated
timezone. The library date-range query uses each stored timestamp's recorded
calendar date, with inclusive start and end dates. It does not convert timestamps
between zones, so clips with unknown offsets remain discoverable by their
recorded date while the UI identifies their source and confidence.

Date-range inspection uses `capture_date_page` and `DateRangeDialog`, separately
from the planner's full-range API. One SQLite read transaction returns the total,
undated count, clamped offset and at most 200 canonical assets for the desktop.
Preferred source locations are resolved only after the asset page is limited;
copies do not duplicate results and offline locations remain inspectable.
Recording time and asset ID give deterministic ordering even for equal dates.
A `QAbstractTableModel` formats only requested cells and does no I/O. The initial
page is passed from the main window to avoid a duplicate read. Each navigation
reads a fresh snapshot and handles a result set that shrank after corrections.
These queries still count/sort matching database records; the bounded guarantee
concerns materialized Python assets and view rows, not constant query time.
The 20,000-record check covers navigation and concurrent timestamp correction,
not media decoding or arbitrary-size database performance.

Schema 7 records an independent metadata extractor version. Re-indexing an
unchanged verified asset with stale metadata refreshes just that stage, reusing
its content hash and semantic/local caches. Existing manual and higher-confidence
recording times retain precedence. Confidence values are heuristics, not calibrated
probabilities. EXIF fields are supported when exposed by the media tools; there
is no independent complete EXIF binary parser.

The desktop entry point acquires a process-owned library file lock before
initialization or migration. A second desktop instance of that library is rejected;
OS locks are released on process exit, including crashes. Library services remain
Qt-independent; external direct API callers must coordinate their own lifecycle.
`MEMENTO_DATA_DIR` isolates library, default cache and Qt settings for installed-app
tests or separate workspaces.

`installer/Memento.nsi` adds per-user NSIS installation without elevation. Its
exact uninstall ownership list is generated from a verified bundle; directories
are removed only when empty, never recursively. A product marker rejects foreign
nonempty install directories. Upgrades run the previous owned uninstaller to
remove obsolete payload files before extraction. An active executable blocks the
operation. Shortcuts and the per-user Programs entry are separate from application
data and vault credentials; the desktop shortcut is deleted only if installer-owned.
The build script tests a separate product ID with an uncompressed payload before
compiling the LZMA production setup, and publishes only after payload/script digest
checks. Installed-app smoke, update, uninstall and preservation checks run in a
workspace path containing spaces. No production product registration is used by
these tests. Authenticode and clean-machine acceptance remain separate.

`scripts/build_windows.py` checks tests, builds a PyInstaller directory bundle,
captures source/EXE digests and installed dependency/license inventory, then runs
the frozen app with a minimal system PATH. Its isolated offline check generates
media and exercises indexing, metadata, local analysis, fixture intelligence,
planning, project roundtrip, H.264/AAC rendering and a valid Qt preview frame.
It also instantiates the paged date-range dialog from the frozen application,
verifies its model and navigation state, decodes the expected 24 frames of the test
export with audio (at most one frame of rounding), and reports the runtime planner/local-analysis/render profile
IDs. The build verifier requires these results, rather than treating launch alone
as sufficient. This runs on the development Windows machine with an isolated data
directory and restricted PATH; it does not replace a fresh-machine acceptance test.
It also verifies and deletes a uniquely named disposable Windows Vault entry.
It never requests Gemini inference or reads the user's Gemini credential.

The library view invokes the indexing service through a dedicated QThread worker.
The library view also runs shot analysis in a separate QThread worker. Shot
analysis uses OpenCV at 0.5-second requested intervals, splits at HSV histogram
distance `>= 0.62`, and enforces a 1-second minimum between cuts. It uses decoder
presentation timestamps where monotonic values are available; fallback sample
times are marked as approximate in shot features. This first version targets
hard cuts and is not a semantic highlight detector.

Local analysis profile `opencv-hsv-quality-phash-v3` rejects failed or empty
sample decodes more than one sampling interval (0.5s) before the known end.
Previously the loop could silently stop early and commit full-duration shots.
Failures now retain the requested source time in the per-file error, release
the decoder and leave other assets running; resuming retries the failed asset.
A missing sample within the last interval is tolerated for duration rounding,
but a source still needs at least one decodable frame. Non-finite durations
are rejected before sampling. Invalid, out-of-range or non-monotonic decoder
timestamps fall back to the requested sample time and mark the timebase as
approximate. The version change invalidates local analysis only: an explicit
local-analysis run refreshes older results without re-requesting cached AI
analysis or modifying saved movie plans. Sampling does not verify every frame,
and a decode failure alone does not establish whether the source or decoder
is at fault.

Application data is separate from source videos. Original files are referenced
by path and are never opened for writing by this indexing pipeline.
