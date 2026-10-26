#!/usr/bin/env bash
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
failures=0
tmp_root=$(mktemp -d)
trap 'rm -rf "$tmp_root"' EXIT

fail() {
	echo "FAIL $1: $2"
	failures=$((failures + 1))
}

setup() {
	claude_dir=$(mktemp -d -p "$tmp_root")

	mkdir -p "$claude_dir/skills/card" "$claude_dir/skills/other"
	echo old >"$claude_dir/CLAUDE.md"
	echo '{"old": true}' >"$claude_dir/settings.json"
	ln -s /nonexistent/obsidian-notes "$claude_dir/skills/obsidian-notes"
	ln -s /nonexistent/project "$claude_dir/skills/project"
}

test_desktop_links_files() {
	setup
	CLAUDE_DIR=$claude_dir "$repo/install.sh" desktop >/dev/null

	local pair src dst
	for pair in \
		"CLAUDE.md:CLAUDE.md" \
		"settings/desktop.json:settings.json" \
		"skills/card:skills/card" \
		"skills/project:skills/project" \
		"skills/refine:skills/refine"; do
		src=$repo/${pair%%:*}
		dst=$claude_dir/${pair#*:}
		[[ "$(readlink "$dst")" == "$src" ]] || { fail "${FUNCNAME[0]}" "$dst does not link to $src"; return; }
	done

	echo "PASS ${FUNCNAME[0]}"
}

test_desktop_backs_up_and_keeps_other_skills() {
	setup
	CLAUDE_DIR=$claude_dir "$repo/install.sh" desktop >/dev/null

	[[ "$(cat "$claude_dir"/dotclaude-backup/*/CLAUDE.md)" == old ]] ||
		{ fail "${FUNCNAME[0]}" "no CLAUDE.md backup"; return; }
	[[ "$(cat "$claude_dir"/dotclaude-backup/*/settings.json)" == '{"old": true}' ]] ||
		{ fail "${FUNCNAME[0]}" "no settings.json backup"; return; }
	compgen -G "$claude_dir/dotclaude-backup/*/card" >/dev/null || { fail "${FUNCNAME[0]}" "no card backup"; return; }
	[[ "$(readlink "$claude_dir"/dotclaude-backup/*/project)" == /nonexistent/project ]] ||
		{ fail "${FUNCNAME[0]}" "no stale project link backup"; return; }
	[[ "$(readlink "$claude_dir/skills/obsidian-notes")" == /nonexistent/obsidian-notes ]] ||
		{ fail "${FUNCNAME[0]}" "obsidian-notes changed"; return; }
	[[ -d "$claude_dir/skills/other" ]] || { fail "${FUNCNAME[0]}" "other skill removed"; return; }

	echo "PASS ${FUNCNAME[0]}"
}

test_desktop_is_idempotent() {
	setup
	CLAUDE_DIR=$claude_dir "$repo/install.sh" desktop >/dev/null

	local out
	out=$(CLAUDE_DIR=$claude_dir "$repo/install.sh" desktop)

	[[ -z "$out" ]] || { fail "${FUNCNAME[0]}" "second run moved files: $out"; return; }
	echo "PASS ${FUNCNAME[0]}"
}

test_desktop_fresh_dir() {
	local fresh_dir=$tmp_root/fresh/.claude
	CLAUDE_DIR=$fresh_dir "$repo/install.sh" desktop >/dev/null

	[[ "$(readlink "$fresh_dir/skills/card")" == "$repo/skills/card" ]] ||
		{ fail "${FUNCNAME[0]}" "card not linked in fresh dir"; return; }
	[[ ! -e "$fresh_dir/dotclaude-backup" ]] || { fail "${FUNCNAME[0]}" "backup made with nothing to replace"; return; }

	echo "PASS ${FUNCNAME[0]}"
}

test_unknown_target() {
	setup

	local target code err
	for target in laptop ""; do
		code=0
		err=$(CLAUDE_DIR=$claude_dir "$repo/install.sh" $target 2>&1 >/dev/null) || code=$?
		[[ $code -eq 2 ]] || { fail "${FUNCNAME[0]}" "target '$target' exited $code, want 2"; return; }
		[[ "$err" == "usage: install.sh desktop" ]] || { fail "${FUNCNAME[0]}" "target '$target' printed '$err'"; return; }
	done

	echo "PASS ${FUNCNAME[0]}"
}

test_desktop_links_files
test_desktop_backs_up_and_keeps_other_skills
test_desktop_is_idempotent
test_desktop_fresh_dir
test_unknown_target
exit "$((failures > 0))"
