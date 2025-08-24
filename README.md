## DiffAI: One file to rule your diffs (and print them nicely)

You have code changes. You want one chunky Markdown file with all the diffs, a tidy summary, and a ready-to-paste prompt for an AI code review. Enter `ai-diff.py`: a single, dependency-free Python script that fetches diffs from GitHub (PRs, commits) or from your local repo (commits, ranges, working tree) and prints them into one neat Markdown.

Yes, it's just one file. No, it doesn't need fancy installs. You're welcome.

### Highlights
- **Works with:** GitHub PR URLs, commit URLs, commit SHAs/branches/tags, ranges (`A..B`, `A...B`), or your current working tree (`WORKTREE`).
- **Output:** a single Markdown file with a title, summary, optional commit list, and a big fenced `diff` block.
- **No dependencies:** pure Python 3.8+ and `git`. That's it.
- **Tokens:** Private PRs/commits? Use `--token` or set `GITHUB_TOKEN`/`GH_TOKEN`.

### Requirements
- Python 3.8+
- `git` on your PATH
- Internet access for PR/commit URLs (shocking)

### Install (if you can even call it that)
Option A: Run it directly.
```bash
python3 ai-diff.py --help
```

Option B: Make it executable because you enjoy convenience.
```bash
chmod +x ai-diff.py
./ai-diff.py --help
```

### What it generates
The Markdown includes:
- **Header:** repo name, target, timestamp
- **Commits:** for PRs/ranges/commit views (when applicable)
- **Summary of Changes:** `git --shortstat` or GitHub stats
- **Diffs:** inside a ```diff fenced block
- **Prompt:** a prewritten “do an AI review” prompt (unless you say `--no-prompt`)

Example filenames:
- PR: `diff-pr-123.md`
- Commit: `diff-commit-abc1234.md`
- Fallback: `ai-review.md`

### Modes (aka what you can point it at)
Use exactly one target argument:
- **PR URL:** `https://github.com/owner/repo/pull/123`
- **Commit URL:** `https://github.com/owner/repo/commit/abc1234`
- **Commit-ish:** `abc1234` or `main` or `v1.2.3`
- **Range:** `A..B` (diff B vs A) or `A...B` (three-dot merge-base magic)
- **Working tree:** `WORKTREE` (everything vs `HEAD`, i.e., staged + unstaged)
- **Only unstaged:** `UNSTAGED` (just the stuff you haven't added yet)

Note: This script supports `github.com` (not GitHub Enterprise). If you paste an Enterprise URL, it will look at you politely and do nothing helpful.

### Options (with bite-sized examples)
All options work with any mode unless noted.

- **`-r, --repo PATH`**: Local repo path. Default: `.`
  - Useful for local commits/ranges/worktree.
  ```bash
  python3 ai-diff.py abc1234 -r /path/to/repo
  ```

- **`-o, --output FILE`**: Output Markdown file.
  ```bash
  python3 ai-diff.py WORKTREE -o review-today.md
  ```

- **`-c, --context N`**: Diff context lines (default 3).
  ```bash
  python3 ai-diff.py main..feature -r . -c 10
  ```

- **`-w, --word-diff`**: Use `git --word-diff=plain` for local diffs (great for prose-y changes).
  ```bash
  python3 ai-diff.py main..feature -r . -w
  ```

- **`--max-lines N`**: Truncate diff after N lines (default 5000). Adds a note when truncated.
  ```bash
  python3 ai-diff.py main...feature --max-lines 1200
  ```

- **`--token TOKEN`**: GitHub token for private repos/APIs.
  - Or set env var: `GITHUB_TOKEN` or `GH_TOKEN`.
  ```bash
  python3 ai-diff.py https://github.com/owner/repo/pull/123 --token "$GITHUB_TOKEN"
  ```

- **`--no-prompt`**: Skip the built-in AI-review prompt at the bottom.
  ```bash
  python3 ai-diff.py https://github.com/owner/repo/commit/abc1234 --no-prompt
  ```

### Usage by example (copy-paste buffet)

#### 1) PR URL (GitHub)
Fetches metadata, commit list, and the PR diff via GitHub API.
```bash
python3 ai-diff.py https://github.com/owner/repo/pull/123 --token "$GITHUB_TOKEN"
```
Output: `diff-pr-123.md`

#### 2) Commit URL (GitHub)
Same idea, but for a single commit.
```bash
python3 ai-diff.py https://github.com/owner/repo/commit/abc1234 --token "$GITHUB_TOKEN"
```
Output: `diff-commit-abc1234.md`

#### 3) Commit-ish (local)
Compares a commit to its parent locally. No internet fame required.
```bash
python3 ai-diff.py abc1234 -r /path/to/repo
```
Output: `diff-commit-abc1234.md`

#### 4) Range (two-dot)
Classic “what changed from A to B”.
```bash
python3 ai-diff.py A..B -r .
```

#### 5) Range (three-dot)
Compares B to the merge-base with A (handy for PR-like diffs).
```bash
python3 ai-diff.py main...feature-branch -r .
```

#### 6) Working tree (your current mess)
Diff your uncommitted changes vs `HEAD`.
```bash
python3 ai-diff.py WORKTREE -r .
```

#### 7) Only unstaged changes (what you haven't added yet)
Diff your working tree against the index (no staged changes included).
```bash
python3 ai-diff.py UNSTAGED -r .
```

### What the script actually does (under the hood, but not boring)
- Figures out the **mode** from your target (PR URL, commit URL, sha/range, or `WORKTREE`).
- For GitHub URLs: calls the GitHub API for the stats/commits and the `.diff` view for the actual diff.
- For local stuff: runs `git diff` with rename detection and your context/word-diff choices.
- Builds a Markdown with:
  - A title like “AI Code Review: Commit abc1234”
  - Repo name (from your local repo path)
  - Optional commit list
  - A **Summary of Changes** (files changed, insertions, deletions)
  - The full diff inside a ```diff code fence
  - A helpful prompt for your favorite AI to review the changes (unless you say `--no-prompt`)

### Tips, quirks, gotchas
- Private PRs/commits? Use `--token` or set `GITHUB_TOKEN`/`GH_TOKEN`.
- Big diffs? Use `--max-lines` to keep your editor alive.
- Want more context around changes? Bump `-c`.
- Word-by-word highlighting? Add `-w` (local diffs only).
- Not in the right repo? Point at it with `-r /path/to/repo`.
- GitHub Enterprise? Not supported. Sorry. This is a humble script, not a SaaS platform.

### Troubleshooting (a.k.a. Why is this yelling at me?)
- “HTTP 404/401 for PR/commit URL”
  - You probably need a token or the repo is private.
- “Rate limited by GitHub”
  - Use a token, or wait out your GitHub time-out corner.
- “git diff failed”
  - Check your `-r` path, your commit/range spelling, and that it’s a real Git repo.
- Output empty or tiny?
  - Maybe you diffed identical things. It happens to the best of us.

### FAQ
- Can I run it in CI?
  - Yes. It’s a single script. Emit Markdown. Archive it as an artifact. Boom.
- Does it modify my repo?
  - No. It only reads diffs and writes one Markdown file.
- Can I change the output filename?
  - `-o review.md`. Live your truth.
