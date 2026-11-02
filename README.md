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

## Why I’m building OpenMemento

As a family, we almost always have a camera or smartphone with us to capture the
good moments. All too often, those recordings stay on a phone or hard drive and
are never watched again. That’s why we turn ours into monthly and yearly movies
to watch together as a family.

The editing never had to be perfect. Still, watching hundreds, sometimes a
thousand clips, finding the good parts and putting them in chronological order
was a Sisyphean task. That first cut alone took countless hours. With two
children, we simply couldn’t keep up anymore. That’s why I started OpenMemento.

OpenCV checks the footage locally first. Gemini helps find meaningful moments in
the video and audio. OpenMemento uses those results to build a chronological,
editable first cut, whether it covers a month, a year, a holiday or any other
period.

My goal is to take those hours of assembling a first cut off your hands, leaving
you to add background music, put a title at the beginning and give the movie your
finishing touches. Those collected clips should become family movies you actually
watch again.

This application is being developed with AI coding tools. Contributions that help
keep the code clear and maintainable are welcome.

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

See the [application documentation](OpenMemento/README.md) for operational details
and [implementation status](OpenMemento/docs/implementation-status.md) for known
limitations and outstanding validation.

## Getting started

The desktop application lives in [`OpenMemento/`](OpenMemento/).

### Requirements

- **Python 3.12**; the package currently requires Python `>=3.12,<3.13`.
- **Windows or Linux** with a graphical desktop session.
- For Gemini: your own API key, internet access and an available secure credential
  store. On Linux, use an unlocked Secret Service or supported native keyring
  backend in the desktop session.

Dependencies are declared in
[`OpenMemento/pyproject.toml`](OpenMemento/pyproject.toml).

### Windows

From a terminal in the repository root:

```powershell
cd OpenMemento
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m memento.app
```

After setup, you can also start the application with `./start_windows.ps1` from
`OpenMemento`.

### Linux

```bash
cd OpenMemento
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

Follow the [first-test guide](OpenMemento/docs/first-test.md) for a practical
walkthrough. Windows packaging instructions are in the
[application README](OpenMemento/README.md) and
[installer guide](OpenMemento/docs/installer.md).

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
| `OpenMemento/src/memento/ui/` | Desktop interface and background workers |
| `OpenMemento/src/memento/application/` | Indexing, analysis, planning and rendering services |
| `OpenMemento/src/memento/domain/` | Media, movie and editing models |
| `OpenMemento/src/memento/library/` | Local database, projects and recovery |
| `OpenMemento/src/memento/media/` | Discovery, metadata and local video analysis |
| `OpenMemento/src/memento/ai/` | Provider contracts, Gemini integration and segmentation |
| `OpenMemento/src/memento/security/` | Secure credential storage |
| `OpenMemento/tests/` | Application tests |
| `website/` | English and German Hugo project website |
| `.github/` | Website ownership and GitHub Pages workflow |

Read the [architecture notes](OpenMemento/docs/architecture.md) before proposing
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

Open the address printed by Hugo. Language routes are `/en/` and `/de/`.

The workflow in [`.github/workflows/ftp.yml`](.github/workflows/ftp.yml) builds
website pull requests and deploys website changes pushed to `main` exclusively
via FTP to `/public_html/openmemento.de/`. Pull requests do not deploy. Configure
the repository secrets `FTP_HOSTNAME`, `FTP_USER` and `FTP_PASSWORD`.
The configured public URL is `https://openmemento.de/`.

See the [website README](website/README.md) for content editing, asset sources,
deployment configuration and protection instructions.

## Contributing

Python contributions are welcome through pull requests. Start with the existing
implementation, keep changes focused and include relevant verification. Preserve
the separation between media analysis and movie generation, keep originals
untouched and use synthetic or explicitly approved media for tests.

To run the application tests after installing the development dependencies:

```powershell
# From OpenMemento on Windows
.venv\Scripts\python.exe -m pytest -q
```

```bash
# From OpenMemento on Linux
.venv/bin/python -m pytest -q
```

Website and GitHub configuration changes are assigned to **@MarcoGriep88** in
[`.github/CODEOWNERS`](.github/CODEOWNERS). To enforce that ownership, the repository
maintainer must enable a `main` branch ruleset requiring pull requests and
code-owner approval and dismiss stale approvals. CODEOWNERS alone does not block changes.
See the [protection setup](website/README.md#protect-the-website-while-accepting-python-contributions).

When reporting issues, include reproduction steps, operating system and relevant
error messages. Remove credentials, private filenames and personal media before
sharing diagnostics.

## License

See [LICENSE](LICENSE) for the repository's GNU General Public License v3 text and
[third-party notices](OpenMemento/THIRD_PARTY_NOTICES.md) for bundled components.

## Deutsch

**Eure Momente. Ein Film, der bleibt.**

### Warum ich OpenMemento entwickle

Wir haben als Familie fast immer eine Kamera oder ein Smartphone dabei und halten
die schönen Momente fest. Viel zu oft bleiben solche Videos danach auf dem Handy
oder der Festplatte liegen und werden nie wieder angesehen. Wir machen deshalb
Monats- und Jahresfilme daraus, die wir uns als Familie gemeinsam anschauen.

Der Schnitt musste nie perfekt sein. Trotzdem war es jedes Mal eine
Sisyphusarbeit, hunderte, manchmal tausend Clips durchzusehen, die schönen Stellen
herauszusuchen und chronologisch zusammenzusetzen. Allein dieser Rohschnitt hat
unzählige Stunden gebraucht. Mit zwei Kindern kamen wir irgendwann einfach nicht
mehr hinterher. Deshalb habe ich OpenMemento gestartet.

OpenCV prüft das Material lokal vor. Gemini hilft, die bedeutungsvollen Momente in
Bild und Ton zu finden. Daraus erstellt OpenMemento einen chronologischen,
bearbeitbaren Rohschnitt – für einen Monat, ein Jahr, einen Urlaub oder jeden
anderen Zeitraum.

Mein Ziel: Euch den stundenlangen Rohschnitt abnehmen, damit ihr noch die passende
Hintergrundmusik ergänzen, einen Titel davor setzen und dem Film euren letzten
Feinschliff geben könnt. So werden aus gesammelten Clips wieder Familienfilme,
die ihr wirklich anschaut.

### Was die Anwendung macht

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

- [Deutsche Anleitung zur Desktop-App](OpenMemento/README.md)
- [Ablauf für den ersten Test](OpenMemento/docs/first-test.md)
- [Hugo-Website und GitHub-Pages-Einrichtung](website/README.md)
- [Marco Griep – Hauptwebsite](https://marcogriep.de/)
