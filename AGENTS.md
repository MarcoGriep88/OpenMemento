# Product Goal: Local-First AI Family Video Editor

Build a desktop application that automatically turns large collections of personal and family video footage into thoughtfully edited highlight movies.

The application should dramatically reduce the manual work involved in reviewing hundreds or thousands of raw smartphone videos, identifying meaningful moments, organizing them chronologically, and creating a coherent movie.

The product is not specifically a "year-in-review" generator.

Users select an arbitrary time period or collection of media, for example:

- a vacation
- a birthday
- a weekend
- one month
- several months
- a complete year
- any custom start/end date

The application then creates a high-quality first cut from that material.

Example:

> Select July 12–26, 2026  
> Target duration: 12 minutes  
> Style: Family vacation

Result:

> A chronological ~12-minute movie containing the most meaningful moments from that period.

---

# Core Product Principle

The product should not merely concatenate technically good clips.

Its primary value is:

> Find the moments a human would actually want to remember and turn them into a coherent movie.

A technically imperfect clip of a meaningful family moment may be far more important than a perfectly exposed but meaningless shot.

Semantic and emotional relevance therefore matter more than purely technical video quality.

---

# Existing Project

An existing prototype already performs parts of the video analysis using OpenCV.

Do NOT rewrite the project from scratch.

Before implementing major changes:

1. Inspect the complete existing repository.
2. Understand the current architecture.
3. Identify existing functionality that can be reused.
4. Identify technical debt or architectural limitations.
5. Compare the current implementation against this product goal.
6. Propose an incremental target architecture.
7. Only then begin implementation.

Prefer improving and restructuring working components over replacing them unnecessarily.

---

# Desktop-First / Local-First Architecture

The application should be a desktop application.

Original media should remain on the user's computer whenever possible.

Heavy deterministic processing should happen locally, including where appropriate:

- media discovery
- metadata extraction
- FFmpeg operations
- decoding
- OpenCV analysis
- shot detection
- blur detection
- exposure/darkness analysis
- motion analysis
- duplicate detection
- perceptual similarity
- proxy generation
- final rendering

The user's computer should perform the computational work that does not require a cloud AI model.

Cloud infrastructure should NOT be required merely for storing or rendering the user's media.

---

# AI Strategy

Use multimodal AI for tasks where conventional computer vision is insufficient.

The initial AI provider should be Gemini because of its video, temporal and audio understanding capabilities.

The AI layer must nevertheless be abstracted behind a provider interface so additional providers or local models can be supported later.

Conceptually:

AIProvider

- GeminiProvider
- FutureProvider
- FutureLocalProvider

Do not spread Gemini-specific API logic throughout the application.

---

# Bring Your Own API Key

The initial commercial architecture should support BYOK ("Bring Your Own Key").

The user supplies their own Gemini API key.

The application communicates directly with Gemini using the user's credentials.

The software vendor does not pay the user's AI inference costs.

API credentials must:

- never be included in logs
- never be included in analytics
- never be persisted as plain text
- use the operating system's secure credential storage where possible
- never be transmitted to the application's licensing/backend services

Design the architecture so a managed AI service could be added later without redesigning the video pipeline.

---

# Separate Media Intelligence From Movie Generation

This is a fundamental architectural requirement.

There are two separate concepts:

## 1. Media Analysis

Understand source media once.

## 2. Movie Generation

Use existing analysis to generate arbitrary movies later.

Expensive AI analysis should NOT have to run again whenever the user requests another movie.

Example:

The user has 20,000 family videos.

After they have been indexed and analyzed, requests such as:

> "Create a 7-minute movie from August 3–17."

or:

> "Create a 15-minute movie covering all of 2026."

should primarily query the existing local media intelligence database.

---

# Local Media Intelligence Database

Maintain a persistent local index of analyzed media.

For every source asset, retain information such as:

- source path / stable media identity
- recording date/time
- duration
- codec and technical metadata
- detected shots
- technical quality metrics
- semantic descriptions
- detected activities/events
- interesting time ranges
- audio relevance
- emotional relevance
- uniqueness
- embeddings where useful
- similarity relationships
- analysis version
- AI model/provider/version
- confidence values

The exact schema should be designed based on the actual requirements rather than blindly implementing this list.

Analysis results must be cached.

Re-running the application should not cause expensive analysis to be repeated unnecessarily.

If analysis algorithms or models change, support selective invalidation/re-analysis.

---

# Media Import

Users should be able to point the application at one or more folders containing their media.

The system should recursively discover supported video files and build/update the local media index.

Original files must NEVER be modified.

The application should handle libraries containing thousands or tens of thousands of videos.

Indexing must therefore be:

- incremental
- resumable
- cancellable
- observable
- robust against individual corrupt files

A single problematic video must not abort an entire indexing job.

---

# Date and Time

Recording timestamps are essential because chronological storytelling is a core product feature.

Determine the best available recording timestamp from media metadata.

Handle:

- QuickTime metadata
- EXIF where applicable
- filesystem timestamps as fallback
- timezone inconsistencies
- missing metadata
- duplicate imports
- copied files

Retain information about timestamp confidence/source when appropriate.

---

# Local Preprocessing

Use OpenCV, FFmpeg and other appropriate local techniques to cheaply understand and reduce the media before expensive semantic AI processing.

Potential tasks include:

- shot boundary detection
- representative frame extraction
- blur detection
- darkness / overexposure detection
- camera motion estimation
- near-duplicate detection
- perceptual hashing
- audio level analysis
- speech presence
- unusable footage detection

Do not optimize prematurely.

The purpose of local analysis is both improving quality and avoiding unnecessary AI calls.

---

# Semantic Video Understanding

Use Gemini for semantic understanding of relevant video segments.

The model should understand temporal context and audio where useful rather than treating every frame as an independent image.

Semantic analysis should answer questions such as:

- What is happening?
- Who/what appears to be important?
- Is this an event or ordinary footage?
- Is there meaningful human interaction?
- Is there laughter, speech or another valuable audio moment?
- Which portions of the clip are interesting?
- Which portions are boring or redundant?
- Is there a natural beginning/end to the interesting action?
- Is this likely to be memorable?
- How does this footage relate to surrounding footage?

Prefer structured machine-readable output over prose.

Use validated schemas for model responses.

---

# Segment-Level Analysis

Do not assume that an entire source video has one quality or importance score.

A 90-second clip might contain:

- 20 seconds of nothing
- 12 seconds of an important moment
- 30 seconds of repetitive footage
- 8 seconds of laughter/reaction
- additional irrelevant footage

The system should be capable of identifying useful time ranges inside source clips.

Movie generation should operate primarily on candidate segments rather than whole source files.

---

# Highlight Selection

Do NOT simply calculate one score for every clip and take the highest-scoring clips.

Selection should consider multiple dimensions:

- semantic importance
- emotional relevance
- technical quality
- audio value
- uniqueness
- redundancy
- people diversity
- activity diversity
- event diversity
- temporal coverage
- narrative coherence
- requested target duration

A large number of recordings from one event must not automatically cause that event to dominate the final movie.

Duration should be allocated intelligently between detected events/clusters.

---

# Event / Story Clustering

Automatically infer related sequences of footage.

For example, vacation footage might naturally cluster into:

Arrival

→ Hotel

→ Beach

→ Boat trip

→ Restaurant

→ Sunset

→ Departure

A month might contain:

Weekend trip

→ Birthday

→ everyday family moments

→ Zoo

→ grandparents visiting

Do not rely on predefined event categories.

Infer meaningful clusters from timestamps, semantic similarity, location metadata where available and visual/audio context.

---

# Movie Planning

Before rendering, create an explicit movie plan/timeline.

The timeline should contain references to source media and precise time ranges.

Example conceptual representation:

Movie
- Chapter/Event
  - Segment(source, start, end)
  - Segment(source, start, end)
- Chapter/Event
  - Segment(...)
  - Segment(...)

The movie plan must remain editable independently of the original analysis.

This separation is important:

Media Library
→ Intelligence
→ Candidate Segments
→ Movie Plan
→ Render

---

# Editing Philosophy

The resulting movie should feel intentionally edited rather than AI-generated.

Prefer:

- chronological storytelling
- coherent sequences
- meaningful human moments
- natural action boundaries
- useful original audio
- sensible shot duration
- visual variety
- simple clean cuts
- subtle transitions where appropriate

Avoid:

- excessive transitions
- arbitrary cuts
- repetitive footage
- overly fast social-media editing by default
- generic "AI montage" aesthetics

The initial goal is a good human-like family movie, not flashy automated effects.

---

# User Control

AI should produce a strong first cut, not remove control from the user.

After generation, the user should be able to influence the movie with actions such as:

- make movie longer/shorter
- include more from an event
- include less from an event
- exclude a clip
- force-include a clip
- change segment boundaries
- reorder where appropriate
- regenerate selection
- adjust relative importance of events

Future natural-language controls should be possible, for example:

> "More from the beach."

> "The birthday is important. Give it more time."

> "Remove the car ride."

> "Include more clips with grandma."

Design the underlying representation so these features can be added cleanly.

---

# Rendering

Final rendering should happen locally using FFmpeg or another appropriate local media pipeline.

Rendering must not require uploading the original media to the software vendor.

The renderer should support common smartphone formats and preserve quality reasonably.

Initially prioritize reliable output over sophisticated effects.

Architecture should allow future support for:

- titles
- chapter cards
- background music
- audio ducking
- transitions
- stabilization
- color correction
- beat-aware editing
- subtitles

These are secondary to excellent footage selection.

---

# Privacy

Family media is highly private.

Privacy should therefore be treated as a product feature, not merely a compliance requirement.

The application should make it obvious:

- where media is stored
- what processing happens locally
- exactly what is sent to an AI provider
- which AI provider receives it
- when network access occurs

The software vendor should not receive users' original media in the BYOK architecture.

Never make privacy claims that are stronger than the actual implementation.

---

# Cost Awareness

AI analysis has a monetary cost to the user.

The application should therefore:

- estimate analysis volume before expensive operations
- avoid redundant calls
- cache successful responses
- show useful usage information
- allow analysis to resume
- batch requests where beneficial
- use cheaper models/stages where quality is sufficient

The architecture should make it possible to benchmark different Gemini models and analysis strategies.

Do not sacrifice movie quality merely to minimize fractions of a cent, but avoid obviously wasteful inference.

---

# Reliability

Large media libraries mean processing can take a long time.

Every long-running operation should therefore be designed around:

- resumability
- progress reporting
- cancellation
- retries
- persistent job state
- graceful failure
- idempotency where practical

Closing or crashing the application after analyzing 4,000 of 5,000 videos must not require starting over.

---

# Explainability / Debugging

The system should make selection decisions inspectable.

For a selected segment, developers — and eventually users — should be able to understand why it was selected.

Example:

Selected because:
- birthday event
- strong human interaction
- laughter detected
- unique moment
- good technical quality
- low redundancy

Likewise, rejected segments should be diagnosable.

This is essential for improving the selection algorithm.

---

# Commercial Architecture

Design the product as commercial desktop software.

Initial intended model:

- perpetual software license
- includes approximately one year of software updates
- software continues working after the update period expires
- renewal is required only for future software updates
- AI usage is paid directly by the user through their own Gemini API account

Licensing concerns should remain separate from the core video-processing architecture.

Do not build an unnecessary SaaS backend into the core application.

---

# Security

Treat the desktop client as an environment controlled by the user.

Do not depend on client-side secrecy for protecting vendor secrets.

There should be no vendor Gemini key embedded in the application.

If licensing is implemented, design it under the assumption that sufficiently motivated users can inspect and modify the client.

Prefer reasonable commercial license enforcement over invasive DRM.

---

# Development Priorities

Prioritize development in approximately this order:

1. Understand and stabilize the existing prototype.
2. Establish clean media indexing and persistent analysis.
3. Establish reliable date/time handling.
4. Establish segment/shot representation.
5. Integrate structured Gemini video understanding.
6. Build candidate selection and event clustering.
7. Build movie planning.
8. Generate a genuinely good automatic first cut.
9. Add user correction/editing workflows.
10. Improve rendering and presentation.
11. Add commercial licensing/update infrastructure.

Do NOT spend significant time on licensing, payments, animations, polished UI or cloud infrastructure before the automatic movie selection is genuinely useful.

---

# MVP

The MVP should answer one question:

> Can the system automatically create a family movie that a real person would actually want to watch?

A minimal successful workflow is:

1. User selects a media folder.
2. Application indexes the media.
3. User configures Gemini API access.
4. Media is analyzed and cached.
5. User selects a date/time range.
6. User chooses target movie duration.
7. Application generates a chronological movie plan.
8. User can inspect the proposed highlights.
9. Application renders the movie locally.
10. User watches the result.

Everything else is secondary until this workflow works extremely well.

---

# Success Criterion

The product succeeds when a user can take a large, messy collection of personal smartphone videos, select an arbitrary period, and receive a coherent movie containing the moments they would have wanted to select themselves — while eliminating most of the tedious work of watching, sorting and cutting the raw footage.

The ideal reaction is:

> "I would never have spent the hours required to make this movie myself, but these are actually the moments I wanted to keep."

Optimize for that outcome.