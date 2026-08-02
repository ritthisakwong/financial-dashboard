#!/usr/bin/env python3
"""
session_saver.py

End-of-session snapshot tool for this project.

  python session_saver.py
      Default action: back up every project file into a timestamped
      folder under .sessions/, write session metadata (git state,
      version, an auto-generated note), and regenerate PROJECT_INDEX.md.

  python session_saver.py --save "what you did this session"
      Same as above, but with an explicit note instead of an
      auto-generated one.

  python session_saver.py --index
      Regenerate PROJECT_INDEX.md only, without creating a snapshot.

  python session_saver.py --bump {major,minor,patch}
      Bump the version recorded in ./VERSION.

  python session_saver.py --push
      After saving/bumping, git add/commit/push so the snapshot and
      code changes actually sync to other machines. Combine with the
      flags above, e.g. `python session_saver.py --push`.
"""

import argparse
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SESSIONS_DIR = PROJECT_ROOT / ".sessions"
INDEX_PATH = PROJECT_ROOT / "PROJECT_INDEX.md"
VERSION_PATH = PROJECT_ROOT / "VERSION"

# Files/dirs to ignore when listing/backing up project contents
IGNORE = {".git", ".sessions", "__pycache__", ".DS_Store", "PROJECT_INDEX.md"}


def run_git(*args):
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip()
    except FileNotFoundError:
        return ""


# ─────────────────────────────────────────────
# VERSION
# ─────────────────────────────────────────────
def read_version():
    if VERSION_PATH.exists():
        v = VERSION_PATH.read_text().strip()
        if v:
            return v
    return "0.0.0"


def write_version(v):
    VERSION_PATH.write_text(v + "\n")


def bump_version(part):
    old_v = read_version()
    major, minor, patch = (int(x) for x in old_v.split("."))
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    new_v = f"{major}.{minor}.{patch}"
    write_version(new_v)
    return old_v, new_v


# ─────────────────────────────────────────────
# FILE LISTING / BACKUP
# ─────────────────────────────────────────────
def list_project_files():
    files = []
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(PROJECT_ROOT)
        if any(part in IGNORE for part in rel.parts):
            continue
        files.append(rel)
    return files


def auto_note():
    """Summarize commits since the last snapshot (or the last few, if this is the first one)."""
    sessions = load_sessions()
    since_ref = sessions[-1].get("git_head") if sessions else None
    if since_ref:
        log = run_git("log", f"{since_ref}..HEAD", "--pretty=%s")
    else:
        log = run_git("log", "-5", "--pretty=%s")
    subjects = [line for line in log.splitlines() if line.strip()]
    if not subjects:
        return "No new commits since last snapshot"
    return "; ".join(subjects[:8])


def save_session(note: str):
    folder_name = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_dir = SESSIONS_DIR / folder_name
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    backed_up = []
    for rel in list_project_files():
        src = PROJECT_ROOT / rel
        dest = snapshot_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        backed_up.append(str(rel))

    metadata = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "note": note,
        "version": read_version(),
        "git_branch": run_git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_head": run_git("rev-parse", "--short", "HEAD"),
        "git_status": run_git("status", "--porcelain"),
        "git_last_commit": run_git("log", "-1", "--pretty=%h %s"),
        "files_backed_up": backed_up,
    }
    (snapshot_dir / "session.json").write_text(json.dumps(metadata, indent=2))
    print(f"Saved session snapshot: {snapshot_dir.relative_to(PROJECT_ROOT)}  "
          f"({len(backed_up)} files, v{metadata['version']})")
    return snapshot_dir


def load_sessions():
    if not SESSIONS_DIR.exists():
        return []
    sessions = []
    for d in sorted(SESSIONS_DIR.iterdir()):
        meta_path = d / "session.json"
        if d.is_dir() and meta_path.exists():
            try:
                sessions.append(json.loads(meta_path.read_text()))
            except (json.JSONDecodeError, OSError):
                continue
    return sessions


# ─────────────────────────────────────────────
# PROJECT_INDEX.md
# ─────────────────────────────────────────────
def build_index():
    files = list_project_files()
    sessions = load_sessions()

    lines = []
    lines.append("# Project Index")
    lines.append("")
    lines.append(f"_Version: {read_version()} · Last generated: {datetime.now().isoformat(timespec='seconds')}_")
    lines.append("")

    lines.append("## Files")
    lines.append("")
    if files:
        for f in files:
            size = (PROJECT_ROOT / f).stat().st_size
            lines.append(f"- `{f}` ({size:,} bytes)")
    else:
        lines.append("_No files found._")
    lines.append("")

    lines.append("## Git")
    lines.append("")
    branch = run_git("rev-parse", "--abbrev-ref", "HEAD")
    last_commit = run_git("log", "-1", "--pretty=%h %s")
    if branch:
        lines.append(f"- Branch: `{branch}`")
    if last_commit:
        lines.append(f"- Last commit: {last_commit}")
    lines.append("")

    lines.append("## Session History")
    lines.append("")
    if sessions:
        for s in sessions:
            lines.append(f"- **{s.get('timestamp', '?')}** (v{s.get('version', '?')}) — {s.get('note', '(no note)')}")
            if s.get("git_last_commit"):
                lines.append(f"  - commit: {s['git_last_commit']}")
            n_files = len(s.get("files_backed_up", []))
            if n_files:
                lines.append(f"  - files backed up: {n_files}")
    else:
        lines.append("_No session snapshots recorded yet. Run `python session_saver.py` to create one._")
    lines.append("")

    return "\n".join(lines)


def write_index():
    INDEX_PATH.write_text(build_index())
    print(f"Wrote {INDEX_PATH.relative_to(PROJECT_ROOT)}")


# ─────────────────────────────────────────────
# GIT PUSH
# ─────────────────────────────────────────────
def push_changes():
    subprocess.run(["git", "add", "-A"], cwd=PROJECT_ROOT)
    staged = run_git("diff", "--cached", "--name-only")
    if staged:
        msg = f"Session snapshot {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        commit = subprocess.run(["git", "commit", "-m", msg], cwd=PROJECT_ROOT,
                                 capture_output=True, text=True)
        print(commit.stdout.strip() or commit.stderr.strip())
    else:
        print("Nothing new to commit.")

    push = subprocess.run(["git", "push"], cwd=PROJECT_ROOT, capture_output=True, text=True)
    if push.returncode == 0:
        print("Pushed to remote.")
    else:
        print("git push failed:\n" + push.stderr.strip())


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Session snapshot / index / version tool for this project")
    parser.add_argument("--save", nargs="?", const="", default=None, metavar="NOTE",
                         help="Create a full snapshot (backup + metadata). NOTE is optional; "
                              "auto-generated from recent commits if omitted.")
    parser.add_argument("--index", action="store_true",
                         help="Regenerate PROJECT_INDEX.md only, without creating a snapshot")
    parser.add_argument("--bump", choices=["major", "minor", "patch"],
                         help="Bump the version recorded in ./VERSION")
    parser.add_argument("--push", action="store_true",
                         help="git add/commit/push afterward so changes sync across machines")
    args = parser.parse_args()

    if args.bump:
        old_v, new_v = bump_version(args.bump)
        print(f"Version bumped: {old_v} -> {new_v}")

    if args.index and args.save is None:
        write_index()
    else:
        # Default behavior (bare invocation, or --save given): full snapshot + index refresh
        note = args.save if args.save else auto_note()
        save_session(note)
        write_index()

    if args.push:
        push_changes()


if __name__ == "__main__":
    main()
