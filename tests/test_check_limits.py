"""Проверки границ лимита и исключения сторонних файлов."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "check_limits.py"


@pytest.fixture
def project(tmp_path):
    """Отдельный проект для проверки скрипта без изменения репозитория."""
    root = tmp_path / "project"
    (root / "scripts").mkdir(parents=True)
    shutil.copyfile(SOURCE, root / "scripts" / "check_limits.py")
    return root


def run_check(project):
    """Запускаем из другой папки: корень должен определяться по скрипту."""
    return subprocess.run(
        [sys.executable, str(project / "scripts" / "check_limits.py")],
        cwd=project.parent,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("size, code", [(10_000, 0), (10_001, 1)])
def test_character_limit(project, size, code):
    """Считаются символы кириллицы, а не байты UTF-8; новые файлы проверяются."""
    (project / "example.md").write_text("я" * size, encoding="utf-8")
    result = run_check(project)
    assert result.returncode == code
    if code:
        assert "example.md: 10001" in result.stdout
    else:
        assert result.stdout == result.stderr == ""


@pytest.mark.parametrize(
    "folder", [".venv", "node_modules", ".agents", ".codex", "build", "vendor"]
)
def test_dependencies_are_excluded(project, folder):
    """Большие сторонние файлы не нарушают лимит проекта."""
    target = project / folder / "external.py"
    target.parent.mkdir()
    target.write_text("#" * 10_001, encoding="utf-8")
    result = run_check(project)
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""


def test_custom_venv_and_roadmap_are_excluded(project):
    """Учитываются venv с произвольным именем и исключение для дорожной карты."""
    environment = project / "custom_environment"
    environment.mkdir()
    (environment / "pyvenv.cfg").write_text("", encoding="utf-8")
    (environment / "external.py").write_text("#" * 10_001, encoding="utf-8")
    (project / "doc").mkdir()
    (project / "doc" / "ROADMAP.md").write_text("я" * 10_001, encoding="utf-8")
    assert run_check(project).returncode == 0


def test_invalid_utf8_is_reported(project):
    """Повреждённая кодировка не должна молча игнорироваться."""
    (project / "broken.md").write_bytes(b"\xff")
    result = run_check(project)
    assert result.returncode == 1
    assert "Ошибка чтения broken.md" in result.stderr
