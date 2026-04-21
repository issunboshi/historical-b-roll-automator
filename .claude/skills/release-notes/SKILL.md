---
name: release-notes
description: Draft release notes by diffing main against the last git tag, grouping commits by Conventional-Commit prefix (feat/fix/docs/refactor/etc.), and linking to PRs. Use when the user wants to publish a new release, cut a tag, or summarise recent changes — not for ad-hoc "what changed this week" questions.
disable-model-invocation: true
---

# release-notes

Draft human-readable release notes for this repo from git history. User-invoked only because tagging / publishing has side effects the user should authorise.

## When to use this

- User asks to "draft release notes", "prepare a release", "cut v0.x.0".
- After a cluster of merged PRs when the user wants a changelog entry.

Do NOT use this skill for:

- Generic "what did I do today" summaries (just read git log directly).
- In-progress feature summaries (use the PR description instead).

## Inputs

Ask the user for:

1. **Base ref** — default: the most recent `git tag` (use `git describe --tags --abbrev=0`). If no tags exist, fall back to 30 commits ago and flag that.
2. **Head ref** — default: `main` (or the current branch if not on main).
3. **Target version** — e.g. `v0.3.0`. If the user doesn't specify, propose one based on the highest-severity commit prefix (feat → minor bump, fix → patch bump, breaking → major).
4. **Output mode** — write to a file (typically `CHANGELOG.md` at the top, or `docs/releases/<version>.md`), or print to stdout for copy-paste into a GitHub Release.

## Steps

1. Run `git log <base>..<head> --pretty=format:'%H%x1f%s%x1f%b'` to get commit subjects + bodies separated by unit-separator.
2. Parse each subject for Conventional Commit prefix: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `chore`, `style`, `build`, `ci`. Strip the optional scope in parentheses (keep it to show alongside).
3. Group commits into sections, in this order (skip empty sections):
   - **Features** (`feat:`)
   - **Fixes** (`fix:`)
   - **Performance** (`perf:`)
   - **Refactors** (`refactor:`)
   - **Documentation** (`docs:`)
   - **Tooling** (`build:`, `ci:`, `chore:`)
   - **Other** (anything that did not match)
4. For each commit, extract the PR number if present (`(#123)` at end of subject) and link to it as `[#123](https://github.com/issunboshi/historical-b-roll-automator/pull/123)`.
5. Collapse merge commits (`Merge pull request #`) into the feature/fix they merged — prefer the PR commit body's first paragraph over the merge commit subject.
6. Detect breaking changes: commit body contains `BREAKING CHANGE:` or subject has `!` after the type. Surface these in a top-level **Breaking Changes** callout.
7. Write the notes using this shape:

   ```markdown
   ## <version> — <YYYY-MM-DD>

   ### Breaking Changes  (only if any)
   - ...

   ### Features
   - **scope:** subject — [#123](...)

   ### Fixes
   - ...
   ```

8. Show the draft to the user and wait for approval before writing to a file or proposing a `git tag` command.

## Output

- Draft markdown in the conversation for review.
- On approval: write to the chosen file (append to `CHANGELOG.md` or create `docs/releases/<version>.md`), and suggest (but do NOT run) `git tag -a <version> -m "..."` and `git push origin <version>`.

## Anti-patterns to avoid

- Do not tag or push without explicit user approval — these are durable, user-visible actions.
- Do not paraphrase commit subjects beyond stripping the prefix. The author's wording is the contract.
- Do not include co-author trailer lines or `Co-Authored-By` footers in the notes.
- Do not invent a version number the user didn't confirm.
