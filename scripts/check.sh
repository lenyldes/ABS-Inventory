#!/usr/bin/env bash
set -uo pipefail

# Единая точка входа для всех обязательных проверок проекта.
cd "$(dirname "$0")/.." || exit 1

CHECK_PROJECT="abs_checks_$$"
export COMPOSE_PROJECT_NAME="${CHECK_PROJECT}"
export ABS_DB_CONTAINER="${CHECK_PROJECT}_db"
export ABS_TEST_CONTAINER="${CHECK_PROJECT}_test"
export POSTGRES_PORT=0

CHECK_LOG=$(mktemp) || exit 1
FAILED=0

if ! docker info >"${CHECK_LOG}" 2>&1; then
    printf 'ОШИБКА: нет доступа к Docker API\n' >&2
    tail -n 5 "${CHECK_LOG}" >&2
    rm -f "${CHECK_LOG}"
    exit 1
fi

cleanup() {
    if ! docker compose down -v --remove-orphans >"${CHECK_LOG}" 2>&1; then
        printf 'ОШИБКА: очистка проверочного Compose-проекта\n' >&2
        tail -n 30 "${CHECK_LOG}" >&2
        FAILED=1
    fi
    rm -f "${CHECK_LOG}"
}

run_check() {
    local name="$1"
    shift
    if "$@" >"${CHECK_LOG}" 2>&1; then
        return
    fi

    printf 'ОШИБКА: %s\n' "${name}" >&2
    tail -n 40 "${CHECK_LOG}" >&2
    FAILED=1
}

run_check 'Ruff: линтинг' docker compose run --rm -T test ruff check --fix .
run_check 'Ruff: форматирование' docker compose run --rm -T test ruff format .
run_check 'лимит символов' docker compose run --rm -T test python3 scripts/check_limits.py
run_check 'pytest' docker compose run --rm -T test pytest -q --tb=short
run_check 'сквозной запуск Compose' bash scripts/test_compose_lifecycle.sh
run_check 'сбои запуска Compose' bash scripts/test_compose_failure.sh
run_check 'сквозной сценарий исправлений' bash scripts/test_amendments_e2e.sh

cleanup

if (( FAILED )); then
    exit 1
fi
printf 'Все проверки пройдены.\n'
