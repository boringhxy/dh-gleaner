# DH Gleaner

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

Python 3.10 or later is required. You get the `dhgleaner` command; adding the `[mcp]` extra also installs `dhgleaner-mcp`, the entry point AI clients use. Skipping `[mcp]` does not affect command-line usage.

**Recommended: one line with pipx.** No clone, isolated environment, your system Python untouched:

```bash
pipx install "dh-gleaner @ git+https://github.com/boringhxy/dh-gleaner.git"
pipx install "dh-gleaner[mcp] @ git+https://github.com/boringhxy/dh-gleaner.git"
```

If you do not have pipx yet, install it first (`python3 -m pip install --user pipx`, or `brew install pipx` on macOS), or use uv:

```bash
uv tool install "dh-gleaner @ git+https://github.com/boringhxy/dh-gleaner.git"
uv tool install "dh-gleaner[mcp] @ git+https://github.com/boringhxy/dh-gleaner.git"
```

**Or clone into a virtual environment:**

```bash
git clone https://github.com/boringhxy/dh-gleaner.git
cd dh-gleaner
python3 -m venv .venv
source .venv/bin/activate
pip install ".[mcp]"
```

Editable installs (`-e`) are only for hacking on the code: `pip install -e ".[dev,mcp]"`. You do not need `-e` just to use the tool.

To move to a newer commit:

```bash
pipx upgrade dh-gleaner
```

Because the source is git, a warm pip cache can serve a stale build; if that happens use `pipx install --force "dh-gleaner[mcp] @ git+https://github.com/boringhxy/dh-gleaner.git"`. With uv, the equivalent is `uv tool upgrade dh-gleaner --reinstall`.

Run the self-check once after installing. It creates the data directory and tells you what is missing:

```bash
dhgleaner doctor
```

> `python -m dhgleaner` is equivalent to `dhgleaner`. If your virtual environment is not activated, `./.venv/bin/dhgleaner` works too.

## Quick start

Capturing and screening need **no Zotero credentials** — try it right after install:

```bash
dhgleaner capture --journal "数字人文研究" --year 2026 --volume 6 --issue 2   # 1. Fetch the issue TOC
dhgleaner review                 # 2. Read the shortlist and note the indices you want
```

Configure your own credentials only when you're ready to write into Zotero:

```bash
dhgleaner init                        # 3. Interactive setup: enter credentials, test connection, optionally create collections
dhgleaner import --selection "1,3,5"  # 4. Import only the selected articles
```

`dhgleaner init` writes credentials to `config.local.json` under the data dir (never committed, never uploaded, never echoed); in a non-interactive shell it prints manual steps instead of blocking. To check readiness only, run `dhgleaner doctor --zotero`.

## Command reference

Every `x` below is a placeholder. Replace it with an actual number at run time.

### Initialization

```bash
dhgleaner init
dhgleaner init-collections
dhgleaner init-collections --yes
dhgleaner init-collections --journal "图书馆论坛" --yes
```

- `init`: interactive wizard — enter Zotero credentials, test the connection, optionally create collections, then self-check.
- `init-collections`: read-only preview showing which collection levels are missing per journal; **writes nothing**.
- `init-collections --yes`: actually creates the missing collections once you confirm; add `--journal` to fix up one journal only.

`init-collections` previews by default and only writes to Zotero with `--yes`; the import flow itself still never creates collections on its own.

### Diagnostics

```bash
dhgleaner --version
dhgleaner doctor
dhgleaner doctor --zotero
dhgleaner doctor --network
```

- `--version`: prints the version; include it along with the `doctor` output when reporting a bug.
- `doctor`: checks dependencies, data directory and configuration file.
- `doctor --zotero`: additionally connects to Zotero and checks each journal collection.
- `doctor --network`: additionally runs a network connectivity check.

### Capture

| Mode | When to use | Command |
|------|-------------|---------|
| Issue | One issue of one journal | `dhgleaner capture --journal "期刊名" --year x --issue x` |
| Volume + issue | When the volume number matters | `dhgleaner capture --journal "期刊名" --year x --volume x --issue x` |
| Section | A cross-issue section, full history | `dhgleaner capture-channel --journal "图书馆杂志" --channel "数字人文"` |
| Yearly harvest | LIS/information journals with no standing DH section, where DH articles are scattered and the current-issue page is unstable — enumerate a whole year, then filter by keyword | `dhgleaner harvest --year 2026` |
| Manual contents page | Announcement pages, WeChat listings, unstable Airiti pages | `dhgleaner capture --journal "期刊名" --url "contents-page-URL"` |

```bash
dhgleaner capture --journal "数字人文研究" --year x --issue x
dhgleaner capture --journal "数字人文研究" --year x --volume x --issue x
dhgleaner capture --journal "图书馆论坛" --year x --issue x
dhgleaner capture --journal "图书馆杂志" --year x --issue x
dhgleaner capture-channel --journal "图书馆杂志" --channel "数字人文"
dhgleaner capture --journal "中国数字人文" --url "real contents page URL"
dhgleaner capture --journal "数位典藏与数位人文" --url "real contents page URL"
dhgleaner capture --all-journals --year x --issue x   # explicitly capture every configured journal
```

`capture --year x --issue x` without a journal is rejected — capturing everything requires the explicit `--all-journals` flag.

### Scattered-article harvest (enumerate a year, then filter by keyword)

Some library-and-information-science journals have no standing "digital humanities" section. Their DH articles are scattered across ordinary sections, and the current-issue page is unstable enough that the only reliable route is to walk the archive year by year. `harvest` is the third capture flow, built for exactly those journals: enumerate a full year of tables of contents → tag every article against the keyword tables → keep only the DH hits. Output lands in the same `data/review.md` / `pending.json`, so `screen` and `import` downstream work unchanged.

```bash
dhgleaner harvest --year 2026
dhgleaner harvest --journal "现代情报" --year 2026
dhgleaner harvest --year 2026 --all-catalog
dhgleaner harvest --year 2026 --no-abstracts
dhgleaner harvest --year 2026 --dedupe
dhgleaner harvest --year 2026 --dry-run
```

| Flag | Effect |
|------|--------|
| _(none)_ | Harvest every journal marked `harvestOnly` in the configuration |
| `--journal "现代情报"` | Harvest one journal only |
| `--all-catalog` | Keep the whole year's catalogue with DH tags, not just the hits |
| `--no-abstracts` | Skip abstract fetching; faster, but keywords then match titles only |
| `--dedupe` | Drop articles already recorded in `state.json` |
| `--dry-run` | Print only; do not overwrite `pending.json` / `review.md` |

Journals marked `harvestOnly: true` take part in the harvest rotation only: `capture --all-journals` and `doctor --network` skip them, and running `capture` on one for a single issue is rejected with a hint to use `harvest` instead (unless you pass an explicit `--url`).

**Keyword criteria** (`dhgleaner/keywords.py`, shared by `capture` and `harvest`; every article gets both tags). An article counts as DH **if and only if** it matches a DH domain term **or** satisfies the history+AI co-occurrence rule:

- **DH table** (`dhMatched`) — domain terms such as 数字人文 / 文化遗产 / 数字典藏 / 博物馆 / GLAM / 计量史学. **Any single hit** counts.
- **History+AI table** (`histAiMatched`) — history terms (古籍 / 甲骨 / 敦煌 / 方志 / 断代史 …) paired with computational-method terms (知识图谱 / 文本挖掘 / GIS / 深度学习 / 语义 / 本体 …). This uses a **co-occurrence** rule: at least one hit on each side is required.
- **Computational-method terms alone never count as DH.** LIS and information-science journals publish a great many "AI in LIS" papers that use method vocabulary with no digital-humanities substance; letting those through would flood the shortlist with noise. Method terms therefore only count as the computational side of a history+AI pair.
- Matching is case-sensitive substring matching, so abbreviations like RAG / GIS / OCR cannot accidentally match inside `storage` or `logistics`. Deliberately excluded trap words include 历史, 古代, 传统, 文化, 档案 and 记忆 — too generic to signal anything.

### Screen and import

```bash
dhgleaner review                                        # re-display the most recent shortlist
dhgleaner abstract --index 1                            # show the full abstract of one article
dhgleaner export-review                                 # export data/review_selection.xlsx
dhgleaner import --spreadsheet data/review_selection.xlsx          # import rows ticked in the sheet
dhgleaner import --spreadsheet data/review_selection.xlsx --dry-run # preview only
dhgleaner import --selection "1,3,5"                    # import by index
dhgleaner import --titles-file "titles.txt" --confirm-titles       # import by title matching
dhgleaner import --selection "都不要"                    # skip this batch entirely
```

`export-review` writes `data/review_selection.xlsx`; set the "是否导入" column to "是" on the "筛选" sheet, then run `import --spreadsheet`.

A **selection basket** is handy when you browse and collect as you go:

```bash
dhgleaner screen --list                     # current basket
dhgleaner screen --search "keyword"         # find indices by keyword
dhgleaner screen --add "1,3-5"              # add to the basket
dhgleaner screen --remove "3"
dhgleaner screen --clear
dhgleaner screen --import                   # import everything in the basket
```

### Misc

```bash
dhgleaner --data-dir /path/to/dir <subcommand>   # use a temporary data directory
dhgleaner --help
```

`import --all` still exists for the rare case where you want an entire issue, but it is not the recommended path.

## Zotero setup

The tool speaks to Zotero through the Web API and uses **your own** credentials. It only reads them — never issues, stores, or proxies them.

1. Open <https://www.zotero.org/settings/keys>.
2. Create an API key with library read/write permission.
3. On the same page, note the numeric userID.
4. Run `dhgleaner init` and paste both values when prompted — input is not echoed, and the connection is tested as soon as they are saved.

To configure by hand instead, write the two fields into `config.local.json` **in your data directory** (by default `~/.dhgleaner/config.local.json`; `dhgleaner doctor` prints the exact path plus the location of a template you can copy):

```json
{
  "zotero": {
    "webLibraryId": "your numeric userID",
    "webApiKey": "your API key"
  }
}
```

`config.local.json` never enters version control, is never uploaded, and never appears in logs. **Never paste the key into a public document, an issue, or a commit.**

Verify with `dhgleaner doctor --zotero`: it reads every collection and checks the target paths one by one.

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

Corresponding settings in the default config `dhgleaner/defaults/config.json` (to customize, drop a `config.json` in your data directory to override):

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
| 图书馆杂志 | `https://www.libraryjournal.com.cn/` | `magtech` | Issue pages, plus full paginated capture of the 数字人文 section | **Not capturable automatically right now**: the site's anti-bot pre-check returns 412 to every plain HTTP request, so you must pass `--url` with a contents page you can open in a browser | Downloaded and attached when importing selected articles |
| 图书馆论坛 | `http://tsglt.zslib.com.cn/` | `magtech` | Volume numbers can be derived from configuration to reach archived issues | Usually available | Downloaded and attached when importing selected articles |

The following journals are marked `harvestOnly: true`: they are collected through `harvest` on a yearly basis only, are skipped by `capture --all-journals`, and do not download PDFs by default.

| Journal | Site | Parser | Harvest strategy |
|---------|------|--------|------------------|
| 现代情报 | `https://www.xdqb.net/` | `founder` | Founder rc-pub open JSON API (`getPeriodTree`, articles grouped by section, abstracts inline) |
| 情报科学 | `https://journal12.magtechjournal.com/jwk3_qbkx` | `magtech` | Archive with the `ul.lunwen` skin; abstracts fetched per article |
| 中国图书馆学报 | `https://www.jlis.cn/jtlsc/ch/reader/` | `journalx` | `issue_list.aspx` enumerated by quarter; `view_abstract` fetched per article |
| 国家图书馆学刊 | `https://gtxk.nlc.cn/ch/reader/` | `journalx` | Same as above |
| 数字图书馆论坛 | `http://journals.istic.ac.cn/dlf/ch/reader/` | `journalx` | Same as above |
| 图书情报知识 | `https://dik.whu.edu.cn/jwk3/tsqbzs` | `magtech` | Archive with the `div.dqml` skin (DOI-style title links); abstracts fetched per article |
| 信息资源管理学报 | `https://jirm.whu.edu.cn/jwk3/xxzyglxb` | `magtech` | Same as above |

New journals are added mainly through configuration; how parsers are extended is described in `docs/sources.md`. To ask for one, use the [new journal source](https://github.com/boringhxy/dh-gleaner/issues/new?template=new_journal.yml) issue template — a real contents-page URL that opens without logging in is the single most useful thing you can supply.

## Using it from an AI client (MCP)

The project ships an MCP server that MCP-capable clients can call directly. Install the `[mcp]` extra:

```bash
pipx install "dh-gleaner[mcp] @ git+https://github.com/boringhxy/dh-gleaner.git"
```

Then `dhgleaner-mcp` runs the server over stdio.

Example client configuration:

```json
{
  "mcpServers": {
    "dh-gleaner": {
      "command": "dhgleaner-mcp"
    }
  }
}
```

Two things bite in practice:

- **Clients usually do not inherit your shell's PATH**, so a bare command name can fail with "command not found". Run `command -v dhgleaner-mcp` and put the absolute path in the config, e.g. `/Users/you/.local/bin/dhgleaner-mcp`.
- **The client's working directory is not the one you use on the command line**, and `--data-dir` does not apply to MCP. If you have been capturing into a project directory and want the AI client to see the same shortlist, set the data directory explicitly — otherwise it falls back to `~/.dhgleaner`:

```json
{
  "mcpServers": {
    "dh-gleaner": {
      "command": "/Users/you/.local/bin/dhgleaner-mcp",
      "env": {
        "DHGLEANER_DATA_DIR": "/path/to/your/working-directory"
      }
    }
  }
}
```

Nearly every tool returns `dataDir`, `dataDirSource` and `configLocalPath`, so the client can confirm which directory it is reading and writing.

The server exposes 14 tools:

- **Read-only (8)**: `list_journals`, `get_capture_status`, `list_pending_articles`, `get_article_abstract`, `search_pending_articles`, `preview_import`, `get_import_report`, `run_doctor`
- **Local writes (5)**: `capture_issue`, `capture_channel`, `harvest_year`, `export_review_spreadsheet`, `mark_pending_skipped`
- **Zotero write (1)**: `import_to_zotero`

`import_to_zotero` **refuses by default**. It writes only when both `confirm=true` and `dryRun=false` are supplied. Failures come back as structured results carrying a `failureKind` (`network`, `blocked`, `captcha`, `empty_parse`, `issue_mismatch`, `not_configured`, `invalid_input`, `no_pending`) so the client can decide what to do next.

Full parameters and return fields are documented in `docs/mcp.md`.

## Data files

Where these live depends on how you installed the tool: under `data/` in the project root after a clone, or under `~/.dhgleaner/data/` for a pipx / uv install. See "Data directory resolution" at the end of this section for the full rule.

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
2. `DHGLEANER_DATA_DIR=/path/to/dir` in the environment
3. If the current working directory contains `config.json` or `data/`, use it (legacy layout)
4. Fallback to `~/.dhgleaner`

## Capture quality checks

Each journal is inspected **separately** before saving — if 12 of 13 journals fail and one succeeds, the aggregate still "has articles", but that batch must not replace the previous complete shortlist. The following are marked `suspect` and **do not overwrite** the existing `review.md` / `pending.json`:

- The issue resolves to "year 0, issue 0" during a single-issue capture.
- Navigation, advertising or platform-recommendation text dominates the titles.
- Titles or abstracts contain the U+FFFD replacement character, meaning the page encoding was misdetected.
- The title duplication ratio is abnormal.
- `generic_html` requires certain page text but the page lacks the target journal, IssueID or section keyword.
- Some journals failed while others returned results in a batch capture.
- Channel pagination hit the `maxChannelPages` cap, so the list may only cover the first few pages.

When this happens, read the reason in the terminal and in `data/last_capture_status.json`, confirm the real contents page and retry with `--url`, or curate the list manually as a `manual_curated` capture.

### Exit codes

`capture` / `capture-channel` / `harvest` report status through exit codes, so cron jobs, CI and scripts can act on them:

| Code | Meaning |
|------|---------|
| 0 | Every journal captured cleanly and passed the quality gate |
| 1 | Nothing usable was captured (bad arguments also exit 1) |
| 2 | The command line itself was invalid (argparse) |
| 3 | Something was captured but the quality is doubtful, or only some journals succeeded — the old shortlist was not overwritten and deserves a look |

The `failures` array in `data/last_capture_status.json` gives each journal's `stage` and `kind`; `kind: "blocked"` means the site explicitly refuses automation (401/403/412), so retrying will not help — use `--url` or curate manually instead.

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
- 图书馆杂志 uses the generic Magtech parser and has a 数字人文 section configured, but **the site's anti-bot pre-check returns 412 to every plain HTTP request** (not occasionally), so neither issue capture nor `capture-channel` currently works for it. Per the project's red lines we do **not** bypass that check; open the contents page in a browser yourself and pass it via `--url`, which may still fail. Its `historyUrlTemplate` contains `{volume}` while `volumeYearBase` / `volumeBase` are not configured, so locating archived issues by year is unavailable too — the error message now says so explicitly.
- 中国数字人文 contents pages often redirect to WeChat, so authors and abstracts may not be complete; the tool degrades to titles and links.
- 数位典藏与数位人文 pages that return platform promotional content are rejected by the quality checks; prefer the official TADH announcement page or a manually curated list.
- This tool **never** solves CAPTCHAs, bypasses logins, or substitutes for your institution's access rights.

## Feedback and help

Three issue templates cover three kinds of request. Picking the right one saves a round trip:

| What you need | Where to go |
|---------------|-------------|
| Report a bug: wrong capture result, command error, failed import, spreadsheet will not open | [Bug report](https://github.com/boringhxy/dh-gleaner/issues/new?template=bug_report.yml) |
| Ask for a journal that is not supported yet | [New journal source](https://github.com/boringhxy/dh-gleaner/issues/new?template=new_journal.yml) |
| Questions about installation, configuration, Zotero or MCP | [Question](https://github.com/boringhxy/dh-gleaner/issues/new?template=question.yml) |
| Security flaw: a path that could leak credentials, or a way around the import confirmation gate | Email `boringhxy@163.com`, see [SECURITY.md](SECURITY.md) — **do not** open a public issue |
| Contribute code or a new parser | [CONTRIBUTING.md](CONTRIBUTING.md), read the hard limits first |

When reporting a bug, three things help most — please attach all of them:

1. The output of `dhgleaner --version` — behaviour can differ a lot between versions.
2. The full output of `dhgleaner doctor`. It is already redacted and contains no API key. If the command will not install or run at all, paste the installation error instead.
3. The contents of `data/last_capture_status.json`. It records whether the capture succeeded, failed, or was marked `suspect`, whether the old `review.md` is still valid, and which stage each journal that returned nothing failed at.

**Never paste the contents of `config.local.json` or a Zotero API key into an issue.**

For a new journal source, the single most important field is **a real contents-page URL that opens without logging in** — how much work the integration takes depends almost entirely on whether the contents page can be read reliably. The template also asks about the platform (which decides whether one of the six existing parsers can be reused through configuration), whether DH articles sit in a standing section or are scattered across sections (which decides between `capture-channel`, `capture` and `harvest`), and whether abstracts and PDFs are reachable. That is exactly the information needed to write a parser; see `docs/sources.md`.

Things this tool does not do, and will not accept requests for: solving CAPTCHAs, simulating logins, getting around paywalls, bulk-downloading copyrighted full text. That line is written into CONTRIBUTING.md, and it is the precondition for this project being public at all.

## Development

```bash
git clone https://github.com/boringhxy/dh-gleaner.git
cd dh-gleaner
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,mcp]"      # mcp is optional: without it, 1 server-registration check is skipped

python -B -m unittest discover -s tests -v    # unit tests
ruff check .                                  # static checks
```

See `CONTRIBUTING.md` for contribution rules and hard limits, `SECURITY.md` for reporting vulnerabilities, and `CHANGELOG.md` for version history. Pull requests use the checklist in `.github/PULL_REQUEST_TEMPLATE.md`.

## License

MIT — see [LICENSE](LICENSE).
