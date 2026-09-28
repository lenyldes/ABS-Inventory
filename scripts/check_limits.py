#!/usr/bin/env python3
"""
Скрипт проверки лимита символов в файлах проекта (<= 10 000 символов).
Тихий по умолчанию (quiet by default): при отсутствии нарушений ничего не выводит.
"""

import os
import sys
from pathlib import Path

TARGET_EXTS = {".py", ".md"}
LIMIT = 10_000
ROOT = Path(__file__).resolve().parents[1]
EXCLUDE_DIRS = {
    ".git",
    ".agents",
    ".codex",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".tox",
    ".nox",
    "node_modules",
    "vendor",
    "build",
    "dist",
}
EXCEPTIONS = {"doc/ROADMAP.md"}

failed = False

for directory, subdirs, filenames in os.walk(ROOT):
    # Не заходим в зависимости и служебные каталоги, включая venv с любым именем.
    subdirs[:] = sorted(
        name
        for name in subdirs
        if name not in EXCLUDE_DIRS
        and not (Path(directory) / name / "pyvenv.cfg").is_file()
        and not (Path(directory) / name).is_symlink()
    )
    for filename in sorted(filenames):
        path = Path(directory) / filename
        if path.suffix not in TARGET_EXTS or path.is_symlink():
            continue

        posix_path = path.relative_to(ROOT).as_posix()
        if posix_path in EXCEPTIONS:
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as err:
            print(f"⚠️ Ошибка чтения {posix_path}: {err}", file=sys.stderr)
            failed = True
            continue

        char_count = len(content)
        if char_count > LIMIT:
            print(f"❌ {posix_path}: {char_count} символов (превышен лимит {LIMIT})")
            failed = True

sys.exit(1 if failed else 0)
