#!/usr/bin/env python3
# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
"""Fail if a tracked file contains a home directory path with a user name in it.

Usage: tests/check_paths.py        (run from anywhere inside the repository)
Looks at every file git tracks, and inside .tar.gz files. /home/USER is the allowed placeholder.
"""
import re
import subprocess
import sys
import tarfile
from pathlib import Path

PATTERN = re.compile(rb"/home/(?!USER\b)[A-Za-z0-9_.-]+")


def main():
    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True,
                               capture_output=True, text=True).stdout.strip())
    files = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True,
                           capture_output=True).stdout.split(b"\0")
    bad = []
    for name in filter(None, files):
        path = root / name.decode()
        if not path.is_file():
            continue
        blobs = [(str(path.relative_to(root)), path.read_bytes())]
        if path.name.endswith(".tar.gz"):
            with tarfile.open(path) as tar:
                blobs = [(f"{path.relative_to(root)}:{m.name}", tar.extractfile(m).read())
                         for m in tar.getmembers() if m.isfile()]
        for where, data in blobs:
            hits = sorted(set(PATTERN.findall(data)))
            if hits:
                bad.append(f"{where}: {b', '.join(hits[:3]).decode()}")
    for line in bad:
        print(line)
    print(f"{len(bad)} file(s) with a home directory path" if bad else "no home directory paths in tracked files")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
