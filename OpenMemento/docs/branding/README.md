# OpenMemento · Erinnerungsband

Approved direction: the first design in `logo-concepts-v2.png`. The ribbon forms
an organic M: separate moments become a continuous story. The production assets
are a hand-built vector interpretation of that image concept, not a cropped bitmap.

- Pine: `#204e40`; icon background: `#193e32`.
- Apricot fold: `#eda77f`; light icon ribbon: `#fff7e7` / `#dcebd5`.
- `src/memento/resources/logo-mark.svg`: transparent standalone ribbon.
- `src/memento/resources/logo-wordmark.svg`: ribbon plus outlined wordmark;
  no installed font is needed at runtime.
- `src/memento/resources/memento.svg`: square desktop icon.
- `logo-preview.png`: current production identity preview.

To change the vector master, edit `scripts/build_branding.py`. Regenerating the
outlined wordmark requires Segoe UI on the development machine. Then run:

```powershell
.venv\Scripts\python scripts/build_branding.py
.venv\Scripts\python scripts/build_icons.py
```

The second command needs no fonts. It renders PNG, nine Windows ICO sizes and
24-bit NSIS BMPs, updates this preview and copies website branding assets. BMPs
are included as package data so installer visuals come from the verified payload.

The Imagegen exploration and its original prompt remain here as design history.
