"""Check generated help links, language pairs and local search indices.

Run after: hugo --source website --minify --panicOnWarning --cleanDestinationDir
"""
from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

PUBLIC = Path(__file__).resolve().parents[1] / "public"


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.links, self.alternates, self.ids = [], {}, set()
        self.help = self.support = self.redirect = False
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.help |= "help-layout" in attrs.get("class", "").split()
        self.support |= attrs.get("href") == "https://ko-fi.com/marcogriep"
        self.redirect |= tag == "meta" and attrs.get("http-equiv", "").lower() == "refresh"
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "link" and attrs.get("rel") == "alternate":
            self.alternates[attrs.get("hreflang")] = attrs["href"]
        for attr in ("href", "src", "data-index"):
            if attrs.get(attr):
                self.links.append(attrs[attr])


def target(url):
    path = PUBLIC / unquote(urlsplit(url).path).lstrip("/")
    return path / "index.html" if path.is_dir() or not path.suffix else path


def main():
    pages = {path: Page(path.read_text(encoding="utf-8")) for path in PUBLIC.rglob("*.html")}
    errors, help_count = [], 0
    for path, page in pages.items():
        if page.redirect:
            continue
        url = "https://openmemento.de/" + path.relative_to(PUBLIC).as_posix().removesuffix("index.html")
        if not page.support:
            errors.append(f"Missing support link: {path}")
        for link in page.links:
            resolved = urlsplit(urljoin(url, link))
            if resolved.netloc != "openmemento.de" or resolved.scheme not in ("http", "https"):
                continue
            destination = target(resolved.geturl())
            if not destination.is_file():
                errors.append(f"Broken link in {path}: {link}")
            elif resolved.fragment and destination in pages and unquote(resolved.fragment) not in pages[destination].ids:
                errors.append(f"Missing anchor in {path}: {link}")
        if page.help:
            help_count += 1
            if set(page.alternates) != {"de", "en"}:
                errors.append(f"Missing translated article: {path}")
            for lang, alternate in page.alternates.items():
                other = pages.get(target(alternate))
                if not other or not other.help:
                    errors.append(f"Invalid {lang} translation: {path}")
    for lang, prefix in (("de", "/de/hilfe/"), ("en", "/en/help/")):
        entries = json.loads((PUBLIC / f"help-search-{lang}.json").read_text(encoding="utf-8"))
        assert len(entries) == 10, f"Expected ten {lang} guides"
        assert len({entry["url"] for entry in entries}) == 10
        for entry in entries:
            assert entry["url"].startswith(prefix), entry["url"]
            assert entry["title"] and entry["summary"] and entry["text"]
            assert target(entry["url"]).is_file()
    assert help_count == 22, f"Expected 22 help pages, got {help_count}"
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Checked {help_count} help pages, translations, internal links, support links and both search indices.")


if __name__ == "__main__":
    main()
