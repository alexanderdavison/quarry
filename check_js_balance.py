#!/usr/bin/env python3
"""String-aware JS brace/paren/bracket balance check for the Quarry SPA.

Usage: python3 check_js_balance.py index.html
Prints BALANCED or the first structural error. Exits 0/1.
"""
import re
import sys


def extract_scripts(path):
    src = open(path).read()
    starts = [m.start() for m in re.finditer(r"<script>", src)]
    ends = [m.start() for m in re.finditer(r"</script>", src)]
    if len(starts) != 1 or len(ends) != 1:
        print(f"ERROR: expected exactly one <script> block, found {len(starts)} start / {len(ends)} end")
        sys.exit(1)
    return src[starts[0] + len("<script>"):ends[0]]


def check(script):
    depth_brace = depth_paren = depth_bracket = 0
    i = 0
    while i < len(script):
        c = script[i]
        if c == "/" and i + 1 < len(script) and script[i + 1] == "/":
            i = script.find("\n", i)
            if i == -1:
                break
            i += 1
            continue
        if c == "/" and i + 1 < len(script) and script[i + 1] == "*":
            end = script.find("*/", i + 2)
            if end >= 0:
                i = end + 2
                continue
        if c == "/" and i + 1 < len(script) and script[i + 1] not in ("/", "*"):
            j = i + 1
            while j < len(script):
                if script[j] == "\\":
                    j += 2
                    continue
                if script[j] == "/":
                    break
                j += 1
            if j < len(script):
                i = j + 1
                continue
        if c in ("'", '"', "`"):
            q = c
            i += 1
            while i < len(script):
                if script[i] == "\\":
                    i += 2
                    continue
                if script[i] == q:
                    break
                if script[i] == "\n" and q != "`":
                    print("ERROR: unterminated string")
                    sys.exit(1)
                i += 1
        elif c == "{":
            depth_brace += 1
        elif c == "}":
            depth_brace -= 1
            if depth_brace < 0:
                print("ERROR: unbalanced } at offset", i)
                sys.exit(1)
        elif c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren -= 1
            if depth_paren < 0:
                print("ERROR: unbalanced ) at offset", i)
                sys.exit(1)
        elif c == "[":
            depth_bracket += 1
        elif c == "]":
            depth_bracket -= 1
            if depth_bracket < 0:
                print("ERROR: unbalanced ] at offset", i)
                sys.exit(1)
        i += 1
    if depth_brace == 0 and depth_paren == 0 and depth_bracket == 0:
        print("BALANCED")
        sys.exit(0)
    print(f"ERROR: depth brace={depth_brace} paren={depth_paren} bracket={depth_bracket}")
    sys.exit(1)


if __name__ == "__main__":
    check(extract_scripts(sys.argv[1]))
