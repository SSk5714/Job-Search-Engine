"""Emit the tail of log files as GitHub annotations, so failures are readable through the API
(job logs are served from blob storage that some environments cannot reach)."""

import sys
from pathlib import Path

LIMITS = {0: 80, 1: 160}  # lines from the end of each file

for i, name in enumerate(sys.argv[1:]):
    p = Path(name)
    if not p.exists():
        continue
    lines = p.read_text(errors="replace").splitlines()[-LIMITS.get(i, 100):]
    text = "\n".join(lines)
    for n, start in enumerate(range(0, len(text), 3500)):
        chunk = text[start:start + 3500].replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        print(f"::error title={p.name} part {n + 1}::{chunk}")
