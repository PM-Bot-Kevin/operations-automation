#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = REPO_ROOT / "release-log" / "releases.jsonl"


def main() -> int:
    limit = 10
    if len(sys.argv) > 1:
        limit = max(int(sys.argv[1]), 1)
    if not LOG_PATH.exists():
        print("暂无发布历史。")
        return 0
    rows = [json.loads(line) for line in LOG_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        print("暂无发布历史。")
        return 0
    for row in rows[-limit:]:
        print(
            f"{row['time']} {row['action']} {row['releaseId']} "
            f"{row.get('summary', '')} [{row.get('result', '')}]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
