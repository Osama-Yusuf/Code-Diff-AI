#!/usr/bin/env python3
# ai_diff.py — generate a single Markdown file with diffs for PR/commit/range/worktree
# No external dependencies. Python 3.8+.
import argparse
import os
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json

GITHUB_HOST = "github.com"
API_BASE = "https://api.github.com"

def run_git(args, repo=None, allow_fail=False):
    env = os.environ.copy()
    cmd = ["git", "-c", "core.quotepath=false", "-c", "color.ui=never"] + args
    try:
        out = subprocess.check_output(cmd, cwd=repo, stderr=subprocess.STDOUT)
        return out.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError as e:
        if allow_fail:
            return e.output.decode("utf-8", errors="replace")
        raise RuntimeError(f"git {' '.join(shlex.quote(a) for a in args)} failed:\n{e.output.decode()}")

def http_get(url, accept=None, token=None, timeout=20):
    headers = {"User-Agent": "ai-diff/1.0"}
    if accept:
        headers["Accept"] = accept
    # Prefer Bearer to support classic and fine-grained tokens
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except HTTPError as e:
        msg = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code} GET {url}\n{msg}")
    except URLError as e:
        raise RuntimeError(f"HTTP GET failed for {url}: {e}")

def detect_mode(target):
    """
    Returns (mode, details_dict)
    Modes: pr, commit_url, commit_sha, range, worktree
    """
    if target == "WORKTREE":
        return "worktree", {}
    if target == "UNSTAGED":
        return "unstaged", {}
    # GitHub PR URL
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)", target)
    if m:
        owner, repo, num = m.group(1), m.group(2), int(m.group(3))
        return "pr", {"owner": owner, "repo": repo, "number": num}
    # GitHub commit URL
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/commit/([0-9a-fA-F]{7,40})", target)
    if m:
        owner, repo, sha = m.group(1), m.group(2), m.group(3)
        return "commit_url", {"owner": owner, "repo": repo, "sha": sha}
    # Range like A..B or A...B
    if ".." in target:
        return "range", {"range": target}
    # Commit-ish SHA (7–40 hex)
    if re.fullmatch(r"[0-9a-fA-F]{7,40}", target):
        return "commit_sha", {"sha": target}
    # Fallback: treat as commit-ish (branch or tag) vs parent
    return "commit_sha", {"sha": target}

def safe_repo_name(repo_path):
    try:
        top = run_git(["rev-parse", "--show-toplevel"], repo=repo_path).strip()
        return os.path.basename(top)
    except Exception:
        return os.path.basename(repo_path or "")

def git_shortstat(repo, a=None, b=None, diff_opts=None):
    diff_opts = diff_opts or []
    args = ["diff", "--shortstat"] + diff_opts
    if a is not None and b is not None:
        args += [a, b]
    out = run_git(args, repo=repo, allow_fail=True).strip()
    return out or "(summary unavailable)"

def git_commits_table(repo, range_or_commit):
    # range_or_commit: "A..B" or sha
    try:
        if ".." in range_or_commit:
            log = run_git(["log", "--no-merges", "--pretty=format:%h %ad %an — %s", "--date=short", range_or_commit], repo=repo)
        else:
            log = run_git(["show", "--no-patch", "--pretty=format:%h %ad %an — %s", "--date=short", range_or_commit], repo=repo)
        return "\n".join(f"- {line}" for line in log.splitlines() if line.strip())
    except Exception:
        return ""

def build_markdown(title, repo_name, target_label, summary, diff_text, commits_md=None, prompt=True, truncated_note=None):
    parts = []
    parts.append(f"# AI Code Review: {title}\n")
    parts.append(f"**Repo:** {repo_name}\n**Target:** {target_label}\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    if commits_md:
        parts.append("\n## Commits\n")
        parts.append(commits_md + "\n")
    parts.append("\n## Summary of Changes\n")
    parts.append(summary + "\n")
    parts.append("\n## Diffs\n")

    # Break the unified diff into per-file sections
    per_files = split_diff_by_file(diff_text)
    if not per_files:
        # fallback: single block
        parts.append("```diff\n")
        parts.append(diff_text.rstrip() + "\n")
        parts.append("```\n")
    else:
        for filename, content in per_files:
            parts.append("diff\n")
            parts.append(f"{filename}\n")
            parts.append("```diff\n")
            parts.append(content.rstrip() + "\n")
            parts.append("```\n\n")

    if truncated_note:
        parts.append(f"\n> {truncated_note}\n")
    if prompt:
        parts.append(textwrap.dedent("""
        ---
        
        ## Prompt
        You are a senior code reviewer. Assess correctness, security, performance, and readability.
        Flag risky patterns, missing tests, unclear names, and potential regressions, give categories for e.g Critical, High, Medium, Low and give order of the issues.
        Suggest concrete fixes and test cases, also give categories for e.g Critical, High, Medium, Low and give order of the tests.
        Give a score for e.g 1-10 for the overall quality of the code.
        Give a summary of the changes in a few sentences.
        Lastly suggest a few features that could be added to the code or the project.
        """).lstrip())
    return "".join(parts)

def split_diff_by_file(diff_text):
    """
    Split a unified diff into per-file chunks.
    Returns list of tuples: (filename, chunk_text)
    """
    lines = diff_text.splitlines()
    files = []
    current = []
    current_header = None
    for line in lines:
        if line.startswith("diff --git "):
            if current:
                files.append((infer_filename(current_header, current), "\n".join(current)))
                current = []
            current_header = line
            continue
        if current_header is not None:
            current.append(line)
        else:
            # preamble before first diff --git; collect anyway
            current.append(line)
    if current:
        files.append((infer_filename(current_header, current), "\n".join(current)))
    return files

def infer_filename(header_line, chunk_lines):
    """Infer filename from diff chunk lines."""
    # Prefer +++ line (new file path), fallback to --- line, then diff header
    filename = None
    for ln in chunk_lines:
        if ln.startswith("+++ "):
            path = ln[4:].strip()
            if path != "/dev/null":
                filename = strip_prefix(path)
                break
    if not filename:
        for ln in chunk_lines:
            if ln.startswith("--- "):
                path = ln[4:].strip()
                if path != "/dev/null":
                    filename = strip_prefix(path)
                    break
    if not filename and header_line and header_line.startswith("diff --git "):
        try:
            parts = header_line.split()
            # format: diff --git a/path b/path
            if len(parts) >= 4:
                filename = strip_prefix(parts[3])
        except Exception:
            filename = "(unknown file)"
    return filename or "(unknown file)"

def strip_prefix(path):
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path

def truncate_text(text, max_lines):
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, None
    head = "\n".join(lines[:max_lines])
    note = f"Diff truncated after {max_lines} lines (total: {len(lines)}). Consider reviewing the remainder locally."
    return head, note

def get_parent(repo, sha):
    line = run_git(["rev-list", "--parents", "-n1", sha], repo=repo).strip()
    parts = line.split()
    return parts[1] if len(parts) > 1 else f"{sha}^"

def local_diff(repo, lhs, rhs, context, word_diff):
    args = ["diff", f"-U{context}", "--find-renames"]
    if word_diff:
        args.append("--word-diff=plain")
    args += [lhs, rhs]
    return run_git(args, repo=repo, allow_fail=True)

def worktree_diff(repo, context, word_diff):
    args = ["diff", f"-U{context}", "--find-renames", "HEAD"]
    if word_diff:
        args.append("--word-diff=plain")
    return run_git(args, repo=repo, allow_fail=True)

def unstaged_diff(repo, context, word_diff):
    args = ["diff", f"-U{context}", "--find-renames"]
    if word_diff:
        args.append("--word-diff=plain")
    return run_git(args, repo=repo, allow_fail=True)

def parse_github_repo_from_url(url):
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)", url)
    if not m:
        raise ValueError(f"Not a GitHub URL: {url}")
    return m.group(1), re.sub(r"\.git$", "", m.group(2))

def fetch_pr_bundle(owner, repo, number, token=None):
    # Metadata: additions, deletions, changed_files
    meta_bytes = http_get(f"{API_BASE}/repos/{owner}/{repo}/pulls/{number}", accept="application/vnd.github+json", token=token)
    meta = json.loads(meta_bytes.decode("utf-8", errors="replace"))
    additions = meta.get("additions")
    deletions = meta.get("deletions")
    changed = meta.get("changed_files")
    title = meta.get("title") or f"PR #{number}"
    # Commits list with pagination (per_page=100)
    commits_md = []
    page = 1
    while True:
        commits_url = f"{API_BASE}/repos/{owner}/{repo}/pulls/{number}/commits?per_page=100&page={page}"
        commits_bytes = http_get(commits_url, accept="application/vnd.github+json", token=token)
        page_items = json.loads(commits_bytes.decode("utf-8", errors="replace"))
        if not page_items:
            break
        for c in page_items:
            sha = c.get("sha", "")[:7]
            commit = c.get("commit", {})
            msg = (commit.get("message") or "").splitlines()[0]
            author = (commit.get("author") or {}).get("name") or ""
            date = (commit.get("author") or {}).get("date") or ""
            if date:
                date = date.split("T")[0]
            commits_md.append(f"- {sha} {date} {author} — {msg}")
        if len(page_items) < 100:
            break
        page += 1
    commits_md = "\n".join(commits_md)
    # Diff
    diff_bytes = http_get(f"{API_BASE}/repos/{owner}/{repo}/pulls/{number}", accept="application/vnd.github.v3.diff", token=token)
    diff_text = diff_bytes.decode("utf-8", errors="replace")
    # Summary line
    summary = f"Files changed: {changed}, insertions: {additions}, deletions: {deletions}"
    return title, summary, diff_text, commits_md

def fetch_commit_bundle(owner, repo, sha, token=None):
    meta_bytes = http_get(f"{API_BASE}/repos/{owner}/{repo}/commits/{sha}", accept="application/vnd.github+json", token=token)
    meta = json.loads(meta_bytes.decode("utf-8", errors="replace"))
    author = ((meta.get("commit") or {}).get("author") or {}).get("name")
    date = ((meta.get("commit") or {}).get("author") or {}).get("date") or ""
    if date:
        date = date.split("T")[0]
    message = ((meta.get("commit") or {}).get("message") or "").splitlines()[0]
    additions = meta.get("stats", {}).get("additions")
    deletions = meta.get("stats", {}).get("deletions")
    changed = meta.get("files")
    changed_files = len(changed) if isinstance(changed, list) else None
    title = f"Commit {sha[:7]} — {message}"
    summary = f"Files changed: {changed_files}, insertions: {additions}, deletions: {deletions}"
    diff_bytes = http_get(f"{API_BASE}/repos/{owner}/{repo}/commits/{sha}", accept="application/vnd.github.v3.diff", token=token)
    diff_text = diff_bytes.decode("utf-8", errors="replace")
    commits_md = f"- {sha[:7]} {date} {author} — {message}"
    return title, summary, diff_text, commits_md

def main():
    p = argparse.ArgumentParser(description="Generate a single Markdown file for AI code review from PR/commit/range/worktree.")
    p.add_argument("target", help="PR URL | commit URL | commit-ish | range (A..B or A...B) | WORKTREE | UNSTAGED")
    p.add_argument("-r", "--repo", default=".", help="Local repo path (default: current dir). Required for local ranges/commits/WORKTREE.")
    p.add_argument("-o", "--output", default=None, help="Output Markdown file (default: auto-named per target)")
    p.add_argument("-c", "--context", type=int, default=3, help="Diff context lines (default: 3)")
    p.add_argument("-w", "--word-diff", action="store_true", help="Use git --word-diff=plain for local diffs")
    p.add_argument("--max-lines", type=int, default=5000, help="Truncate diff after N lines (default: 5000)")
    p.add_argument("--token", default=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"), help="GitHub token for private repos/APIs (default: $GITHUB_TOKEN or $GH_TOKEN)")
    p.add_argument("--no-prompt", action="store_true", help="Omit the helper prompt section")
    args = p.parse_args()

    mode, details = detect_mode(args.target)
    repo_name = safe_repo_name(args.repo)
    title = ""
    summary = ""
    diff_text = ""
    commits_md = ""
    truncated_note = None
    output_path = args.output

    if mode == "pr":
        owner, repo, num = details["owner"], details["repo"], details["number"]
        title, summary, diff_text, commits_md = fetch_pr_bundle(owner, repo, num, token=args.token)
        target_label = f"https://{GITHUB_HOST}/{owner}/{repo}/pull/{num}"
        if output_path is None:
            output_path = f"./diff-pr-{num}.md"
    elif mode == "commit_url":
        owner, repo, sha = details["owner"], details["repo"], details["sha"]
        title, summary, diff_text, commits_md = fetch_commit_bundle(owner, repo, sha, token=args.token)
        target_label = f"https://{GITHUB_HOST}/{owner}/{repo}/commit/{sha}"
        if output_path is None:
            output_path = f"./diff-commit-{sha[:7]}.md"
    elif mode == "commit_sha":
        sha = details["sha"]
        parent = get_parent(args.repo, sha)
        diff_text = local_diff(args.repo, parent, sha, args.context, args.word_diff)
        title = f"Commit {sha[:7]}"
        summary = git_shortstat(args.repo, parent, sha, [f"-U{args.context}", "--find-renames"])
        commits_md = git_commits_table(args.repo, sha)
        target_label = sha
        if output_path is None:
            try:
                resolved = run_git(["rev-parse", "--verify", sha], repo=args.repo).strip()
                short = resolved[:7]
            except Exception:
                short = sha[:7]
            output_path = f"./diff-commit-{short}.md"
    elif mode == "range":
        rng = details["range"]
        if "..." in rng:
            cmd = ["diff", f"-U{args.context}", "--find-renames"]
            if args.word_diff:
                cmd.append("--word-diff=plain")
            cmd.append(rng)
            diff_text = run_git(cmd, repo=args.repo, allow_fail=True)
        else:
            a, b = rng.split("..", 1)
            diff_text = local_diff(args.repo, a, b, args.context, args.word_diff)
        title = f"Range {rng}"
        # shortstat needs the range as-is (without -U)
        summary = git_shortstat(args.repo, None, None, [])  # fallback if next line fails
        try:
            summary = run_git(["diff", "--shortstat"] + rng.split(), repo=args.repo, allow_fail=True).strip() or summary
        except Exception:
            pass
        commits_md = git_commits_table(args.repo, rng)
        target_label = rng
    elif mode == "worktree":
        diff_text = worktree_diff(args.repo, args.context, args.word_diff)
        title = "Working tree vs HEAD"
        try:
            summary = run_git(["diff", "--shortstat", "HEAD"], repo=args.repo, allow_fail=True).strip() or "(summary unavailable)"
        except Exception:
            summary = "(summary unavailable)"
        commits_md = ""
        target_label = "WORKTREE"
    elif mode == "unstaged":
        diff_text = unstaged_diff(args.repo, args.context, args.word_diff)
        title = "Unstaged changes (working tree vs index)"
        try:
            summary = run_git(["diff", "--shortstat"], repo=args.repo, allow_fail=True).strip() or "(summary unavailable)"
        except Exception:
            summary = "(summary unavailable)"
        commits_md = ""
        target_label = "UNSTAGED"
    else:
        raise RuntimeError(f"Unknown mode: {mode}")

    # Fallback default output path for modes without a specific rule
    if output_path is None:
        output_path = "./ai-review.md"

    # Truncate if needed
    if args.max_lines and args.max_lines > 0:
        diff_text, truncated_note = truncate_text(diff_text, args.max_lines)

    md = build_markdown(
        title=title,
        repo_name=repo_name,
        target_label=target_label,
        summary=summary,
        diff_text=diff_text,
        commits_md=commits_md if commits_md.strip() else None,
        prompt=(not args.no_prompt),
        truncated_note=truncated_note
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"✅ Wrote {output_path}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
