---
title: Documentation
---

# Documentation

Documentation is built using [MkDocs](https://www.mkdocs.org/) with several plugins:

* [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) for the theme
* [mkdocs-macros](https://mkdocs-macros-plugin.readthedocs.io/) for macros and variables


## Structure

```
gc-batch/
├── docs/                # Markdown documentation files
│   ├── index.md         # Home page
│   ├── development/     # Development docs
│   └── guides/          # User guides
├── include/
│   └── mkdocs/
│       └── macros.py    # Custom macros
└── mkdocs.yml           # MkDocs configuration
```


## Writing Documentation


### Installing MkDocs Dependencies

```bash
uv sync --group docs
```


### Adding New Pages

New pages are added as markdown files in the `docs/` folder.
Pages must be included in the `nav:` section of `mkdocs.yml`:

```yaml title="mkdocs.yml"
nav:
  - Home: index.md
  - Development: development/
  - Guides: guides/
```


### Viewing Changes Locally

MkDocs includes a development server with live reloading:

```bash
uv run mkdocs serve
```

Then open http://localhost:8000 in your browser.


### Building Static Site

To build the static documentation site:

```bash
uv run mkdocs build
```

The output will be in the `site/` directory.


## Markdown Features

### Admonitions

```markdown
!!! tip
    This is a tip admonition.

!!! warning
    This is a warning admonition.

!!! note
    This is a note admonition.
```

### Code Blocks

````markdown
```bash
gc-batch create --job-name my-job
```

```python
from gc_batch.client import BatchClient
client = BatchClient()
```
````

### Tables

```markdown
| Column 1 | Column 2 |
|----------|----------|
| Value 1  | Value 2  |
```


## Deploying Documentation

The published site is versioned with [mike](https://github.com/jimporter/mike) and
tracks releases, not `main`. Releasing deploys that version and moves the
`stable` alias that
<https://empirico-oss.github.io/gc-batch/stable/> resolves to. The workflow
itself is `.github/workflows/mkdocs.yaml`.

Pre-releases do not publish, so a release candidate never becomes `stable`.

To publish a preview of a branch — or of a pre-release — run the **Build and Deploy
Docs** workflow from the Actions tab; it deploys the branch under its own name, plus
any alias you pass as the `alias` input.

!!! warning "Do not run `mkdocs gh-deploy`"
    It overwrites the whole `gh-pages` branch with a single unversioned build,
    destroying the version switcher and every published release. Use `mike` if you
    need to deploy by hand:

    ```bash
    uv run --only-group docs mike deploy --push --update-aliases 1.2.3 stable
    ```
