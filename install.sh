#!/usr/bin/env bash
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
claude_dir=${CLAUDE_DIR:-$HOME/.claude}
managed_dir=${MANAGED_DIR:-/etc/claude-code}
backup_dir=$claude_dir/dotclaude-backup/$(date +%Y%m%d%H%M%S)
skills=(card project refine retro)

link() {
	local src=$1 dst=$2

	if [[ -L "$dst" && "$(readlink "$dst")" == "$src" ]]; then
		return
	fi

	if [[ -e "$dst" || -L "$dst" ]]; then
		mkdir -p "$backup_dir"
		mv "$dst" "$backup_dir/"
		echo "moved $dst to $backup_dir"
	fi

	ln -s "$src" "$dst"
}

desktop() {
	local skill

	mkdir -p "$claude_dir/skills"
	link "$repo/CLAUDE.md" "$claude_dir/CLAUDE.md"
	link "$repo/settings/desktop.json" "$claude_dir/settings.json"

	for skill in "${skills[@]}"; do
		link "$repo/skills/$skill" "$claude_dir/skills/$skill"
	done
}

vm() {
	install -D -m 0644 "$repo/settings/vm-managed.json" "$managed_dir/managed-settings.json"
	install -D -m 0644 "$repo/settings/vm-managed-mcp.json" "$managed_dir/managed-mcp.json"
}

case "${1:-}" in
	desktop) desktop ;;
	vm) vm ;;
	*)
		echo "usage: install.sh desktop|vm" >&2
		exit 2
		;;
esac
