#!/usr/bin/env python3
"""Check publishable files and optional Git history for common private data."""

import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CHECKS = {
    "personal home directory": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub access token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "portal URL argument": re.compile(r"[?&]Arg=(?!\.\.\.|ARG_PLACEHOLDER)[A-Za-z0-9%+/=_-]+"),
    "portal URL token": re.compile(r"djxkaiemglvvihukvsobuyiyby=(?!\.\.\.|TOKEN_PLACEHOLDER)[A-Za-z0-9%+/=_-]+"),
    "literal launch token": re.compile(r"--launch-token[ \t]+['\"](?!LAUNCH_TOKEN['\"]|\.\.\.['\"])[A-Za-z0-9+/=_-]{24,}['\"]"),
    "literal property ID": re.compile(r"--liegenschaft-id[ \t]+['\"]\d+['\"]"),
}
PRIVATE_DIRECTORIES = {"analysis", "trace", "exports", ".storage", "__pycache__"}
PRIVATE_SUFFIXES = {".har", ".log", ".csv", ".zip", ".pyc", ".pem", ".key"}


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def public_email(value):
    domain = value.rsplit("@", 1)[1].lower()
    return domain in {"example.com", "example.org", "example.net", "example.invalid", "users.noreply.github.com"} or domain.endswith(".invalid")


def inspect_content(label, data):
    """Report locations and categories only, never the potentially secret value."""
    issues = set()
    body = data.decode("utf-8", errors="replace")
    for number, line in enumerate(body.splitlines(), 1):
        for category, pattern in CHECKS.items():
            if pattern.search(line):
                issues.add(f"{label}:{number}: {category}")
        if any(not public_email(value) for value in EMAIL.findall(line)):
            issues.add(f"{label}:{number}: non-example email address")
    return issues


def inspect_file(label, path, data):
    name = PurePosixPath(path)
    if (set(name.parts) & PRIVATE_DIRECTORIES or name.suffix.lower() in PRIVATE_SUFFIXES
            or name.name in {".DS_Store", "initial.txt", ".env"}
            or name.name.startswith(("secrets.", "credentials."))
            or (name.name.startswith(".env.") and name.name != ".env.example")):
        return {f"{label}: private or generated file"}
    if name.suffix == ".png" and name.parent.as_posix() == "custom_components/uvi_service/brand":
        # Scan metadata in PNGs too; binary pixel data is not UTF-8 text.
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return {f"{label}: invalid brand PNG"}
        metadata = []
        offset = 8
        while offset + 12 <= len(data):
            size = int.from_bytes(data[offset:offset + 4], "big")
            kind = data[offset + 4:offset + 8]
            if kind not in {b"IHDR", b"IDAT", b"IEND", b"sRGB", b"gAMA", b"pHYs", b"cHRM", b"bKGD"}:
                metadata.append(data[offset + 8:offset + 8 + size])
            offset += size + 12
        if metadata:
            return {f"{label}: review nonessential PNG metadata"}
        return set()
    if b"\0" in data:
        return {f"{label}: unexpected binary file"}
    return inspect_content(label, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="Also inspect all Git refs and commit identities.")
    args = parser.parse_args()
    issues = set()
    paths = set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")) - {""}
    for path in paths:
        source = ROOT / path
        if source.is_symlink():
            issues.add(f"{path}: unexpected symlink")
        elif source.is_file():
            issues.update(inspect_file(path, path, source.read_bytes()))
    # Inspect the staged snapshot separately: it may differ from the worktree.
    for item in git("ls-files", "--stage", "-z").decode().split("\0"):
        if not item:
            continue
        metadata, path = item.split("\t", 1)
        mode, oid, stage = metadata.split()
        if mode not in {"100644", "100755"} or stage != "0":
            issues.add(f"index:{path}: unexpected file mode or unresolved merge")
        else:
            issues.update(inspect_file(f"index:{path}", path, git("cat-file", "blob", oid)))
    commits = git("rev-list", "--all").decode().splitlines() if args.history else []
    seen = set()
    for commit in commits:
        identity = git("show", "-s", "--format=%an <%ae>%n%cn <%ce>%n%B", commit)
        issues.update(inspect_content(f"commit:{commit[:8]}", identity))
    trees = [(commit[:8], commit) for commit in commits]
    if args.history:
        for ref in git("for-each-ref", "--format=%(objecttype) %(objectname) %(refname)").decode().splitlines():
            kind, oid, name = ref.split()
            if kind == "tree":
                trees.append((name, oid))
            elif kind not in {"commit", "tag"}:
                issues.add(f"{name}: unexpected ref type")
    for label, tree in trees:
        for entry in git("ls-tree", "-r", "-z", tree).decode().split("\0"):
            if not entry:
                continue
            metadata, path = entry.split("\t", 1)
            mode, kind, oid = metadata.split()
            if mode not in {"100644", "100755"} or kind != "blob":
                issues.add(f"{label}:{path}: unexpected file type")
            elif (path, oid) not in seen:
                seen.add((path, oid))
                issues.update(inspect_file(f"{label}:{path}", path, git("cat-file", "blob", oid)))
    for issue in sorted(issues):
        print(issue)
    if issues:
        print(f"Publication check failed: {len(issues)} finding(s).")
        return 1
    print(f"Publication check passed: {len(paths)} working files, staged snapshot, {len(commits)} historical commits, {len(trees) - len(commits)} tree refs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
