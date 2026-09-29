#!/usr/bin/env python3
"""
Скрипт проверки лимита символов в файлах проекта (<= 10 000 символов).
Тихий по умолчанию (quiet by default): при отсутствии нарушений ничего не выводит.
"""

import os
import sys
from pathlib import Path

GLOBAL_EXTS = {".py", ".md"}
WEB_EXTS = {".js", ".css", ".html"}
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
EXCEPTIONS = {
    "doc/ROADMAP.md",
    "doc/SOW/Тестовое задание/БТ СПА.md",
    "doc/SOW/Тестовое задание/Тестовое бэкенд СПА.md",
}


def should_check_path(path: Path, root: Path = ROOT) -> bool:
    """Определяет, подлежит ли файл проверке лимита символов."""
    if path.is_symlink():
        return False

    try:
        posix_path = path.relative_to(root).as_posix()
    except ValueError:
        return False

    if posix_path in EXCEPTIONS:
        return False

    if path.suffix in GLOBAL_EXTS:
        return True

    if path.suffix in WEB_EXTS and (posix_path == "web" or posix_path.startswith("web/")):
        return True

    return False


def collect_limit_violations(root: Path = ROOT) -> list[str]:
    """Сканирует проект и возвращает список сообщений о нарушениях лимита символов."""
    violations: list[str] = []
    for directory, subdirs, filenames in os.walk(root):
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
            if not should_check_path(path, root=root):
                continue

            posix_path = path.relative_to(root).as_posix()
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as err:
                violations.append(f"⚠️ Ошибка чтения {posix_path}: {err}")
                continue

            char_count = len(content)
            if char_count > LIMIT:
                violations.append(
                    f"❌ {posix_path}: {char_count} символов (превышен лимит {LIMIT})"
                )
    return violations


def main() -> int:
    violations = collect_limit_violations(ROOT)
    if violations:
        for item in violations:
            print(item, file=sys.stderr if item.startswith("⚠️") else sys.stdout)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
