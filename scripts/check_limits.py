#!/usr/bin/env python3
"""
Скрипт проверки лимита символов в файлах проекта (<= 10 000 символов).
Тихий по умолчанию (quiet by default): при отсутствии нарушений ничего не выводит.
"""

from pathlib import Path
import sys

TARGET_EXTS = {".py", ".md"}
LIMIT = 10_000
EXCLUDE_DIRS = {".git", ".agents"}
EXCEPTIONS = {"doc/ROADMAP.md"}

failed = False

for path in sorted(Path(".").rglob("*")):
    if path.suffix not in TARGET_EXTS:
        continue
    if any(part in EXCLUDE_DIRS for part in path.parts):
        continue

    posix_path = path.as_posix()
    if posix_path in EXCEPTIONS:
        continue

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as err:
        print(f"⚠️ Ошибка чтения {posix_path}: {err}", file=sys.stderr)
        failed = True
        continue

    char_count = len(content)
    if char_count > LIMIT:
        print(f"❌ {posix_path}: {char_count} символов (превышен лимит {LIMIT})")
        failed = True

sys.exit(1 if failed else 0)
