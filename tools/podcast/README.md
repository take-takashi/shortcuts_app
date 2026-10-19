# podcast-tools

公開RSSから、公開日を指定してPodcastのMP3を取得するBunプログラムです。`ffmpeg`は不要です。Notionへの登録は、プロジェクトルートの `download_radiko_and_upload_notion.ts` が担当します。

## セットアップ

```bash
cd tools/podcast
mise run install
mise run typecheck
mise run test
```

## 日次オートメーション

Macのショートカットでは、既存の `download_radiko_and_upload_notion.ts` をそのまま呼び出します。Radikoの検索キーワードやNotionの設定も従来どおり使えます。通常は両方の昨日分を取得します。

プロジェクトルートから、初回だけPodcastの最新回を登録する場合は次のように実行します。初回かどうかは自動判定しません。

```bash
./download_radiko_and_upload_notion.ts --podcast-only --latest
```

`--podcast-only --date YYYYMMDD` ならPodcastだけを指定日で取得できます。`--radiko-only` を指定するとPodcastを取得しません。

## 番組設定

既定の `feeds.json` には次の3番組を登録しています。

| id | 番組 | RSS |
| --- | --- | --- |
| satoshio | 佐藤栞里 さとしおあちぇとぺぺ | https://omny.fm/shows/shiori/playlists/podcast.rss |
| otagaisamassu | お互いさまっす | https://feeds.megaphone.fm/HDYMP5472899783 |
| haruhiko | 春とヒコーキのグピ☆グパ☆グポ | https://feeds.megaphone.fm/FNCOMMUNICATIONSINC3656403561 |

番組を追加する場合は、重複しない `id` と公開RSSの `url` を指定します。別ファイルを使う場合は、日次スクリプトの `--podcast-feeds <パス>` または環境変数 `PODCAST_FEEDS_FILE` で指定できます。番組一覧の既定パスは、ショートカットの作業ディレクトリに依存しません。会員限定・アプリ限定の回は、公開RSSに含まれないことがあります。

## 日付と再実行

日次スクリプトの `--date` はRadikoと共通です。省略時は `yesterday`、ほかに `today` と `YYYYMMDD` を受け付けます。PodcastはRSSの `pubDate` を日本時間に変換し、その日の00:00以上、翌日00:00未満の公開済み回をすべて取得します。`--latest` はRSSの並び順にかかわらず、公開日時が最新の1回を番組ごとに選びます。

処理済み履歴は保存しません。既存の音声は再ダウンロードせず、日次スクリプトではNotion登録の対象に含めます。`--overwrite` で音声を再取得できます。途中失敗したファイルは完成ファイルとして残さず、上書きに失敗した場合も既存音声は残します。

Notion登録に失敗した場合は、同じ日付で再実行してください。Notionの別DBへ移動済みの回は再登録される場合があります。実行しなかった日やRSSへの掲載が遅れた回も、公開日を指定して取得します。ただし、RSSから削除された回はこの方法では取得できません。

## タイトルとカバー画像

MP3に埋め込まれたタイトル・アルバム名・カバー画像は維持します。不足時はRSSのエピソードタイトル・番組名で補完し、画像はエピソード画像、番組画像の順に取得します。補完用の画像はJPEG/PNGに対応し、取得できなくても音声は保存します。情報が揃っているMP3は書き換えず、音声の再エンコードは行いません。

ファイル名は `公開日時_番組名_エピソードタイトル_識別子.mp3` です。ファイル名に使えない文字と長すぎる名前は調整します。Notionページタイトルは `エピソードタイトル / 番組名 / 公開日時` とし、音声タグではなくRSSの情報を使います。日時の表示は日本時間です。Notionページのカバー画像は設定しません。

## ダウンロードだけの実行

以下はプロジェクトルートからの実行例です。Notionへの登録は行いません。

```bash
bun run tools/podcast/src/download.ts --date yesterday
bun run tools/podcast/src/download.ts --latest --save-directory ~/Downloads
bun run tools/podcast/src/download.ts --date 20261018 --manifest-output /tmp/podcast.json
```

単独CLIで既存音声もファイル一覧に含めるには `--manifest-include-existing` を指定します。`--feeds` で番組設定を変更でき、保存先の既定値は `PODCAST_SAVE_DIRECTORY` または `~/Downloads` です。日次スクリプト経由ではRadikoと共通の `--save-directory`、`RADIKO_SAVE_DIRECTORY`、`~/Downloads` の順で保存先を決めます。

## ログとテスト

Podcastのログは `~/Library/Logs/shortcuts_app/podcast.log` に保存します。5MiB以上になると `.1` へ移し、バックアップを1世代残します。ダウンロードやRSS取得の失敗は他の番組へ波及させず、取得できた音声をファイル一覧に残して終了コード1を返します。

`mise run test` は外部サービスに接続せず、日付の境界、画像・タグの維持と補完、再実行、失敗時の続行、既存の日次スクリプトとの連携を確認します。実際のNotion登録は行いません。
