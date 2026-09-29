"""Тесты CLI-команды подготовки демонстрационных данных."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.demo_data.__main__ import main, parse_as_of


def test_parse_as_of_validation() -> None:
    """Проверяет валидацию контрольной даты по Москве (задача 1.3)."""
    # 1. Валидный формат
    valid = parse_as_of("2026-09-29")
    assert valid == date(2026, 9, 29)

    # 2. Неверный формат даты
    with pytest.raises(ValueError, match="Неверный формат даты"):
        parse_as_of("invalid-date")
    with pytest.raises(ValueError, match="Неверный формат даты"):
        parse_as_of("2026-02-30")

    # 3. Будущая дата относительно текущей по Москве
    with patch("app.demo_data.__main__.today_in_moscow", return_value=date(2026, 9, 29)):
        with pytest.raises(ValueError, match="в будущем относительно текущей даты"):
            parse_as_of("2026-09-30")


def test_demo_data_cli_run(db_session: Session, capsys: pytest.CaptureFixture[str]) -> None:
    """Проверяет запуск команды через CLI (задача 1.3)."""
    session_maker = sessionmaker(bind=db_session.get_bind())

    with (
        patch("app.demo_data.__main__.check_database_readiness", return_value=(True, "available")),
        patch("app.demo_data.__main__.get_session_factory", return_value=session_maker),
    ):
        exit_code = main(["--as-of", "2026-09-29"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Демонстрационные данные успешно подготовлены" in captured.out
        assert "Контрольная дата (as_of): 2026-09-29" in captured.out
        assert "Объектов: 2" in captured.out
        assert "Товаров: 9" in captured.out
        assert "Складских движений: 105" in captured.out


def test_demo_data_cli_errors(capsys: pytest.CaptureFixture[str]) -> None:
    """Проверяет обработку ошибок CLI при некорректных аргументах (задача 1.3)."""
    # 1. Неверный формат даты
    code = main(["--as-of", "not-a-date"])
    assert code == 1
    err = capsys.readouterr().err
    assert "Неверный формат даты" in err

    # 2. Будущая дата
    with patch("app.demo_data.__main__.today_in_moscow", return_value=date(2026, 9, 29)):
        code = main(["--as-of", "2026-10-01"])
        assert code == 1
        err = capsys.readouterr().err
        assert "в будущем относительно текущей даты" in err

    # 3. База данных недоступна
    with patch(
        "app.demo_data.__main__.check_database_readiness",
        return_value=(False, "unavailable"),
    ):
        code = main(["--as-of", "2026-09-29"])
        assert code == 1
        err = capsys.readouterr().err
        assert "База данных недоступна" in err


def test_demo_data_cli_unexpected_error_masks_secrets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Проверяет сокрытие секретов при непредвиденной ошибке в CLI."""
    secret = "postgresql://user:super_secret_password@db.example.com/dbname"

    mock_factory = MagicMock()
    mock_factory.return_value.__enter__.return_value = MagicMock()

    with (
        patch("app.demo_data.__main__.check_database_readiness", return_value=(True, "available")),
        patch("app.demo_data.__main__.get_session_factory", return_value=mock_factory),
        patch("app.demo_data.__main__.logger") as mock_logger,
        patch(
            "app.demo_data.__main__.prepare_demo_data",
            side_effect=RuntimeError(f"connection failed: {secret}"),
        ),
    ):
        code = main(["--as-of", "2026-09-29"])
        assert code == 1
        captured = capsys.readouterr()
        assert secret not in captured.err
        assert "RuntimeError" in captured.err
        assert "Непредвиденная ошибка при подготовке данных" in captured.err
        mock_logger.exception.assert_called_once()
        log_args, _ = mock_logger.exception.call_args
        assert any(secret in str(arg) for arg in log_args)
