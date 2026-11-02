# OpenMemento project website

Standalone, bilingual Hugo site for GitHub Pages. The Python application is
unchanged. English lives at `/en/`, German at `/de/`; the root redirects to English.
All assets are served with the site. No theme, npm install, external fonts,
analytics, cookies or Gemini credentials are needed to view the site.

## Preview and build

Use **Hugo 0.162.1 or later** (the workflow pins 0.162.1).
From the repository root:

```powershell
hugo server --source website
```

Open the URL printed by Hugo, including `/OpenMemento/en/` or
`/OpenMemento/de/`. To build the production site:

```powershell
hugo --source website --minify --panicOnWarning
```

Generated output is in `website/public/` and is intentionally ignored.

## Publish to GitHub Pages

1. Push these source files and `.github/workflows/pages.yml` to `main`.
2. In **Settings → Pages → Build and deployment**, choose **GitHub Actions**.
3. Run **Hugo · GitHub Pages** from Actions, or push a website change to `main`.
4. The expected address is `https://marcogriep88.github.io/OpenMemento/`.

Pull requests build for validation but do not deploy. Publishing runs only from
pushes to `main` and manual workflow runs. In the `github-pages` environment,
restrict deployment branches to **Selected branches and tags → main**. This
also prevents a manually dispatched workflow on another branch from deploying.
Python-only pushes do not rebuild the website.

If you rename the repository or configure a custom domain, update `baseURL` in
`hugo.toml`; add a `static/CNAME` file only when using a custom domain.
See [Hugo's GitHub Pages guide](https://gohugo.io/host-and-deploy/deploy-to-github-pages/).

## Protect the website while accepting Python contributions

`.github/CODEOWNERS` assigns `website/` and all `.github/` files (including itself
and deployment workflows) to **@MarcoGriep88**. Python source has no mandatory
code owner. **CODEOWNERS is not enforcement by itself.** Enable it on GitHub:

1. Open **Settings → Rules → Rulesets → New branch ruleset**.
2. Target `main`, set enforcement to **Active**, and require pull requests.
3. Enable **Require review from Code Owners**, at least one required approval,
   and **Dismiss stale pull request approvals when new commits are pushed**.
4. Block force pushes and branch deletion. Keep bypass permissions limited to
   your own trusted administrative access; do not let general contributors bypass.
5. In **Settings → Environments → github-pages**, allow deployments only from
   `main`. Optionally require your own deployment approval if supported by your plan.
6. In **Settings → Actions → General**, keep the default workflow token read-only
   and disable permission for Actions to create/approve pull requests unless needed.

Contributors can fork the repository and propose Python changes through PRs.
Website or workflow changes require your review before merge. Repository admins
can change rules, so do not grant admin access to untrusted contributors. Ordinary
branch protection cannot guarantee protection against someone who controls the
repository's settings. For stronger organizational separation, use a separate
website repository with only you holding write access.

Smoke check after enabling the rules: open a Python-only PR and a website PR
from another account. The website PR must request Marco's approval; direct writes
to `main` must be blocked for ordinary contributors. Required approval counts may
also require an ordinary reviewer on Python PRs; code-owner approval is specific
to the protected paths.

Documentation: [Code owners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
and [rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets).

## Edit content and design

- `data/en.json`, `data/de.json`: translated landing page content.
- `content/_index.en.md`, `content/_index.de.md`: search/social descriptions.
- `layouts/`: shared accessible markup and SEO metadata.
- `assets/css/main.css`: responsive design and square buttons.
- `assets/js/main.js`: lightweight example selector, no network calls.
- `static/images/`: locally served illustrative photographs.
- `hugo.toml`: hosting URL, languages, repository and author website.

The example timeline is explicitly a concept, not a functioning media editor.
The copy distinguishes local processing from the approved video/audio proxies
sent to Google Gemini with the user's own API key. It identifies the application
as in development and does not promise validated real-world selection quality.

The footer links to Marco's existing imprint and privacy pages. Before a public
launch, the site's operator should ensure their privacy notice covers this
additional GitHub Pages hosting; the existing notice is not modified here.

## Photography

Illustrative travel photographs downloaded from Unsplash and served locally:

- `mountains.jpg`: https://unsplash.com/photos/landscape-photography-of-mountain-ranges-NsFG5mdspH4
  (image ID `photo-1464822759023-fed622ff2c3b`).
- `coast.jpg`: https://images.unsplash.com/photo-1473116763249-2faaef81ccda
- `forest.jpg`: https://images.unsplash.com/photo-1448375240586-882707db888b

Source: [Unsplash license](https://unsplash.com/license). Images illustrate the
concept and are not actual private family footage or generated movie results.
