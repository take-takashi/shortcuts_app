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

## 新規セットアップ時のコマンド

TODO: pyproject.tomlにしたい

```bash
takashi@Mac shortcuts_app % python3 -m venv .venv
takashi@Mac shortcuts_app % source .venv/bin/activate
(.venv) takashi@Mac shortcuts_app % pip install uv
(.venv) takashi@Mac shortcuts_app % uv pip install -r requirements.in

# .example.envを参考に.envを作成、設定すること
```
