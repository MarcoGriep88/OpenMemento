# OpenMemento

**Your moments. A story worth keeping.**

OpenMemento is a local-first desktop application that turns large collections of
short family video clips into chronological highlight movies. It combines local
**OpenCV** analysis with **Google Gemini** video and audio understanding to help
find meaningful moments, build an editable first cut and render a movie on your
computer with **FFmpeg**.

Choose a vacation, a birthday, a weekend, a month or any custom date range. Set a
target duration and turn scattered recordings into a story you can watch together.

> **Development status:** The repository contains a working development version,
> not a finished public release. Selection quality still needs validation with
> real family footage. Target duration is a guideline and depends on the available
> usable material.

A project by [Marco Griep](https://marcogriep.de/).

[Deutsch](#deutsch) · [Getting started](#getting-started) ·
[Project website](#project-website) · [Contributing](#contributing)

## The idea

The most memorable clip is not always the sharpest or best-exposed one. A laugh,
a birthday wish or a small family interaction can matter more than a technically
perfect shot.

OpenMemento aims to reduce the time spent watching, sorting and trimming raw
footage while preserving those moments. It selects time ranges within recordings
and considers semantic value, emotional relevance, repetition and event coverage.
The result is a first cut that you can inspect and adjust.

## How it works

1. **Create a project.** Choose a name and target movie duration.
2. **Add your footage.** Select media folders, index their contents locally and
   optionally limit the recording date range.
3. **Analyze locally.** OpenCV detects shots and measures technical properties
   such as motion, blur and exposure.
4. **Understand the moments.** Configure your own Gemini API key, review the
   analysis scope and explicitly start video/audio analysis.
5. **Review the first cut.** Generate a chronological movie plan from cached
   analysis. Adjust highlights, segment boundaries and event importance.
6. **Export locally.** Render an MP4 with FFmpeg, with original audio or optional
   local background music.

Media analysis and movie generation are separate. Successful analysis is stored
locally and reused when planning other movies; changing a date range or target
duration does not itself require another AI call.

## Privacy and AI costs

- Original source files are read without modification.
- Indexing, OpenCV processing, the media database and final rendering are local.
- Semantic analysis sends approved temporary video/audio proxies directly to
  Google Gemini. This step requires internet access and is subject to Google's
  terms; the complete workflow is not offline.
- You provide your own Gemini API key. Google charges AI usage to your account.
- API keys use supported native operating system credential storage rather than
  plain-text configuration files.
- Successful AI responses are cached. Analysis jobs support progress reporting,
  cancellation and resuming work.

See the [application documentation](Memento_v2/README.md) for operational details
and [implementation status](Memento_v2/docs/implementation-status.md) for known
limitations and outstanding validation.

## Getting started

The desktop application lives in [`Memento_v2/`](Memento_v2/).

### Requirements

- **Python 3.12**; the package currently requires Python `>=3.12,<3.13`.
- **Windows or Linux** with a graphical desktop session.
- For Gemini: your own API key, internet access and an available secure credential
  store. On Linux, use an unlocked Secret Service or supported native keyring
  backend in the desktop session.

Dependencies are declared in
[`Memento_v2/pyproject.toml`](Memento_v2/pyproject.toml).

### Windows

From a terminal in the repository root:

```powershell
cd Memento_v2
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m memento.app
```

After setup, you can also start the application with `./start_windows.ps1` from
`Memento_v2`.

### Linux

```bash
cd Memento_v2
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
bash start_linux.sh
```

Configure Gemini in the application's settings before starting semantic analysis.
Never commit an API key or put it in a bug report.

### Interface language

The desktop interface supports **English and German**. On first launch, German
systems use German and other systems use English. Open **Settings / Gemini →
Language / Sprache**, select a language, save and restart to apply it.

For a temporary override, append `--language en` or `--language de` to the launch
command, for example:

```powershell
.venv\Scripts\python.exe -m memento.app --language en
```

The language preference is stored locally. Project names, filenames, user prompts
and cached AI descriptions keep their original content; changing the interface
language does not trigger new analysis.

Follow the [first-test guide](Memento_v2/docs/first-test.md) for a practical
walkthrough. Windows packaging instructions are in the
[application README](Memento_v2/README.md) and
[installer guide](Memento_v2/docs/installer.md).

## Architecture

```text
Media folders
    → Local index and metadata
    → OpenCV shot and quality analysis
    → Approved Gemini video/audio analysis
    → Persistent local media intelligence
    → Candidate segments and event selection
    → Editable chronological movie plan
    → Local FFmpeg export
```

The Python/PySide6 interface sits above separate application services, domain
models, SQLite persistence, media processing and AI provider contracts. Movie
projects remain separate from cached media analysis.

| Path | Purpose |
| --- | --- |
| `Memento_v2/src/memento/ui/` | Desktop interface and background workers |
| `Memento_v2/src/memento/application/` | Indexing, analysis, planning and rendering services |
| `Memento_v2/src/memento/domain/` | Media, movie and editing models |
| `Memento_v2/src/memento/library/` | Local database, projects and recovery |
| `Memento_v2/src/memento/media/` | Discovery, metadata and local video analysis |
| `Memento_v2/src/memento/ai/` | Provider contracts, Gemini integration and segmentation |
| `Memento_v2/src/memento/security/` | Secure credential storage |
| `Memento_v2/tests/` | Application tests |
| `website/` | English and German Hugo project website |
| `.github/` | Website ownership and GitHub Pages workflow |

Read the [architecture notes](Memento_v2/docs/architecture.md) before proposing
large changes.

## Project website

The Hugo site describes the project in **English and German**, with a responsive
layout, square-cornered buttons and an interactive movie timeline concept. It
links back to [marcogriep.de](https://marcogriep.de/).

With **Hugo 0.162.1 or later**, run these commands from the repository root:

```powershell
# Local preview
hugo server --source website

# Production build
hugo --source website --minify --panicOnWarning
```

Open the address printed by Hugo. Language routes are `/OpenMemento/en/` and
`/OpenMemento/de/` with the current configuration.

For deployment, select **GitHub Actions** in the repository's **Settings → Pages**.
The workflow in [`.github/workflows/pages.yml`](.github/workflows/pages.yml) builds
website pull requests and deploys website changes pushed to `main`. Pull requests
do not deploy. The configured public URL is
`https://marcogriep88.github.io/OpenMemento/`; availability depends on enabling
Pages and completing a deployment.

See the [website README](website/README.md) for content editing, asset sources,
deployment configuration and protection instructions.

## Contributing

Python contributions are welcome through pull requests. Start with the existing
implementation, keep changes focused and include relevant verification. Preserve
the separation between media analysis and movie generation, keep originals
untouched and use synthetic or explicitly approved media for tests.

To run the application tests after installing the development dependencies:

```powershell
# From Memento_v2 on Windows
.venv\Scripts\python.exe -m pytest -q
```

```bash
# From Memento_v2 on Linux
.venv/bin/python -m pytest -q
```

Website and GitHub configuration changes are assigned to **@MarcoGriep88** in
[`.github/CODEOWNERS`](.github/CODEOWNERS). To enforce that ownership, the repository
maintainer must enable a `main` branch ruleset requiring pull requests and
code-owner approval, dismiss stale approvals, and restrict the `github-pages`
deployment environment to `main`. CODEOWNERS alone does not block changes.
See the [protection setup](website/README.md#protect-the-website-while-accepting-python-contributions).

When reporting issues, include reproduction steps, operating system and relevant
error messages. Remove credentials, private filenames and personal media before
sharing diagnostics.

## License

See [LICENSE](LICENSE) for the repository's GNU General Public License v3 text and
[third-party notices](Memento_v2/THIRD_PARTY_NOTICES.md) for bundled components.

## Deutsch

**Eure Momente. Ein Film, der bleibt.**

OpenMemento ist eine lokale Desktop-Anwendung, die aus vielen kurzen
Familienvideos einen chronologischen Highlight-Film erstellt. **OpenCV** übernimmt
die lokale Bildanalyse. **Google Gemini** hilft, bedeutungsvolle Momente in Video
und Ton zu erkennen. Ein bearbeitbarer Filmplan wird anschließend mit **FFmpeg**
auf eurem Computer als MP4 exportiert.

Ihr wählt Medienordner, einen beliebigen Zeitraum und eine gewünschte Ziellänge:
Urlaub, Geburtstag, Wochenende, mehrere Monate oder ein ganzes Jahr. Gespeicherte
Analysen können für weitere Filme wiederverwendet werden. Originaldateien bleiben
unverändert.

Für die KI-Analyse benötigt ihr einen eigenen Gemini-API-Schlüssel. Freigegebene
Analysevideos mit Ton werden direkt an Google gesendet; Google rechnet die Nutzung
mit euch ab. Die semantische Analyse ist deshalb nicht vollständig offline.

Das Projekt ist **in Entwicklung**. Die Auswahlqualität mit echten
Familienaufnahmen muss noch validiert werden.

- [Deutsche Anleitung zur Desktop-App](Memento_v2/README.md)
- [Ablauf für den ersten Test](Memento_v2/docs/first-test.md)
- [Hugo-Website und GitHub-Pages-Einrichtung](website/README.md)
- [Marco Griep – Hauptwebsite](https://marcogriep.de/)
