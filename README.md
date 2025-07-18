# shortcuts.app

Mac, iOSのショートカット.appで使うスクリプトなどをまとめる

## python用仮想環境の作成

```bash
takashi@Mac shortcuts.app % python3 -m venv .venv
takashi@Mac shortcuts.app % source .venv/bin/activate

# uvのインストール
(.venv) takashi@Mac shortcuts.app % pip install uv
(.venv) takashi@Mac shortcuts.app % uv --version
uv 0.7.12 (dc3fd4647 2025-06-06)
```

## uvの操作

```bash
# 初回のインストール（これはrequirements.inに記載すべきだった）
(.venv) takashi@Mac shortcuts.app % uv pip install notion-client yt-dlp requests python-dotenv
# ロック生成（requirements.inに追加したら実行）
(.venv) takashi@Mac shortcuts.app % uv pip compile requirements.in > requirements.txt
# インストールコマンド
uv pip sync requirements.txt
```

### uvでdevにpytestを入れてみた

```bash
(.venv) takashi@Mac shortcuts_app % uv add pytest==8.4.1 --dev
# これで`uv sync`で動く？
```

## 新規セットアップ時のコマンド

TODO: requirements.inとrequirements.txtを削除

```bash
takashi@Mac shortcuts_app % python3 -m venv .venv
takashi@Mac shortcuts_app % source .venv/bin/activate
(.venv) takashi@Mac shortcuts_app % pip install uv
(.venv) takashi@Mac shortcuts_app % uv sync

# 昔のコマンド
# (.venv) takashi@Mac shortcuts_app % uv pip install -r requirements.in

# .example.envを参考に.envを作成、設定すること
```

## `mise` 導入後の新しいパッケージインストールコマンド

```bash
# まず、pyproject.tomlにパッケージの追加内容を記載してから

.venvtakashi@Mac shortcuts_app % uv pip install selenium
.venvtakashi@Mac shortcuts_app % uv sync

```

## packageのメモ

- selenuim, webdriver-manager: ブラウザ操作（今は不要）
- playwright: ブラウザ操作その2（不要？）
- beautifulsoup4, lxml: HTMLファイルの構造操作（上記2つから乗り換え）

## `Playwright` のインストール

```bash
.venvtakashi@Mac shortcuts_app % python -m playwright install
```

## memo

- TODO: My***をsrcに移動
