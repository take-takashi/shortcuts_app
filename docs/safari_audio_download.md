# Safariで開いているページの音声を保存する

`download_audio_from_html.py` は、HTMLファイルまたはSafariの現在タブから音声を取得します。
既存のAuDee・Bitfan・Omny・JFN Pods向けのMP3処理に加え、Team aikoのVimeo埋め込みに対応しています。

## Safariの現在タブを使う

1. Safariで対象サイトにログインし、保存したい回のページを開きます。
2. Safariの開発メニューで「Apple EventsからのJavaScriptを許可」を有効にします。
3. プロジェクトルートで実行します。

```bash
mise run download-safari-audio --download_dir "$HOME/Downloads"
```

同じ処理をPythonから直接呼ぶ場合:

```bash
uv run --locked python download_audio_from_html.py \
  --safari \
  --download_dir "$HOME/Downloads"
```

Macのショートカットの「シェルスクリプトを実行」から呼ぶ場合:

```zsh
"$HOME/github/shortcuts_app/.venv/bin/python" \
  "$HOME/github/shortcuts_app/download_audio_from_html.py" \
  --safari --download_dir "$HOME/Downloads"
```

ショートカットからの実行前に、一度プロジェクトで `uv sync --locked` を実行してください。
初回はmacOSがSafariの操作許可を求めることがあります。

Safariから取得するのは現在ページのURLとHTMLです。スクリプトはパスワードやCookieを読み出さず、取得したHTMLもファイルに保存しません。
Team aikoでは、ログイン済みのページにあるVimeo埋め込みURLを利用します。ログイン処理やアクセス制限の回避は行いません。

## Team aikoの保存形式

- サイトの一覧ページにある公開日を配信日として使います。Vimeoへのアップロード日やダウンロードした日ではありません。
- 音声タグのタイトルは `YYYY-MM-DD エピソード名`、日付タグは `YYYY-MM-DD`、ファイル名は `{番組名}_{YYYYMMDD}_{エピソード名}.m4a` です。
- 例: タイトルは `2026-10-08 あじがとレディオ#232`、ファイル名は `あじがとレディオ_20261008_あじがとレディオ#232.m4a` になります。
- 音声専用HLSのAACパケットをPyAVでコピーします。再エンコードや音量調整をしないため、追加の音質劣化はありません。
- タイトル・アーティスト・番組名のタグと、取得できたカバー画像を埋め込みます。
- この処理には `yt-dlp`・`ffmpeg` CLI・`ffprobe` CLIは不要です。既存サイトのMP3タグ付けには従来どおり `ffmpeg` CLIを使います。
- 同名のM4Aがある場合はエラーにします。明示的に上書きする場合だけ `--overwrite` を追加します。
- 暗号化配信、ライブ配信、AAC以外の音声、音声専用HLSがない動画には対応していません。
- 通信エラーや配信情報と長さが一致しない場合は、M4Aを完成品として残しません。エラー時の終了コードは1です。

公開日は対象回のページURL（記事ID）で照合します。HTMLファイル入力で元ページのURLが分からない場合は、一覧上のエピソード名の完全一致で探します。過去回は一覧のページ送りをたどります。
取得できない場合は日付を推測せずエラーにします。サイトで日付を確認できた場合は、次のように手動指定できます。

```bash
mise run download-safari-audio --download_dir "$HOME/Downloads" --broadcast-date 2026-10-08
```

この変更前に保存した日付なしのファイルは、自動で改名・削除しません。再実行すると日付付きの別ファイルを保存します。

Vimeoの配信URLには有効期限があります。失敗時はSafariでページを開き直して再実行してください。
配信設定の解析は自前実装のため、Vimeoの仕様変更で修正が必要になる場合があります。

サイトの利用条件を確認して利用してください。Team aikoの対象ページには「本コンテンツは保存できません」との案内があります。

## 従来のHTMLファイル入力

既存のショートカットからの呼び出し方は変更不要です。

```bash
uv run --locked python download_audio_from_html.py \
  --html /path/to/page.html \
  --domain sp.aiko.pcan.us \
  --download_dir "$HOME/Downloads"
```

VimeoへのRefererを明示する場合は `--page-url 'https://sp.aiko.pcan.us/contents/...'` を追加できます。
非公開動画の識別情報や期限付きURLを含むHTMLは、リポジトリに登録しないでください。

## テスト

```bash
uv run --locked python -m pytest tests/test_vimeo_audio.py tests/test_team_aiko_publish_date.py tests/test_download_audio_from_html.py
```

テストはダミーのページ情報とPyAVで生成した音声を使い、会員サイトへの接続は行いません。
公開日の照合・ページ送り・手動指定、AACパケットの一致、HTTP経由の分割HLS取得とReferer、タグ・カバー、既存MP3処理、失敗時の後片付けを確認します。
