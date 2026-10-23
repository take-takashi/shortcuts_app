#!/bin/zsh
# Finder・Shortcuts・Spotlight用アプリから、対話できるTerminalで起動する。
set -euo pipefail
SCRIPT_DIR="${0:A:h}"
MISE="${commands[mise]:-}"
if [[ -z "$MISE" ]]; then
  for candidate in "$HOME/.local/bin/mise" /opt/homebrew/bin/mise /usr/local/bin/mise; do
    if [[ -x "$candidate" ]]; then
      MISE="$candidate"
      break
    fi
  done
fi
if [[ -z "$MISE" ]]; then
  print -u2 'miseが見つかりません。miseをインストールしてください。'
  exit 1
fi
cd "$SCRIPT_DIR"
exec "$MISE" -C "$SCRIPT_DIR" run import-cd -- "$@"
