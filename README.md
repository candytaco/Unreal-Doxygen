# Unreal-Doxygen

A preprocessing toolkit that makes [Doxygen](https://www.doxygen.nl/) work
properly with Unreal Engine C++ reflection macros and optionally publishes the
generated documentation to [Zensical](https://zensical.org) as a static site.

---

## Overview

Unreal Engine decorates C++ declarations with reflection macros such as
`UPROPERTY`, `UFUNCTION`, `UCLASS`, and `USTRUCT`.  These macros confuse
Doxygen: it can't attach a documentation comment to the C++ item that follows
because the macro sits between them.

This toolkit solves the problem in two steps:

1. **`preprocess.py`** — a Doxygen `INPUT_FILTER` that reads each C++ source
   file and:
   * Parses specifiers inside every Unreal reflection macro
     (`BlueprintCallable`, `Category=…`, `Server`, etc.).
   * Injects the matching Doxygen alias commands into the preceding `/** */`
     or `///` documentation comment.
   * Comments out the macro so Doxygen can correctly attach the comment to
     the C++ declaration that follows.

2. **`Doxyfile`** — a template Doxygen configuration that:
   * Defines `ALIASES` for every common Unreal specifier so the injected
     commands render as styled "Blueprint", "Category", "RPC", etc. sections.
   * Suppresses Unreal boiler-plate tokens via `PREDEFINED`.
   * Wires up `preprocess.py` as the `INPUT_FILTER`.

### Bonus tools

| Script | Purpose |
|--------|---------|
| `xml_to_markdown.py` | Converts Doxygen XML output into per-page Markdown (MSDN / Unreal Engine doc style) |
| `mkdocs.yml` | [Zensical](https://zensical.org) site configuration — builds a searchable static documentation site from the generated Markdown |

---

## Quick start

### Requirements

* Python ≥ 3.9
* Doxygen ≥ 1.9 ([download](https://www.doxygen.nl/download.html))
* `lxml` Python package (for `xml_to_markdown.py`):

  ```bash
  pip install lxml
  ```

* [Zensical](https://zensical.org) (for publishing the static documentation site):

  ```bash
  pip install zensical
  ```

### 1 — Copy the Doxyfile into your project

```bash
cp Doxyfile /path/to/your/project/Doxyfile
```

Edit `PROJECT_NAME`, `INPUT`, and `OUTPUT_DIRECTORY` at the top.

### 2 — Point `INPUT_FILTER` at `preprocess.py`

The Doxyfile already contains:

```
INPUT_FILTER = "python3 preprocess.py"
```

Adjust the path if `preprocess.py` is not on `PATH` or not in the project
root:

```
INPUT_FILTER = "python3 /absolute/path/to/preprocess.py"
```

### 3 — Run Doxygen

```bash
doxygen Doxyfile
```

Doxygen will pipe every source file through `preprocess.py`, inject Blueprint
behaviour descriptions into the doc-comments, and produce HTML + XML output
under `docs/`.

---

## preprocess.py

### How it works

Given this Unreal header:

```cpp
/**
 * @brief Applies damage to this actor.
 * @param DamageAmount The amount of damage to apply.
 */
UFUNCTION(BlueprintCallable, Category = "Combat")
void ApplyDamage(float DamageAmount);
```

`preprocess.py` outputs:

```cpp
/**
 * @brief Applies damage to this actor.
 * @param DamageAmount The amount of damage to apply.
 * \ufunction \blueprintcallable \category{Combat}
 */
// UFUNCTION(BlueprintCallable, Category = "Combat")
void ApplyDamage(float DamageAmount);
```

Doxygen then renders `\blueprintcallable` and `\category{Combat}` as:

> **Blueprint:** Callable from Blueprints
>
> **Category:** Combat

### Supported macros

`UPROPERTY`, `UFUNCTION`, `UCLASS`, `USTRUCT`, `UENUM`, `UDELEGATE`,
`UMETA`, `UPARAM`

### Supported specifiers

#### Blueprint access (UPROPERTY)

| Specifier | Alias | Description |
|-----------|-------|-------------|
| `BlueprintReadWrite` | `\blueprintreadwrite` | Accessible in Blueprints (Read/Write) |
| `BlueprintReadOnly` | `\blueprintreadonly` | Read-only in Blueprints |
| `BlueprintAssignable` | `\blueprintassignable` | Assignable (Multicast Delegate) |
| `BlueprintNativeOnly` | `\blueprintnativeonly` | Native only |

#### Blueprint function (UFUNCTION)

| Specifier | Alias | Description |
|-----------|-------|-------------|
| `BlueprintCallable` | `\blueprintcallable` | Callable from Blueprints |
| `BlueprintPure` | `\blueprintpure` | Pure (no exec pins) |
| `BlueprintImplementableEvent` | `\blueprintimplementableevent` | Override in Blueprints |
| `BlueprintNativeEvent` | `\blueprintnativeevent` | May override in Blueprints |

#### RPC (UFUNCTION)

| Specifier | Alias | Description |
|-----------|-------|-------------|
| `Server` | `\server` | Server RPC |
| `Client` | `\client` | Client RPC |
| `NetMulticast` | `\netmulticast` | NetMulticast RPC |
| `Reliable` | `\reliable` | Reliable delivery |
| `Unreliable` | `\unreliable` | Best-effort delivery |
| `Exec` | `\exec` | Console command |

#### Edit / Visibility (UPROPERTY)

`EditAnywhere`, `EditDefaultsOnly`, `EditInstanceOnly`,
`VisibleAnywhere`, `VisibleDefaultsOnly`, `VisibleInstanceOnly`,
`EditFixedSize`

#### Class specifiers (UCLASS / USTRUCT)

`Blueprintable`, `NotBlueprintable`, `BlueprintType`, `NotBlueprintType`,
`Abstract`

#### Key=value specifiers

| Specifier | Alias |
|-----------|-------|
| `Category="…"` | `\category{…}` |
| `DisplayName="…"` | `\displayname{…}` |
| `ToolTip="…"` | `\uetooltip{…}` |
| `meta=(DisplayName="…")` | `\displayname{…}` |

### Standalone usage

```bash
# Print processed file to stdout
python3 preprocess.py MyComponent.h

# Write to a file
python3 preprocess.py MyComponent.h -o MyComponent_processed.h
```

---

## xml_to_markdown.py

Converts Doxygen's XML output into per-page Markdown using the
[MSDN reference documentation style](https://github.com/MicrosoftDocs/microsoft-style-guide/blob/main/styleguide/developer-content/reference-documentation.md)
(one Markdown file per function / property).

### Output structure

```
docs/md/
    index.md                    # master index of all classes
    ACombatActor/
        index.md                # class overview + member list
        ApplyDamage.md          # one page per function
        MaxHealth.md            # one page per property
    ...
```

### Usage

```bash
# Defaults: reads docs/xml, writes to docs/md
python3 xml_to_markdown.py

# Custom paths
python3 xml_to_markdown.py --xml-dir build/xml --output-dir site/api
```

---

## Zensical — publish the static documentation site

[Zensical](https://zensical.org) is a modern static site generator (by the
creators of Material for MkDocs).  The `mkdocs.yml` in this repository
configures Zensical to turn the Markdown files produced by `xml_to_markdown.py`
into a searchable, mobile-friendly reference site.

### Install Zensical

```bash
pip install zensical
```

### Preview locally

```bash
zensical serve
```

Opens a live-preview server at <http://localhost:8000>.  The site auto-reloads
whenever a Markdown file changes.

### Build the static site

```bash
zensical build
```

Writes the finished site to `site/`.  Upload the contents of `site/` to any
static hosting provider (GitHub Pages, Netlify, Cloudflare Pages, S3, etc.).

### Deploy to GitHub Pages

```bash
zensical gh-deploy
```

Builds the site and force-pushes the output to the `gh-pages` branch of the
current repository.  Enable GitHub Pages in your repository settings to make
the site publicly accessible.

### `mkdocs.yml` configuration

The provided `mkdocs.yml` template uses `docs_dir: docs/md` — the default
output directory of `xml_to_markdown.py`.  Customise `site_name`, `site_url`,
and optionally add explicit `nav:` entries after running
`xml_to_markdown.py` for the first time to see which pages are generated.

---

## Full pipeline

```bash
# 1. Run Doxygen (preprocess.py is called automatically via INPUT_FILTER)
doxygen Doxyfile

# 2. Convert Doxygen XML → per-page Markdown
python3 xml_to_markdown.py       # writes to docs/md/

# 3. Preview the docs site locally
zensical serve

# 4a. Build the static site
zensical build                   # output in site/

# 4b. Or deploy directly to GitHub Pages
zensical gh-deploy
```

---

## Tests

```bash
pip install pytest
pytest tests/ -v
```

---

## License

MIT
