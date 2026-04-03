#!/usr/bin/env python3
"""Remove orphan git worktrees from .claude/worktrees/ after evaluation.

Prevents accumulation of 6+ worktrees per session. Cleans up directories
and runs `git worktree prune` afterward.

Stdlib-only — no langsmith dependency.

Usage:
    # Dry run — show what would be removed
    python3 cleanup_worktrees.py --dry-run

    # Remove all worktrees
    python3 cleanup_worktrees.py

    # Keep specific worktrees by name
    python3 cleanup_worktrees.py --keep winner-v003 candidate-v004a

    # Specify project directory
    python3 cleanup_worktrees.py --dir /path/to/project --dry-run
"""

import argparse
import os
import shutil
import subprocess
import sys


WORKTREE_SUBDIR = os.path.join(".claude", "worktrees")


def find_worktrees(base_dir):
    """Find all directories under .claude/worktrees/ in the given project.

    Returns a list of absolute paths to worktree directories.
    """
    worktrees_root = os.path.join(base_dir, WORKTREE_SUBDIR)
    if not os.path.isdir(worktrees_root):
        return []
    entries = []
    for name in sorted(os.listdir(worktrees_root)):
        full = os.path.join(worktrees_root, name)
        if os.path.isdir(full):
            entries.append(full)
    return entries


def remove_worktree(path, dry_run=False):
    """Remove a single worktree directory.

    Tries `git worktree remove --force` first. If that fails (e.g. the
    worktree wasn't registered with git), falls back to shutil.rmtree.

    Returns a dict with keys: path, method, success, error.
    """
    result = {"path": path, "method": None, "success": False, "error": None}

    if dry_run:
        result["method"] = "dry-run"
        result["success"] = True
        return result

    # Try git worktree remove --force
    try:
        proc = subprocess.run(
            ["git", "worktree", "remove", "--force", path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            result["method"] = "git worktree remove"
            result["success"] = True
            return result
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Fallback: shutil.rmtree
    try:
        shutil.rmtree(path)
        result["method"] = "shutil.rmtree"
        result["success"] = True
    except OSError as exc:
        result["method"] = "shutil.rmtree"
        result["error"] = str(exc)

    return result


def prune_worktrees(project_dir):
    """Run `git worktree prune` to clean up stale worktree bookkeeping."""
    try:
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Remove orphan git worktrees from .claude/worktrees/"
    )
    parser.add_argument(
        "--dir",
        default=".",
        help="Project directory (default: current directory)",
    )
    parser.add_argument(
        "--keep",
        nargs="*",
        default=[],
        metavar="NAME",
        help="Worktree directory names to keep (basenames, not full paths)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without actually removing",
    )
    args = parser.parse_args()

    project_dir = os.path.abspath(args.dir)
    keep_set = set(args.keep)

    worktrees = find_worktrees(project_dir)
    if not worktrees:
        print(f"No worktrees found under {os.path.join(project_dir, WORKTREE_SUBDIR)}")
        return

    # Partition into keep / remove
    to_remove = []
    to_keep = []
    for wt in worktrees:
        name = os.path.basename(wt)
        if name in keep_set:
            to_keep.append(wt)
        else:
            to_remove.append(wt)

    if to_keep:
        print(f"Keeping {len(to_keep)} worktree(s): {', '.join(os.path.basename(w) for w in to_keep)}")

    if not to_remove:
        print("Nothing to remove.")
        return

    action = "Would remove" if args.dry_run else "Removing"
    print(f"{action} {len(to_remove)} worktree(s):\n")

    results = []
    for wt in to_remove:
        res = remove_worktree(wt, dry_run=args.dry_run)
        results.append(res)
        name = os.path.basename(wt)
        if res["success"]:
            method = f" ({res['method']})" if res["method"] != "dry-run" else ""
            print(f"  [ok] {name}{method}")
        else:
            print(f"  [FAIL] {name} — {res['error']}")

    # Prune stale worktree references
    if not args.dry_run:
        prune_worktrees(project_dir)
        print("\nRan `git worktree prune`.")

    failed = [r for r in results if not r["success"]]
    if failed:
        print(f"\n{len(failed)} removal(s) failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
