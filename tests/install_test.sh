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
	CLAUDE_DIR=$claude_dir GO_CACHE_DIR=$claude_dir/claude-go "$repo/install.sh" desktop >/dev/null

	local pair src dst
	for pair in \
		"CLAUDE.md:CLAUDE.md" \
		"settings/desktop.json:settings.json" \
		"statusline.sh:statusline.sh" \
		"skills/card:skills/card" \
		"skills/project:skills/project" \
		"skills/refine:skills/refine" \
		"skills/retro:skills/retro" \
		"skills/audit:skills/audit" \
		"skills/learn:skills/learn" \
		"skills/repo-security-review:skills/repo-security-review"; do
		src=$repo/${pair%%:*}
		dst=$claude_dir/${pair#*:}
		[[ "$(readlink "$dst")" == "$src" ]] || { fail "${FUNCNAME[0]}" "$dst does not link to $src"; return; }
	done

	echo "PASS ${FUNCNAME[0]}"
}

test_desktop_backs_up_and_keeps_other_skills() {
	setup
	CLAUDE_DIR=$claude_dir GO_CACHE_DIR=$claude_dir/claude-go "$repo/install.sh" desktop >/dev/null

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
	CLAUDE_DIR=$claude_dir GO_CACHE_DIR=$claude_dir/claude-go "$repo/install.sh" desktop >/dev/null

	local out
	out=$(CLAUDE_DIR=$claude_dir GO_CACHE_DIR=$claude_dir/claude-go "$repo/install.sh" desktop)

	[[ -z "$out" ]] || { fail "${FUNCNAME[0]}" "second run moved files: $out"; return; }
	echo "PASS ${FUNCNAME[0]}"
}

test_desktop_fresh_dir() {
	local fresh_dir=$tmp_root/fresh/.claude
	CLAUDE_DIR=$fresh_dir GO_CACHE_DIR=$tmp_root/fresh/claude-go "$repo/install.sh" desktop >/dev/null

	[[ "$(readlink "$fresh_dir/skills/card")" == "$repo/skills/card" ]] ||
		{ fail "${FUNCNAME[0]}" "card not linked in fresh dir"; return; }
	[[ "$(readlink "$fresh_dir/skills/retro")" == "$repo/skills/retro" ]] ||
		{ fail "${FUNCNAME[0]}" "retro not linked in fresh dir"; return; }
	[[ ! -e "$fresh_dir/dotclaude-backup" ]] || { fail "${FUNCNAME[0]}" "backup made with nothing to replace"; return; }
	[[ -d "$tmp_root/fresh/claude-go/tmp" ]] || { fail "${FUNCNAME[0]}" "Go temp folder not created"; return; }

	echo "PASS ${FUNCNAME[0]}"
}

test_vm_installs_managed_files() {
	local managed_dir=$tmp_root/vm/etc/claude-code
	mkdir -p "$managed_dir"
	echo old >"$managed_dir/managed-settings.json"
	chmod 600 "$managed_dir/managed-settings.json"
	MANAGED_DIR=$managed_dir "$repo/install.sh" vm >/dev/null

	local pair src dst
	mkdir -p "$managed_dir/.claude/skills/card"
	echo stale >"$managed_dir/.claude/skills/card/stale.md"
	MANAGED_DIR=$managed_dir "$repo/install.sh" vm >/dev/null

	for pair in \
		"settings/vm-managed.json:managed-settings.json" \
		"settings/vm-managed-mcp.json:managed-mcp.json" \
		"CLAUDE.md:CLAUDE.md" \
		"skills/card/SKILL.md:.claude/skills/card/SKILL.md" \
		"skills/card/scripts/jira.py:.claude/skills/card/scripts/jira.py" \
		"skills/card/scripts/security_findings.py:.claude/skills/card/scripts/security_findings.py" \
		"skills/audit/SKILL.md:.claude/skills/audit/SKILL.md" \
		"skills/repo-security-review/SKILL.md:.claude/skills/repo-security-review/SKILL.md" \
		"skills/retro/SKILL.md:.claude/skills/retro/SKILL.md"; do
		src=$repo/${pair%%:*}
		dst=$managed_dir/${pair#*:}
		[[ -f "$dst" && ! -L "$dst" ]] || { fail "${FUNCNAME[0]}" "$dst is not a regular file"; return; }
		cmp -s "$src" "$dst" || { fail "${FUNCNAME[0]}" "$dst differs from $src"; return; }
		[[ "$(stat -c %a "$dst")" == 644 ]] || { fail "${FUNCNAME[0]}" "$dst mode is not 644"; return; }
	done

	[[ "$(stat -c %a "$managed_dir/statusline.sh")" == 755 ]] ||
		{ fail "${FUNCNAME[0]}" "statusline.sh mode is not 755"; return; }
	cmp -s "$repo/statusline.sh" "$managed_dir/statusline.sh" ||
		{ fail "${FUNCNAME[0]}" "statusline.sh differs"; return; }
	[[ ! -e "$managed_dir/.claude/skills/card/stale.md" ]] || { fail "${FUNCNAME[0]}" "stale skill file kept"; return; }
	[[ "$(stat -c %a "$managed_dir/.claude/skills/card/scripts")" == 755 ]] ||
		{ fail "${FUNCNAME[0]}" "skill folder mode is not 755"; return; }

	echo "PASS ${FUNCNAME[0]}"
}

test_unknown_target() {
	setup

	local target code err
	for target in laptop ""; do
		code=0
		err=$(CLAUDE_DIR=$claude_dir "$repo/install.sh" $target 2>&1 >/dev/null) || code=$?
		[[ $code -eq 2 ]] || { fail "${FUNCNAME[0]}" "target '$target' exited $code, want 2"; return; }
		[[ "$err" == "usage: install.sh desktop|vm" ]] || { fail "${FUNCNAME[0]}" "target '$target' printed '$err'"; return; }
	done

	echo "PASS ${FUNCNAME[0]}"
}

test_desktop_links_files
test_desktop_backs_up_and_keeps_other_skills
test_desktop_is_idempotent
test_desktop_fresh_dir
test_vm_installs_managed_files
test_unknown_target
exit "$((failures > 0))"
