# radiko2

Raycastを使わず、コマンドラインからradikoのタイムフリー番組を検索・ダウンロードするプログラムです。
macOSのショートカットのオートメーションから実行できます。

## セットアップ

```bash
cd tools/radiko2
mise install
mise run build
```

音声は内蔵のM4A writerで保存するため、`ffmpeg`は不要です。
実行環境と単一バイナリのビルドにはBunを使用します。

## 単一バイナリのビルド

macOS arm64向けの実行ファイルを作成します。`mise run build`が単一バイナリのビルドです。

```bash
mise run build
./dist/radiko2 --help
```

## 実行

```bash
mise run download -- --keywords "伊集院光|サンドウィッチマン"
```

`|`で区切ったキーワードはOR検索になります。番組タイトルとパーソナリティ名が検索対象です。

日付を省略すると昨日が対象になります。

```bash
# 今日
mise run download -- --keywords "伊集院光" --date today

# 指定日（YYYYMMDD）
mise run download -- --keywords "伊集院光" --date 20250630
```

既存ファイルはデフォルトでスキップします。上書きする場合は`--overwrite`を指定してください。
放送終了前の番組は自動ダウンロードの対象外です。

## オプション

```text
-k, --keywords <文字列>       検索語（|でOR検索）
-d, --date <日付>             yesterday（既定）、today、またはYYYYMMDD
    --save-directory <パス>   保存先（既定: ~/Downloads）
    --exclude-stations <ID>   除外する放送局ID（カンマ区切り）
    --overwrite               既存ファイルを上書き
    --include-future          放送終了前の番組も対象にする
```

## ショートカットからの実行例

ショートカットの「シェルスクリプトを実行」に以下を設定します。

```bash
cd /Users/ユーザー名/path/to/shortcuts_app/tools/radiko2
mise run download -- --keywords "伊集院光|サンドウィッチマン"
```

`mise install`でBunを揃えます。`mise run build`は初回、またはソース変更後に実行します。

設定値は環境変数でも指定できます。

```text
RADIKO_KEYWORDS
RADIKO_DATE
RADIKO_SAVE_DIRECTORY
RADIKO_EXCLUDE_STATION_IDS
```

ログは`~/Library/Logs/radiko2/radiko2.log`に保存されます。
