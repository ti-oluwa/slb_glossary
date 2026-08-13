# SLB Energy Glossary

Search the [SLB Energy Glossary](https://glossary.slb.com/) programmatically, in English and Spanish.

> This package is intended for research or instructional use only.

Attribution and disclaimer: this project uses content from the SLB Energy Glossary (<https://glossary.slb.com>). That content is owned by SLB; this project does not claim ownership of glossary entries or their text. Users should consult the original site and follow its terms of use when reusing or redistributing glossary content. See the NOTICE file for details and the project `LICENSE` for code licensing.

## Highlights

* **Pure async.** Every glossary lookup is an `async` function; nothing blocks the event loop.
* **Lazy by default.** Search functions are async generators - they `yield` results as they're found instead of building a list up front, so you can `break` out early without paying for work you don't need.
* **No browser install headaches.** Built on [patchright](https://pypi.org/project/patchright/), a stealth-patched Chromium automation driver, plus [playwright-stealth](https://pypi.org/project/playwright-stealth/) for extra fingerprint hardening. No Selenium, no manual driver management. Chromium, Firefox and WebKit are all supported.
* **Fast by default.** Images, fonts and media are blocked at the network layer, and page data is pulled out in single JavaScript round-trips instead of one request per element.
* **Functions, not classes.** There's no `Glossary` object to subclass or configure. Open a session, get a plain `SearchSession` value back, and pass it to whichever search function you need.
* **A decoupled `store` package.** Saving results to CSV/JSON/TXT/XLSX lives in its own package that only depends on ["things shaped like" a `SearchResult`](#saving-results-to-a-file), not on the glossary or browser code at all.
* **Configurable retries.** Flaky page loads are retried with a pluggable backoff policy - constant, linear, exponential or logarithmic.

## Installation

### As a library

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
uv add slb-glossary
```

Or with pip:

```bash
pip install slb-glossary
```

Then install the browser build patchright drives (a one-time step):

```bash
patchright install chromium
```

To save results as `.xlsx`, also install the optional `xlsx` extra:

```bash
uv add "slb-glossary[xlsx]"
```

### As a CLI tool

`click` is a core dependency, so installing `slb-glossary` by any of the methods below gets you two equivalent commands, `slb-glossary` and the shorter `slb`, with no extra flags needed.

With [uv](https://docs.astral.sh/uv/) (recommended - installs into an isolated tool environment):

```bash
uv tool install slb-glossary
```

Or try it once without installing anything, via [`uvx`](https://docs.astral.sh/uv/guides/tools/):

```bash
uvx slb-glossary search porosity
```

With [pipx](https://pipx.pypa.io/):

```bash
pipx install slb-glossary
```

Or, on macOS/Linux (including WSL), with a one-line installer that picks `uv` or `pipx` for you, installing `uv` first if neither is already on your machine:

```bash
curl -fsSL https://raw.githubusercontent.com/ti-oluwa/slb-glossary/main/scripts/install.sh | sh
```

On Windows, without WSL, use uv's native installer instead, then `uv tool install`:

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex; uv tool install slb-glossary"
```

Whichever method you use, finish with the one-time browser install:

```bash
slb-glossary install
```

## Quick start

```python
import asyncio
import slb_glossary as slb


async def main() -> None:
    async with slb.search_session() as session:
        async for result in slb.search(session, "porosity"):
            print(result.term, "-", result.definition)


asyncio.run(main())
```

## Command-line interface

Installing `slb-glossary` (see [As a CLI tool](#as-a-cli-tool) above) gets you the `slb-glossary` command, and the shorter `slb` alias for it:

```bash
slb search porosity
slb terms Geophysics --limit 20
slb topics list
slb urls fetch "https://glossary.slb.com/en/terms/p/porosity"
```

Every command that prints results also supports `--save PATH` (repeatable, for saving to several files/formats at once), `--format FORMAT` to override the format PATH's extension implies, and `--json` to print results as a JSON array to stdout instead of a table - handy for piping into `jq` or another program:

```bash
slb search "drilling fluid" --json | jq '.[].term'
slb terms Drilling --save drilling_terms.json --quiet
```

Run `slb --help`, or `--help` after any subcommand, for the full set of options - or pass `--tui` to fill them in interactively instead of memorizing flags.

## Logging

`slb_glossary` logs through the standard `logging` module under the `slb_glossary` logger and attaches a `NullHandler` by default, so it stays silent until you configure logging yourself:

```python
import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("slb_glossary").setLevel(logging.DEBUG)  # verbose, per-page detail
```

`INFO` covers session open/close and search start/end; `DEBUG` covers individual page loads, retries and parsed counts; `WARNING` covers unmatched topics and exhausted retries.

## Core concepts

### `SearchSession`: one session, many searches

`slb_glossary` has no `Glossary` class. Instead, `open_session` (or the `search_session` context manager) launches a browser and loads the glossary's topic list once, returning a `SearchSession` - a plain dataclass holding the live browser session and that metadata. Every search function takes this session as its first argument.

```python
session = await slb.open_session(language=slb.Language.ENGLISH)
try:
    ...
finally:
    await slb.close_session(session)
```

Prefer `search_session` for anything but long-lived services; it guarantees the browser is closed even if your code raises:

```python
async with slb.search_session(headless=True) as session:
    ...
```

`open_session` accepts:

| Parameter          | Default              | Description                                                                                     |
| ------------------- | --------------------- | --------------------------------------------------------------------------------------------------- |
| `language`           | `Language.ENGLISH`     | Glossary edition to search (`Language.ENGLISH` or `Language.SPANISH`).                              |
| `browser_type`       | `"chromium"`           | Playwright browser family to launch: `"chromium"`, `"firefox"` or `"webkit"`.                       |
| `headless`           | `True`                 | Run without a visible browser window.                                                               |
| `block`              | `True`                 | Resource types to drop for speed. `True` blocks images/media/fonts, `False` blocks nothing, or pass your own iterable, e.g. `{"image", "stylesheet"}`. |
| `timeout`            | `30_000`               | Milliseconds to wait for page loads and element lookups.                                            |
| `terms_per_tab`      | `12`                   | Results per page, as returned by the glossary site. Rarely needs changing.                          |
| `backoff`            | `RetryPolicy()`      | Retry policy for the initial topic load, reused by search functions. See [Retries and backoff](#retries-and-backoff). |
| `settle_timeout`     | `8.0`                  | Seconds to wait for results to update after a search filter changes (the site updates via JS, not a full page load). |
| `poll_interval`      | `0.3`                  | Seconds between polls while waiting on `settle_timeout`.                                            |
| `executable_path`    | `None`                 | Path to a specific browser build, if not using patchright's own install.                            |
| `proxy`              | `None`                 | Playwright-style proxy settings, e.g. `{"server": "http://myproxy:3128"}`.                          |

`session.topics` is a `dict` of topic name to term count, and `session.size` is the glossary's total term count - both fetched once, on open. Call `slb.refresh_topics(session)` to reload them later.

### Retries and backoff

Page loads that briefly render before the glossary's JavaScript widget finishes populating are retried using a `RetryPolicy`:

```python
from slb_glossary import RetryPolicy

policy = RetryPolicy.exponential(base_delay=0.5, attempts=5, max_delay=8.0)
async with slb.search_session(retry=policy) as session:
    ...
```

Four strategies are available, each with a constructor shortcut: `RetryPolicy.constant()`, `.linear()`, `.exponential()` (the default) and `.logarithmic()`. All accept `attempts`, `base_delay`, `factor`, `max_delay` and `jitter` (randomizes each delay by +/-50% to avoid retry storms; on by default).

### Searching

All three search functions are **async generators**: iterate them with `async for`, and nothing more is fetched than you actually consume.

```python
# Search the whole glossary for a query
async for result in slb.search(session, "gas lift", limit=5):
    ...

# Search within one or more topics (comma-separated)
async for result in slb.search(session, "flow", topic="Well completions,Production"):
    ...

# Every term filed under a topic - one result per term
async for result in slb.get_terms_on(session, topic="Directional drilling"):
    ...

# Just the term detail URLs, if that's all you need
async for url in slb.iter_term_urls(session, query="porosity"):
    ...
```

`limit` bounds the number of *terms* looked up, not the number of results yielded - a term can carry more than one definition (one per topic it's filed under), so `search(..., limit=3)` can yield more than three `SearchResult`s. Pass `limit=None` to fetch every match.

Topic names don't need to be exact: `get_topic_match` resolves whatever you pass to the closest topic in `session.topics` (case-insensitive, typo-tolerant). Call it yourself to see what a topic will resolve to before searching:

```python
slb.get_topic_match(session.topics, "drill")
# "Drilling"
```

### `SearchResult`

Every result is a `typing.NamedTuple`:

```python
class SearchResult(typing.NamedTuple):
    term: str
    definition: str | None
    grammatical_label: str | None
    topic: str | None
    url: str | None
```

Being a plain `NamedTuple`, it already supports `result._asdict()`, `result._replace(...)`, indexing, and unpacking - no custom methods needed.

### Saving results to a file

`slb_glossary.store` is a self-contained package with no dependency on the rest of `slb_glossary`. `save` works with any sequence of records that look like a `NamedTuple` (they just need `_asdict()` and `_fields`) - so it can save `SearchResult`s, records from your own code, or the async generators the search functions return directly:

```python
results = slb.search(session, "gas lift")
await slb.store.save(results, "gas_lift.json")  # collects the generator for you
```

The file format is chosen from the destination's extension, or pass `format=` explicitly:

```python
await slb.store.save(results_list, "results.data", format="csv")
```

Built-in formats: `csv`, `json`, `jsonl`/`ndjson`, `txt`, and `xlsx` (requires the `xlsx` extra). Check what's available with `slb.store.supported_formats()`.

Add support for a new format with `register_writer` - no subclassing required:

```python
import pathlib
from slb_glossary.store import register_writer, RecordLike


async def write_yaml(records: list[RecordLike], destination: pathlib.Path) -> None:
    import yaml

    with open(destination, "w") as file:
        yaml.dump([record._asdict() for record in records], file)


register_writer("yaml", write_yaml)
await slb.store.save(results_list, "results.yaml")
```

## Performance notes

* Image, font and media requests are blocked at the network layer by default (`block=True`) - the glossary is a JavaScript app, so scripts and stylesheets are always loaded, but nothing else needs to be.
* Page data (topic lists, result links, definition text) is read with single `evaluate`-style JavaScript calls rather than one round-trip per DOM element.
* Because search is lazy, `async for result in slb.search(session, "x"): break` after the first result does the minimum work needed to produce it.
* Reuse one `SearchSession` for every search you need instead of opening a new one per query - most of the cost of a session is the one-time browser launch and topic fetch.
* A `SearchSession` drives a single browser page and isn't safe to share across concurrent coroutines. For parallel searches, open one session per concurrent task.

## Exceptions

* `slb_glossary.NetworkError` - the glossary site could not be reached.
* `slb_glossary.BrowserError` - the browser failed to launch or crashed outside of a network issue, including an unsupported `browser_type`.
* `slb_glossary.ParsingError` - reserved for glossary pages that don't match the markup the parser expects.
* `slb_glossary.store.UnsupportedFormatError` - `save` was asked for a format with no registered writer.
* `slb_glossary.store.WriterError` - the registered writer raised while writing, e.g. a permissions error or a full disk. The original exception is chained as `__cause__`.

## Development

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
uv run ruff check .
uv run ruff format .
```

## Contributing

Contributions are welcome. Please fork the repository and submit a pull request.

## Credits

This project was inspired by the 2023/24/25 Petrobowl Team of the Federal University of Petroleum Resources, Effurun, Delta State, Nigeria. It aided the team's preparation for the PetroQuiz and PetroBowl competitions organized by the Society of Petroleum Engineers (SPE).
