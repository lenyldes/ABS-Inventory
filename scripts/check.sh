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

PARALLEL_NAMES=()
PARALLEL_LOGS=()
PARALLEL_PIDS=()

run_parallel() {
    local name="$1"
    shift
    local log
    log=$(mktemp) || exit 1
    PARALLEL_NAMES+=("${name}")
    PARALLEL_LOGS+=("${log}")
    "$@" >"${log}" 2>&1 &
    PARALLEL_PIDS+=($!)
}

wait_parallel() {
    for i in "${!PARALLEL_PIDS[@]}"; do
        local pid="${PARALLEL_PIDS[i]}"
        local name="${PARALLEL_NAMES[i]}"
        local log="${PARALLEL_LOGS[i]}"
        if ! wait "${pid}"; then
            printf 'ОШИБКА: %s\n' "${name}" >&2
            tail -n 40 "${log}" >&2
            FAILED=1
        fi
        rm -f "${log}"
    done
}

cleanup_on_interrupt() {
    for pid in "${PARALLEL_PIDS[@]:-}"; do
        kill "${pid}" 2>/dev/null || true
    done
    for log in "${PARALLEL_LOGS[@]:-}"; do
        rm -f "${log}" 2>/dev/null || true
    done
    cleanup
    exit 130
}
trap cleanup_on_interrupt INT TERM

# 1. Быстрые статические проверки без базы данных (Fail-fast)
run_check 'статические проверки (Ruff и лимит символов)' \
    docker compose run --rm -T --no-deps test sh -c \
    'ruff check --fix . && ruff format . && python3 scripts/check_limits.py'

if (( FAILED )); then
    cleanup
    exit 1
fi

# 2. Параллельный запуск тестовых наборов в изолированных Compose-проектах
run_parallel 'pytest' docker compose run --rm -T test pytest -q --tb=short
run_parallel 'сквозной запуск Compose' bash scripts/test_compose_lifecycle.sh
run_parallel 'сбои запуска Compose' bash scripts/test_compose_failure.sh
run_parallel 'сквозной сценарий исправлений' bash scripts/test_amendments_e2e.sh

wait_parallel
cleanup

if (( FAILED )); then
    exit 1
fi
printf 'Все проверки пройдены.\n'
