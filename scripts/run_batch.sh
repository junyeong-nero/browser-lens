#!/usr/bin/env bash

if [ -z "${BASH_VERSION:-}" ]; then
	exec bash "$0" "$@"
fi

set -euo pipefail

TASKS_FILES=("experiments/tasks_ko.json" "experiments/tasks_en.json")
TASKS_FILE_OPTION_SET=0
LANG_FILTER="both"
DRY_RUN=0
LIMIT=0
START_AT=1
START_AT_SET=0
START_ENTRY_AT=1
START_ENTRY_AT_SET=0
FROM_LAST_FAILURE=0
LOG=1
VIDEO=0
STOP_ON_FAILURE=0
HEADLESS=""
USE_FILTERS=()
EXTRA_ARGS=()
LAST_FAILURE_FILE="${RUN_BATCH_LAST_FAILURE_FILE:-logs/run_batch_last_failure.tsv}"

USER_AGENT="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

usage() {
	cat <<'USAGE'
Usage: scripts/run_batch.sh [options] [-- extra main.py args]

Rerun query entries from the BrowserLens experiment task files. By default the
Korean and English task files are both read, producing two BrowserLens runs per
task.

Options:
  --tasks-file PATH      JSON task file to read. Repeatable.
                         Default: experiments/tasks_ko.json and experiments/tasks_en.json
  --use VALUE            Only run tasks whose "use" field matches VALUE. Repeatable.
                         Examples: --use main --use pilot
  --lang ko|en|both      Which query versions to run. Default: both
  --from N               Start from the Nth selected query entry after filters. Default: 1
  --from-entry N         Start from the extracted query entry number printed as [NNN]
  --from-last-failure    Start from the last failed query entry recorded by this script
  --last-failure-file PATH
                         State file for --from-last-failure.
                         Default: logs/run_batch_last_failure.tsv
  --limit N              Run at most N tasks after filtering. Default: all
  --dry-run              Print planned commands without running them
  --no-log               Do not pass --log to main.py
  --video                Pass --video to main.py
  --headless True|False  Pass --headless to main.py
  --stop-on-failure      Stop after the first failed task
  -h, --help             Show this help

Defaults mirror scripts/c3_browser_lens.sh where they make sense for one-off CLI tasks:
--highlight_mouse --log --grounding text --stealth --locale ko-KR
--timezone Asia/Seoul and the desktop Chrome user agent.
USAGE
}

die() {
	printf 'error: %s\n' "$*" >&2
	exit 2
}

is_positive_integer() {
	case "${1:-}" in
		''|*[!0-9]*) return 1 ;;
		*) [ "$1" -gt 0 ] ;;
	esac
}

tasks_files_label() {
	local label=""
	local tasks_file

	for tasks_file in "${TASKS_FILES[@]}"; do
		if [ -n "$label" ]; then
			label="$label, $tasks_file"
		else
			label="$tasks_file"
		fi
	done

	printf '%s' "$label"
}

tasks_file_is_selected() {
	local needle="$1"
	local tasks_file

	for tasks_file in "${TASKS_FILES[@]}"; do
		if [ "$tasks_file" = "$needle" ]; then
			return 0
		fi
	done

	return 1
}

load_last_failure_start() {
	[ -f "$LAST_FAILURE_FILE" ] || die "last failure file not found: $LAST_FAILURE_FILE"

	local entry_number
	local selected_number
	local use_value
	local lang
	local tasks_file
	local query

	IFS=$'\t' read -r entry_number selected_number use_value lang tasks_file query < "$LAST_FAILURE_FILE" \
		|| die "could not read last failure file: $LAST_FAILURE_FILE"
	is_positive_integer "$entry_number" \
		|| die "invalid last failure entry number in $LAST_FAILURE_FILE"

	START_ENTRY_AT="$entry_number"
	printf 'Resuming from last failed query entry [%03d]' "$entry_number"
	if [ -n "${use_value:-}" ] && [ -n "${lang:-}" ]; then
		printf ' %s (%s)' "$use_value" "$lang"
	fi
	printf '.\n'

	if [ -n "${tasks_file:-}" ] && ! tasks_file_is_selected "$tasks_file"; then
		printf 'warning: last failure was recorded for %s, current tasks files are %s\n' \
			"$tasks_file" "$(tasks_files_label)" >&2
	fi
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--tasks-file)
			[ "$#" -ge 2 ] || die "--tasks-file requires a path"
			if [ "$TASKS_FILE_OPTION_SET" -eq 0 ]; then
				TASKS_FILES=()
				TASKS_FILE_OPTION_SET=1
			fi
			TASKS_FILES+=("$2")
			shift 2
			;;
		--use)
			[ "$#" -ge 2 ] || die "--use requires a value"
			USE_FILTERS+=("$2")
			shift 2
			;;
		--lang)
			[ "$#" -ge 2 ] || die "--lang requires ko, en, or both"
			case "$2" in
				ko|en|both) LANG_FILTER="$2" ;;
				*) die "--lang must be ko, en, or both" ;;
			esac
			shift 2
			;;
		--from)
			[ "$#" -ge 2 ] || die "--from requires a positive integer"
			is_positive_integer "$2" || die "--from must be a positive integer"
			START_AT="$2"
			START_AT_SET=1
			shift 2
			;;
		--from-entry)
			[ "$#" -ge 2 ] || die "--from-entry requires a positive integer"
			is_positive_integer "$2" || die "--from-entry must be a positive integer"
			START_ENTRY_AT="$2"
			START_ENTRY_AT_SET=1
			shift 2
			;;
		--from-last-failure)
			FROM_LAST_FAILURE=1
			shift
			;;
		--last-failure-file)
			[ "$#" -ge 2 ] || die "--last-failure-file requires a path"
			LAST_FAILURE_FILE="$2"
			shift 2
			;;
		--limit)
			[ "$#" -ge 2 ] || die "--limit requires a positive integer"
			is_positive_integer "$2" || die "--limit must be a positive integer"
			LIMIT="$2"
			shift 2
			;;
		--dry-run)
			DRY_RUN=1
			shift
			;;
		--no-log)
			LOG=0
			shift
			;;
		--video)
			VIDEO=1
			shift
			;;
		--headless)
			[ "$#" -ge 2 ] || die "--headless requires True or False"
			case "$2" in
				True|False) HEADLESS="$2" ;;
				*) die "--headless must be True or False" ;;
			esac
			shift 2
			;;
		--stop-on-failure)
			STOP_ON_FAILURE=1
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		--)
			shift
			EXTRA_ARGS+=("$@")
			break
			;;
		*)
			die "unknown option: $1"
			;;
	esac
done

if [ "$FROM_LAST_FAILURE" -eq 1 ] && { [ "$START_AT_SET" -eq 1 ] || [ "$START_ENTRY_AT_SET" -eq 1 ]; }; then
	die "--from-last-failure cannot be combined with --from or --from-entry"
fi

if [ "$START_AT_SET" -eq 1 ] && [ "$START_ENTRY_AT_SET" -eq 1 ]; then
	die "--from and --from-entry cannot be combined"
fi

[ "${#TASKS_FILES[@]}" -gt 0 ] || die "no tasks files configured"
for tasks_file in "${TASKS_FILES[@]}"; do
	[ -f "$tasks_file" ] || die "tasks file not found: $tasks_file"
done

if [ "$FROM_LAST_FAILURE" -eq 1 ]; then
	load_last_failure_start
fi

matches_use_filter() {
	local use_value="$1"
	local filter

	if [ "${#USE_FILTERS[@]}" -eq 0 ]; then
		return 0
	fi

	for filter in "${USE_FILTERS[@]}"; do
		if [ "$use_value" = "$filter" ]; then
			return 0
		fi
	done

	return 1
}

matches_lang_filter() {
	local lang="$1"
	[ "$LANG_FILTER" = "both" ] || [ "$LANG_FILTER" = "$lang" ]
}

extract_tasks() {
	python3 - "${TASKS_FILES[@]}" <<'PY'
import json
import sys
from pathlib import Path


def infer_lang(source_path, data, task):
    for candidate in (
        task.get("lang"),
        task.get("language"),
        data.get("lang") if isinstance(data, dict) else None,
        data.get("language") if isinstance(data, dict) else None,
    ):
        lang = str(candidate or "").strip().lower()
        if lang in {"ko", "en"}:
            return lang

    stem = Path(source_path).stem.lower()
    if stem.endswith("_ko") or stem.endswith("-ko"):
        return "ko"
    if stem.endswith("_en") or stem.endswith("-en"):
        return "en"
    return ""


rows = []
lang_order = {"ko": 0, "en": 1}

for source_index, source_path in enumerate(sys.argv[1:]):
    with open(source_path, encoding="utf-8") as handle:
        data = json.load(handle)

    tasks = data.get("tasks", []) if isinstance(data, dict) else data
    if not isinstance(tasks, list):
        continue

    for task_index, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue

        use_value = str(task.get("use") or "").strip()
        if not use_value:
            continue

        query = str(task.get("query") or "").strip()
        if query:
            lang = infer_lang(source_path, data, task)
            rows.append((task_index, lang_order.get(lang, 2), source_index, source_path, use_value, lang, query))
            continue

        for lang, key in (("ko", "query_ko"), ("en", "query_en")):
            query = str(task.get(key) or "").strip()
            if query:
                rows.append((task_index, lang_order.get(lang, 2), source_index, source_path, use_value, lang, query))

for _, _, _, source_path, use_value, lang, query in sorted(rows):
    print("\t".join((source_path, use_value, lang, query)))
PY
}

print_command() {
	local -a command=("$@")
	local part
	local quoted

	shell_quote() {
		quoted="${1//\'/\'\\\'\'}"
		case "$1" in
			''|*[!A-Za-z0-9_./:=@%+-]*)
				printf "'%s'" "$quoted"
				;;
			*)
				printf '%s' "$1"
				;;
		esac
	}

	shell_quote "${command[0]}"
	for part in "${command[@]:1}"; do
		printf ' '
		shell_quote "$part"
	done
	printf '\n'
}

record_last_failure() {
	local entry_number="$1"
	local selected_number="$2"
	local tasks_file="$3"
	local use_value="$4"
	local lang="$5"
	local query="$6"
	local state_dir="${LAST_FAILURE_FILE%/*}"

	if [ "$state_dir" != "$LAST_FAILURE_FILE" ]; then
		mkdir -p "$state_dir"
	fi

	printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
		"$entry_number" "$selected_number" "$use_value" "$lang" "$tasks_file" "$query" \
		> "$LAST_FAILURE_FILE"
	printf 'Recorded last failed query entry in %s\n' "$LAST_FAILURE_FILE" >&2
}

run_task() {
	local task_number="$1"
	local use_value="$2"
	local lang="$3"
	local query="$4"
	local -a command=(uv run main.py)

	command+=(--highlight_mouse)
	if [ "$LOG" -eq 1 ]; then
		command+=(--log)
	fi
	command+=(--grounding text)
	command+=(--stealth)
	command+=(--locale ko-KR)
	command+=(--timezone Asia/Seoul)
	command+=(--user-agent "$USER_AGENT")
	if [ "$VIDEO" -eq 1 ]; then
		command+=(--video)
	fi
	if [ -n "$HEADLESS" ]; then
		command+=(--headless "$HEADLESS")
	fi
	if [ "${#EXTRA_ARGS[@]}" -gt 0 ]; then
		command+=("${EXTRA_ARGS[@]}")
	fi
	command+=("$query")

	printf '\n[%03d] %s (%s)\n' "$task_number" "$use_value" "$lang"
	printf '%s\n' "$query"

	if [ "$DRY_RUN" -eq 1 ]; then
		print_command "${command[@]}"
		return 0
	fi

	print_command "${command[@]}"
	if "${command[@]}"; then
		printf '[%03d] completed (%s)\n' "$task_number" "$lang"
		return 0
	fi

	printf '[%03d] failed (%s)\n' "$task_number" "$lang" >&2
	return 1
}

total_seen=0
selected_seen=0
run_count=0
failure_count=0

while IFS=$'\t' read -r tasks_file use_value lang query; do
	total_seen=$((total_seen + 1))

	if [ "$total_seen" -lt "$START_ENTRY_AT" ]; then
		continue
	fi

	if ! matches_use_filter "$use_value"; then
		continue
	fi

	if ! matches_lang_filter "$lang"; then
		continue
	fi

	selected_seen=$((selected_seen + 1))
	if [ "$selected_seen" -lt "$START_AT" ]; then
		continue
	fi

	run_count=$((run_count + 1))
	should_stop=0
	if ! run_task "$total_seen" "$use_value" "$lang" "$query"; then
		failure_count=$((failure_count + 1))
		record_last_failure "$total_seen" "$selected_seen" "$tasks_file" "$use_value" "$lang" "$query"
		if [ "$STOP_ON_FAILURE" -eq 1 ]; then
			should_stop=1
		fi
	fi

	if [ "$should_stop" -eq 1 ]; then
		break
	fi

	if [ "$LIMIT" -gt 0 ] && [ "$run_count" -ge "$LIMIT" ]; then
		break
	fi
done < <(extract_tasks)

printf '\nScanned %d query entries, selected %d, attempted %d, failures %d.\n' \
	"$total_seen" "$selected_seen" "$run_count" "$failure_count"

if [ "$run_count" -eq 0 ]; then
	printf 'No tasks matched the requested filters.\n' >&2
	exit 1
fi

if [ "$failure_count" -gt 0 ]; then
	exit 1
fi
