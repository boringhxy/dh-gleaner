# Initial release fixes implementation plan

Goal: fix the six reproduced bugs and clarify runtime directory ownership without changing the literature-selection workflow.

Base: c9aa2658f9eb24cae57ed13486400e3d2bf7e0bc; GitHub main and local main match.

Constraints: Python >=3.10; no new runtime dependencies; no real Zotero writes; keep existing explicit data directories and legacy dh-gleaner data working; preserve current public command names.

1. Add regression tests in tests/test_release_regressions.py for credential backup exclusion, failed/partial pending saves, stable Excel batches after import, completed article state, conflicting DOI metadata, dry-run disk isolation, and unrelated working directories. Run them against unchanged production code and record expected failures.
2. Repair persistence in service.py and .gitignore: stage and atomically replace pending artifacts, propagate failures, preserve capture metadata on status updates, protect credential backups. Update CLI/MCP consumers to report failed saves and distinguish remote success from local-save failure.
3. Repair duplicate detection and article selection: conflicting DOI or bibliographic identity cannot match by title alone; completed article states/keys survive selection and skip operations; only newly skipped records are counted.
4. Make StateManager optionally read-only, including corrupt-state loading; use it for capture/harvest previews, discover without record and doctor checks. Repair preview messages and MCP capture limits. Tighten legacy-directory detection to tool-specific files/configuration while retaining explicit overrides.
5. Stub JSON discovery requests in existing tests. Update configuration/data-directory docs, MCP tool counts, exit codes and changelog. No large module reshuffle.
6. Run complete offline suite, lint, build/install smoke if available; independently review diff and resolve actionable findings. Apply verified patch to original checkout, verify again, and publish a reviewable GitHub branch/PR if connection permits. Never overwrite concurrent changes.

For each production behavior: add failing test first, run it, implement the smallest fix, then rerun targeted tests before full verification.
