# shortcuts.app

Mac, iOSのショートカット.appで使うスクリプトなどをまとめる

## Geminiで作成した音楽の変換

`gemini_music_to_audio.py` は、GeminiからダウンロードしたMP4を、音量調整・タグ・カバー画像付きの音楽ファイルにします。Pythonの追加パッケージは不要ですが、`ffmpeg` と `ffprobe` が必要です。

```bash
python3 gemini_music_to_audio.py \
  ~/Downloads/Patterns_On_The_Glass.mp4 \
  --title "Patterns On The Glass" \
  --artist "Gemini"
```

デフォルトでは、音声に固定gainをかけてIntegrated Loudnessを`-14 LUFS`（True Peak上限`-1 dBTP`）に近づけ、M4A/AAC（256 kbps）とJPEGカバー画像を入力ファイルと同じ場所に出力します。タグの既定値はArtist/Album Artistが`TAKE Takashi`、Albumが`TAKE's music`、Dateが実行時の西暦、Genreが`Lo-Fi`です。Track Titleはファイル名の`_`を半角スペースに置き換えます。FLACで保存する場合は`--format flac`を指定します。

```bash
# デフォルトのM4A/AACに変換して音量調整（AACを再エンコード）
python3 gemini_music_to_audio.py ~/Downloads/Patterns_On_The_Glass.mp4

# 音量を変えず、入力の音声がAACならビットストリームをコピー（追加の音質劣化なし）
python3 gemini_music_to_audio.py ~/Downloads/Patterns_On_The_Glass.mp4 --format m4a --no-normalize
```

音量調整はReplayGainタグではなく、音声データ自体への固定gainです。音量調整を有効にすると音声の再エンコードが必要になります。デフォルトのM4A/AACで音量調整する場合は再エンコードによる劣化がわずかに加わります。`--no-normalize`を指定し、入力音声がAACなら再エンコードせずにコピーできます。FLACを選ぶと、調整後の音声をロスレスで保存できますが、入力MP4の音声が既にAACなどの非可逆形式なら、元の圧縮による劣化までは戻りません。Genreタグに世界共通の固定リストはないため、今回はスタイルを端的に示す`Lo-Fi`を設定しています。必要なら`--genre Chillout`などで変更できます。

### PyAV版 (ffmpeg / ffprobe CLI不要)

Shortcutsからの実行時にFFmpeg CLIを起動したくない場合は、`gemini_music_to_audio_pyav.py` を使います。PyAVがFFmpegライブラリをPythonプロセス内で直接呼び出すため、FFmpeg CLIとffprobe CLIは起動しません。`av` は`pyproject.toml`に追加済みです。

```bash
mise run gemini-music ~/Downloads/Patterns_On_The_Glass.mp4 --title "Patterns On The Glass" --artist "Gemini"
```

`mise run`が`uv run --locked`経由で起動するため、初回も手動の`uv sync`は不要です（`pyproject.toml`と`uv.lock`に従って仮想環境を同期します）。M4A/AACで音量を変えずに出力するなら、次のように指定します。

```bash
mise run gemini-music ~/Downloads/Patterns_On_The_Glass.mp4 --format m4a --no-normalize
```

この方法も内部ではFFmpegのライブラリを使いますが、PyAVのmacOS wheelには必要なライブラリが含まれるため、通常はHomebrew版FFmpegのインストールは不要です。変換テストでは`PATH`を空にしても動作することを確認しています。

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

## install package

```bash
shortcuts_app % uv add pyright==1.1.403 --dev
shortcuts_app % uv add pymarkdownlnt==0.9.31 --dev
```

## memo

- TODO: My***をsrcに移動
