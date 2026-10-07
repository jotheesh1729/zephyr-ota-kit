#!/usr/bin/env python3
# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
"""Run cppcheck with its MISRA addon on this repository's own C files.

Usage: scripts/static_analysis.py BUILD_DIR [BUILD_DIR ...] [--accepted FILE] [--report FILE]

BUILD_DIR is an image build directory with a compile_commands.json, for example
build/v1.0.0/app. Only files of this repository are analysed (src/, app/, samples/, include/). Each file is
preprocessed by the build's own compiler with the build's own flags, then checked. Findings
located in Zephyr or MCUboot headers are dropped. A finding at one of our lines can still
come from the inside of a Zephyr macro used on that line.

Findings are reported by MISRA rule number only. The rule texts are licensed and are not
part of this repository or of cppcheck.

--accepted FILE lists "path:rule" pairs that are documented in docs/DEVIATIONS.md.
Exit code 1 if there is a finding that is not in that list.
This is a static analysis run, not a MISRA compliance claim. See docs/QUALITY.md.
"""
import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OURS = ("src/", "app/", "samples/", "include/")
# Rules this method cannot judge. The compiler's output is full of #line directives, which the
# addon counts as invalid directives (rule 20.13). The other preprocessor rules (20.x) and the
# rules about macro definitions cannot be checked on preprocessed code either, see docs/QUALITY.md.
NOT_CHECKABLE = {"MISRA 20.13"}


def own(path):
    try:
        rel = Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return None
    return rel if rel.startswith(OURS) else None


def analyse(build_dir):
    db = json.loads((Path(build_dir) / "compile_commands.json").read_text())
    entries = [e for e in db if own(e["file"])]
    if not entries:
        return set()
    tmp = Path(tempfile.mkdtemp())
    out = ""
    for n, e in enumerate(entries):
        # cppcheck's own preprocessor fails on Zephyr's devicetree macros. Let the real compiler
        # preprocess, with the exact flags of the build, and analyse the result. The #line
        # markers keep file and line numbers.
        words, cmd, skip = shlex.split(e["command"]), [], 0
        for w in words:
            if skip:
                skip -= 1
            elif w in ("-o", "-MT", "-MF"):
                skip = 1
            elif w not in ("-c", "-MD", "-MMD"):
                cmd.append(w)
        pre = tmp / f"{n}.c"
        subprocess.run(cmd + ["-E", "-o", str(pre)], cwd=e["directory"], check=True,
                       capture_output=True)
        # gcc writes line markers as '# 12 "file" 2'. Turn them into standard #line directives,
        # or the checker reports every one of them as an invalid directive.
        pre.write_text(re.sub(r'^# (\d+) ("[^"]*")[ \d]*$', r"#line \1 \2", pre.read_text(),
                              flags=re.M))
        run = subprocess.run(
            ["cppcheck", str(pre), "--language=c", "--addon=misra", "--inline-suppr", "-q",
             "--enable=warning,style,performance,portability",
             "--template={file}\t{line}\t{severity}\t{id}\t{message}"],
            capture_output=True, text=True, cwd=e["directory"])
        broken = [x for x in run.stderr.splitlines() if "\tsyntaxError\t" in x or "\tpreprocessorErrorDirective\t" in x]
        if broken:  # an analysis that did not parse the file must not look like a clean result
            raise SystemExit(f"cppcheck could not parse {e['file']}:\n  " + "\n  ".join(broken[:5]))
        out += run.stderr
    found = set()
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 5 and own(parts[0]):
            rule = parts[3].replace("misra-c2012-", "MISRA ")
            # the addon has no rule texts, its message is only a placeholder
            msg = "" if rule.startswith("MISRA") else parts[4]
            if rule not in NOT_CHECKABLE:
                found.add((own(parts[0]), int(parts[1]), rule, msg))
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("build_dirs", nargs="+")
    ap.add_argument("--accepted", help='file with accepted "path:rule" pairs')
    ap.add_argument("--report", help="write the findings to this file")
    args = ap.parse_args()

    findings = set()
    for b in args.build_dirs:
        findings |= analyse(b)
    accepted = set()
    if args.accepted:
        accepted = {x.split("#")[0].strip() for x in Path(args.accepted).read_text().splitlines()}
        accepted.discard("")

    lines, new = [], 0
    for path, line, rule, msg in sorted(findings):
        ok = f"{path}:{rule}" in accepted
        new += not ok
        lines.append(f"{'accepted' if ok else 'NEW     '}  {path}:{line}  {rule}{'  ' + msg if msg else ''}")
    by_rule = Counter(r for _, _, r, _ in findings)
    lines.append("")
    lines.append(f"{len(findings)} findings, {new} not accepted, in {len({p for p, *_ in findings})} files")
    lines += [f"  {n:3}  {rule}" for rule, n in sorted(by_rule.items(), key=lambda x: (-x[1], x[0]))]
    text = "\n".join(lines) + "\n"
    print(text, end="")
    if args.report:
        Path(args.report).write_text(text)
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
