# DH Journal Agent

**English** | [简体中文](README.md)

A local literature-discovery tool for Chinese digital-humanities journals. It walks journal tables of contents issue by issue and follows a strict **screen first, import later** rule: capture builds a human-readable shortlist from titles and abstracts, and only the items you explicitly select ever reach Zotero.

Built for researchers in digital humanities, library and information science, and digital history. It does not monitor journals in real time, does not analyse full texts, and does not decide what you should read.

## The problem it solves

Researchers rarely lack "bulk import". What they lack is a low-noise way to discover articles. The manual routine is familiar: open several journal sites, find the right issue, read title after title, copy the metadata, then decide whether to keep anything. It is repetitive, easy to miss things, and tends to litter your Zotero library with items you never needed.

This tool splits the job into three stages:

1. **Capture** — fetch the table of contents, authors, sections, page ranges, links and abstracts for a given issue, section, or manually supplied contents page, and render them into `data/review.md`.
2. **Screen** — you pick the articles you want by index, or export an Excel sheet and tick rows in a spreadsheet application.
3. **Import** — only the indices you selected are written to Zotero. PDFs are attached when they can be downloaded, and degraded to a recorded link when they cannot.

## Design principles

- During capture it is a **read-only presenter**: nothing is written to Zotero and no PDF is downloaded.
- Import handles **only the items you explicitly selected** — never a whole issue by default.
- A suspicious capture result **never overwrites** the previous shortlist; a status file records what happened.
- Existing Zotero collections are **reused**; new ones are not created by default.
- CAPTCHAs, login walls and platform access controls are **never bypassed**.

## Installation

Python 3.10 or later is required.

```bash
git clone https://github.com/boringhxy/dh-journal-agent.git
cd dh-journal-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs the `dhjournal` command. To let MCP-capable AI clients (Claude Desktop, Cherry Studio, and others) call the tool directly, add the MCP extra:

```bash
pip install -e ".[mcp]"
```

That additionally provides the `dhjournal-mcp` entry point. Skipping `[mcp]` does not affect command-line usage.

> `python -m dhjournal` is equivalent to `dhjournal`. If your virtual environment is not activated, `./.venv/bin/dhjournal` works too.

## Quick start

Capturing and screening need **no Zotero credentials** — try it right after install:

```bash
dhjournal capture --journal "数字人文研究" --year 2026 --volume 6 --issue 2   # 1. Fetch the issue TOC
dhjournal review                 # 2. Read the shortlist and note the indices you want
```

Configure your own credentials only when you're ready to write into Zotero:

```bash
dhjournal init                        # 3. Interactive setup: enter credentials, test connection, optionally create collections
dhjournal import --selection "1,3,5"  # 4. Import only the selected articles
```

`dhjournal init` writes credentials to `config.local.json` under the data dir (never committed, never uploaded, never echoed); in a non-interactive shell it prints manual steps instead of blocking. To check readiness only, run `dhjournal doctor --zotero`.

## Command reference

Every `x` below is a placeholder. Replace it with an actual number at run time.

### Initialization

```bash
dhjournal init                   # interactive wizard: enter Zotero credentials → test connection → optionally create collections → self-check
dhjournal init-collections       # read-only preview: show which collection levels are missing per journal (writes nothing)
dhjournal init-collections --yes # actually create the missing collections after you confirm
dhjournal init-collections --journal "图书馆论坛" --yes   # only fix up one journal
```

`init-collections` previews by default and only writes to Zotero with `--yes`; the import flow itself still never creates collections on its own.

### Diagnostics

```bash
dhjournal doctor                 # dependencies, data directory, configuration file
dhjournal doctor --zotero        # additionally connect to Zotero and check each journal collection
dhjournal doctor --network       # additionally run a network connectivity check
```

### Capture

| Mode | When to use | Command |
|------|-------------|---------|
| Issue | One issue of one journal | `dhjournal capture --journal "期刊名" --year x --issue x` |
| Volume + issue | When the volume number matters | `dhjournal capture --journal "期刊名" --year x --volume x --issue x` |
| Section | A cross-issue section, full history | `dhjournal capture-channel --journal "图书馆杂志" --channel "数字人文"` |
| Manual contents page | Announcement pages, WeChat listings, unstable Airiti pages | `dhjournal capture --journal "期刊名" --url "contents-page-URL"` |

```bash
dhjournal capture --journal "数字人文研究" --year x --issue x
dhjournal capture --journal "数字人文研究" --year x --volume x --issue x
dhjournal capture --journal "图书馆论坛" --year x --issue x
dhjournal capture --journal "图书馆杂志" --year x --issue x
dhjournal capture-channel --journal "图书馆杂志" --channel "数字人文"
dhjournal capture --journal "中国数字人文" --url "real contents page URL"
dhjournal capture --journal "数位典藏与数位人文" --url "real contents page URL"
dhjournal capture --all-journals --year x --issue x   # explicitly capture every configured journal
```

`capture --year x --issue x` without a journal is rejected — capturing everything requires the explicit `--all-journals` flag.

### Screen and import

```bash
dhjournal review                                        # re-display the most recent shortlist
dhjournal abstract --index 1                            # show the full abstract of one article
dhjournal export-review                                 # export data/review_selection.xlsx
dhjournal import --spreadsheet data/review_selection.xlsx          # import rows ticked in the sheet
dhjournal import --spreadsheet data/review_selection.xlsx --dry-run # preview only
dhjournal import --selection "1,3,5"                    # import by index
dhjournal import --titles-file "titles.txt" --confirm-titles       # import by title matching
dhjournal import --selection "都不要"                    # skip this batch entirely
```

`export-review` writes `data/review_selection.xlsx`; set the "是否导入" column to "是" on the "筛选" sheet, then run `import --spreadsheet`.

A **selection basket** is handy when you browse and collect as you go:

```bash
dhjournal screen --list                     # current basket
dhjournal screen --search "keyword"         # find indices by keyword
dhjournal screen --add "1,3-5"              # add to the basket
dhjournal screen --remove "3"
dhjournal screen --clear
dhjournal screen --import                   # import everything in the basket
```

### Misc

```bash
dhjournal --data-dir /path/to/dir <subcommand>   # use a temporary data directory
dhjournal --help
```

`import --all` still exists for the rare case where you want an entire issue, but it is not the recommended path.

## Zotero setup

The tool speaks to Zotero through the Web API and uses **your own** credentials. It only reads them — never issues, stores, or proxies them.

1. Open <https://www.zotero.org/settings/keys>.
2. Create an API key with library read/write permission.
3. On the same page, note the numeric userID.
4. Copy `config.local.example.json` to `config.local.json` and fill in both fields:

```json
{
  "zotero": {
    "webLibraryId": "your numeric userID",
    "webApiKey": "your API key"
  }
}
```

`config.local.json` is listed in `.gitignore` and never enters version control. **Never paste the key into public documents or commits.**

Verify with `dhjournal doctor --zotero`: it reads every collection and checks the target paths one by one.

The following collection paths must already exist in Zotero:

```text
10-研究相关
└── 数字人文
    ├── 《数字人文研究》
    ├── 《数字人文》
    ├── 《中国数字人文》
    ├── 《数位典藏与数位人文》
    ├── 《图书馆杂志》
    └── 《图书馆论坛》
```

Corresponding settings in the default config `dhjournal/defaults/config.json` (to customize, drop a `config.json` in your data directory to override):

```json
"collectionPath": ["10-研究相关", "数字人文"],
"journalCollections": {
  "数字人文研究": "《数字人文研究》",
  "数字人文": "《数字人文》",
  "中国数字人文": "《中国数字人文》",
  "数位典藏与数位人文": "《数位典藏与数位人文》",
  "图书馆杂志": "《图书馆杂志》",
  "图书馆论坛": "《图书馆论坛》"
}
```

If you want the tool to create missing collections for you, set `zotero.autoCreateCollection` to `true`. The default is `false`: when a collection is missing, the import pauses and explains why.

## Supported journals

| Journal | Site | Parser | Issue resolution | Abstracts | PDF policy |
|---------|------|--------|------------------|-----------|------------|
| 数字人文研究 | `http://dhr.ruc.edu.cn/` | `journy3` | Archive page resolves past issues automatically | Usually available | Downloaded and attached when importing selected articles |
| 数字人文 | `https://szrw.cbpt.cnki.net/` | `cnki_cbpt` | Current public pages work; older issues may need a user-supplied URL | May be empty due to CNKI limits | Not downloaded by default; the link is recorded for manual download |
| 中国数字人文 | No stable public contents page is published | `generic_html` | Requires `--url` with an accessible contents page | Best effort, usually empty | Metadata-only fallback |
| 数位典藏与数位人文 | `http://www.tadh.org.tw/` | `generic_html` | Requires `--url` with an accessible contents page | Best effort, usually empty | Metadata-only fallback |
| 图书馆杂志 | `https://www.libraryjournal.com.cn/` | `magtech` | Issue pages, plus full paginated capture of the 数字人文 section | Usually available | Downloaded and attached when importing selected articles |
| 图书馆论坛 | `http://tsglt.zslib.com.cn/` | `magtech` | Volume numbers can be derived from configuration to reach archived issues | Usually available | Downloaded and attached when importing selected articles |

New journals are added mainly through configuration; how parsers are extended is described in `docs/sources.md`.

## Using it from an AI client (MCP)

The project ships an MCP server that MCP-capable clients can call directly.

```bash
pip install -e ".[mcp]"
dhjournal-mcp      # runs the MCP server over stdio
```

Example client configuration:

```json
{
  "mcpServers": {
    "dh-journal-agent": {
      "command": "dhjournal-mcp"
    }
  }
}
```

The server exposes 13 tools:

- **Read-only (8)**: `list_journals`, `get_capture_status`, `list_pending_articles`, `get_article_abstract`, `search_pending_articles`, `preview_import`, `get_import_report`, `run_doctor`
- **Local writes (4)**: `capture_issue`, `capture_channel`, `export_review_spreadsheet`, `mark_pending_skipped`
- **Zotero write (1)**: `import_to_zotero`

`import_to_zotero` **refuses by default**. It writes only when both `confirm=true` and `dryRun=false` are supplied. Failures come back as structured results carrying a `failureKind` (`network`, `blocked`, `captcha`, `empty_parse`, `issue_mismatch`, `not_configured`, `invalid_input`, `no_pending`) so the client can decide what to do next.

Full parameters and return fields are documented in `docs/mcp.md`.

## Data files

By default these live under `data/` in the project root (this is configurable, see below).

| File | Purpose |
|------|---------|
| `data/review.md` | Shortlist rendered by the latest capture, with contents and abstracts |
| `data/pending.json` | Structured pending data shared by `review`, `abstract` and `import` |
| `data/state.json` | Record of imported or skipped items, to avoid double processing |
| `data/last_capture_status.json` | Result of the latest capture; states whether `review.md` is still stale content |
| `data/import_report.md` | Report of the latest real import, with Zotero keys, failure reasons and PDF handling |
| `data/title_match_report.md` | Latest title-matching confirmation sheet (not an import) |
| `data/review_selection.xlsx` | Exported screening spreadsheet |
| `data/backups/` | Automatic backups taken before a successful capture overwrites files |
| `logs/capture.log` | Run log (HTTP logging is quieted and never prints the API key) |
| `tmp/` | Temporary PDF downloads, cleaned up after import |

`pending.json` is an object rather than an array:

```json
{
  "capturedAt": "ISO timestamp",
  "captureType": "issue/channel/manual_curated",
  "note": "capture note or correction reason",
  "markdown": "same body as data/review.md",
  "articles": [
    {
      "journal": "journal name",
      "year": "year",
      "volume": "volume number or null",
      "issue": "issue number or whole-issue number",
      "issueDisplay": "year/volume/issue as shown on the source site",
      "totalIssue": "whole-issue number or null",
      "sourceType": "issue/channel/manual_curated",
      "sourceNote": "source note or fallback reason",
      "section": "section name, possibly uncategorised",
      "title": "article title",
      "authors": ["author"],
      "abstract": "abstract text, possibly empty",
      "startPage": "start page",
      "endPage": "end page",
      "articleUrl": "article page URL",
      "pdfUrl": "PDF URL, possibly empty",
      "status": "presented/selected/imported/failed",
      "_globalIndex": "index within the shortlist"
    }
  ]
}
```

### Data directory resolution

Resolved in this order; the first match wins:

1. `--data-dir /path/to/dir` on the command line
2. `DHJOURNAL_DATA_DIR=/path/to/dir` in the environment
3. If the current working directory contains `config.json` or `data/`, use it (legacy layout)
4. Fallback to `~/.dhjournal`

## Capture quality checks

Results are inspected before saving. The following are marked `suspect` and **do not overwrite** the existing `review.md` / `pending.json`:

- The issue resolves to "year 0, issue 0" during a single-issue capture.
- Navigation, advertising or platform-recommendation text dominates the titles.
- The title duplication ratio is abnormal.
- `generic_html` requires certain page text but the page lacks the target journal, IssueID or section keyword.

When this happens, read the reason in the terminal and in `data/last_capture_status.json`, confirm the real contents page and retry with `--url`, or curate the list manually as a `manual_curated` capture.

## PDF fallback policy

PDFs are handled only during import.

- When a journal sets `autoDownloadPdf: true` and the PDF is reachable, it is downloaded, validated and attached to Zotero.
- When the download is not a PDF, is too small, fails on the network, is blocked by a CAPTCHA, or Zotero storage quota is exhausted, **the article still imports**.
- A degraded item keeps title, authors, journal, year, issue, pages, URL and abstract. The Extra field records the PDF link and failure reason, and the item is tagged `PDF待手动下载`.
- If the PDF was downloaded but the upload failed, a URL attachment records the download link.

## Limitations

- 数字人文研究 has good archived-issue support via its back-issue page.
- 数字人文 depends on public CNKI pages; if older issues are behind CAPTCHAs or logins, you must supply an accessible contents-page URL.
- 图书馆论坛 is wired to its public journal system and can derive historical URLs from `historyUrlTemplate` plus `volumeYearBase` / `volumeBase`.
- 图书馆杂志 uses the generic Magtech parser; the 数字人文 section can be captured in full via `capture-channel`. The site occasionally returns 412 or SSL errors — use `--url` with a real contents page when that happens.
- 中国数字人文 contents pages often redirect to WeChat, so authors and abstracts may not be complete; the tool degrades to titles and links.
- 数位典藏与数位人文 pages that return platform promotional content are rejected by the quality checks; prefer the official TADH announcement page or a manually curated list.
- This tool **never** solves CAPTCHAs, bypasses logins, or substitutes for your institution's access rights.

## Development

```bash
pip install -e ".[dev,mcp]"      # mcp is optional: without it, 1 server-registration check is skipped

python -B -m unittest discover -s tests -v    # unit tests
ruff check .                                  # static checks
```

See `CONTRIBUTING.md` for contribution rules and hard limits, `SECURITY.md` for reporting vulnerabilities, and `CHANGELOG.md` for version history.

## License

MIT — see [LICENSE](LICENSE).
