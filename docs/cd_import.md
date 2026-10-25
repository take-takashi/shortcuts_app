# CDの取り込みとNotionへの保存

`import_cd_to_notion.py` はdiskflowを起動し、音量調整・タグ付きAACを曲ごとにNotionへ登録します。アルバム名のタグページには、本文の先頭にカバー画像、その直後に原本ZIPを配置します。ページアイコンにも同じ画像を使います。既存の本文は削除しません。

CD読み取りと音声処理はdiskflow、ZIP作成とNotion登録はshortcuts_appの担当です。FFmpeg CLIや追加のHomebrewパッケージは使いません。曲のページ作成・ファイル送信は既存の`MyNotionHelper`と共通化し、曲情報はdiskflowの検証済みJSONから取得します。

## 初回の設定

同じ親ディレクトリに`diskflow`と`shortcuts_app`を置き、両方のmise設定を利用できる状態にしてください。それぞれのリポジトリのPython・uv設定を使います。別の場所にdiskflowがある場合は`DISKFLOW_DIR`に絶対パスを設定します。

`shortcuts_app/.env`には既存の単曲アップロードと同じ設定が必要です。トークンはdiskflowの子プロセスへ渡しません。

```dotenv
NOTION_TOKEN=your_notion_token_here
NOTION_DATABASE_MUSIC_ID=your_music_database_id_here
NOTION_DATABASE_TAGS_ID=your_tags_database_id_here
```

インテグレーションに両データベースへのアクセスと、コンテンツの読み取り・挿入・更新権限を付けてください。曲DBのプロパティは既存どおり「タイトル」「No」「トラックアーティスト」「アルバム」「アルバムアーティスト」、タグDBは「Name」「Category」を使います。タグ名が同じページが複数ある場合は、誤ったページに添付しないよう停止します。アーティストとアルバムの区別方法は既存のタグ設計を引き継ぎます。

## ショートカット.appからの起動

次のコマンドで、ショートカット.appに追加できる署名済みファイルを生成します。生成しただけでは追加も取り込みも始まりません。既存ファイルは上書きしません。

```bash
cd ~/github/shortcuts_app/create_shortcuts
mise run cd-import
```

`~/Downloads/CDをNotionへ（ショートカット）.shortcut`を開き、内容を確認して「ショートカットを追加」を押してください。追加後はショートカット.appやSpotlightから起動できます。従来の.appと区別できるよう、名前に「ショートカット」を付けています。

中身はコメント、キャンセル可能な確認、シェルスクリプトの3アクションです。実行すると新しいCDの取り込みを確認し、続行した場合だけ`osascript`からTerminalを開いて、リポジトリのルートで`mise run import-cd`を直接実行します。`.command`や`.app`は経由しません。まず試すだけなら確認をキャンセルしてください。取り込み済みのCDで再実行すると、別の出力として重複登録される場合があります。

初回にスクリプト実行の許可を求められた場合は、ショートカット.appの「設定」→「詳細」で「スクリプトの実行を許可」を確認してください。Terminalの操作許可を求められる場合もあります。Pythonの音声処理やNotionトークンはファイルに埋め込みません。

登録済みショートカットのShell欄は、`create_shortcuts/definitions/cd_import.py`の`LAUNCH_SCRIPT`にある内容へ置き換えます。Python定義の変更は、登録済みショートカットへ自動では反映されません。シェルは`/bin/zsh`を使います。`mise`はPATH、`~/.local/bin`、Apple Silicon・IntelのHomebrew標準パスから探し、パスに空白や引用符があっても扱えるようAppleScriptへ引数で渡します。

ショートカット側の実行完了はTerminalの起動完了であり、CD取り込み・アップロードの完了ではありません。進捗と最終結果はTerminalで確認します。

iCloud同期を有効にすればショートカット本体は同期対象になります。実行する各Macには、`~/github/shortcuts_app`とdiskflow、mise環境、`.env`設定を別途用意してください。配置が違う場合はショートカットのシェルスクリプト内のパスを変更します。Mac専用なのでiPhone・iPadでは実行できません。

CD用の定義は`create_shortcuts/definitions/cd_import.py`、共通の生成・署名処理は`create_shortcuts/builder.py`で管理します。タスク名も定義名と同じ`cd-import`です。追加方法とXML出力は[`create_shortcuts/`の説明](../create_shortcuts/README.md)を参照してください。

plistを構成し、macOS標準の`shortcuts sign --mode anyone`で署名します。CD用定義は署名時に起動処理だけをAppleの検証サービスへ送信し、音声・画像・認証情報は含めません。署名済みファイルはGit管理から除外し、生成コードのみ管理します。

## 従来の.appからの起動

Spotlight用アプリは次のコマンドで作成します。作成だけでは取り込みもアップロードも始まりません。既存アプリは上書きしません。

```bash
cd ~/github/shortcuts_app
mise run install-cd-shortcut
```

`~/Applications/CDをNotionへ.app`が作成されます。Spotlightで「CDをNotionへ」を検索して起動するとTerminalが開きます。初回はTerminalの操作許可を求められる場合があります。リポジトリを移動した場合は、既存の起動アプリを手動で移動してから作り直してください。

この旧`.app`は`.command`を経由します。ショートカット.app版はこの経路を使いません。

## 通常の取り込み

CDを入れてSpotlight用アプリを起動するか、shortcuts_appで次を実行します。デバイス名やAppleアルバムIDの指定は不要です。

```bash
mise run import-cd
```

保存先は既定で`~/Music/diskflow/日時-識別子/`です。カバー画像はdiskflowの通常の選択方法を使います。用意した画像を使う場合は、diskflowのルートに`cover.jpg`または`cover.png`のどちらか一方を置くか、次のように指定します。

```bash
mise run import-cd --artwork ~/Pictures/album-cover.jpg
```

曲情報を検索し直す場合は`--search "アーティスト名 アルバム名"`、保存先を変える場合は`--output /新しい保存先`を指定できます。既存フォルダは取り込み先にできません。

## Notionページの構成

アルバム名のタグページは次の順で更新します。

1. カバー画像をNotionへ実体アップロードし、本文先頭に画像ブロックを追加する。
2. 同じ画像をページアイコンに設定する。
3. 原本ZIPをアップロードし、画像ブロックの直後にファイルブロックを追加する。
4. 最初のファイルプロパティがあれば、画像・ZIP・既存ファイルの順に並べる。
5. 曲ごとのページを作成してAACを添付し、同じアルバムタグへ紐付ける。

ヘッダーの「ページカバー」は変更しません。本文の画像とページアイコンを設定します。サムネイル表示はNotion側のビュー設定にも依存します。

ファイルプロパティで同じ取り込みを再登録しないよう、画像・ZIPの表示名には短いハッシュを付けます。画像のハッシュが同じ添付は再利用相当の置換になりますが、既存の本文ブロックは削除しません。

## ローカルに残すもの

| パス | 内容 |
| --- | --- |
| `aac/` | 完成した曲別M4A、アルバム情報、カバー画像 |
| `capture/` | 未加工音声、TOC、読み取り記録、曲情報・画像、復元設定 |
| `capture.zip` | `capture/`一式。AACや認証情報は含めない |
| `notion-upload.json` | 完了済み操作、ページID、アップロードIDなどの再開情報 |
| `notion-upload.log` | ZIP作成とNotion登録の進捗 |

原本・AAC・ZIPはアップロード後も削除しません。ZIPは書き込み後に全エントリのサイズとSHA-256を検証します。既存ZIPは検証して利用し、不一致なら上書きせず停止します。`capture/`にreport未登録のファイルがあっても送信しません。

Notionの上限はボット情報から取得し、ページ作成・ファイル送信より先に確認します。現在の目安はFreeが1ファイル5MiB、Paidが5GiBです。20MiBを超えるファイルは10MiBずつ送信しますが、この分割送信でプラン上限を回避できるわけではありません。パート失敗時は完了APIを呼びません。

## アップロードの再開

CDの読み取りとAAC作成が完了していれば、出力フォルダを指定して再開できます。CDやメタデータ検索は不要です。同じ出力の成功済み操作は再送しません。別の出力として同じCDを取り込み直した場合の重複登録までは防ぎません。

```bash
mise run import-cd "$HOME/Music/diskflow/取り込み済みフォルダ"
```

Spotlight用アプリを再起動した場合も、前回のNotion登録が未完了なら再開するか尋ねます。この入口同士の同時実行はOSロックで防止します。

送信済みでも未添付のファイルは、Notion側で期限切れになる場合があります。その場合は実体だけを送り直します。添付済みファイルのダウンロードURLにも期限がありますが、ファイル自体の保存期限ではありません。後からページを開けば取得できます。

ページ作成やブロック追加の応答が失われると、サーバー上では完了している可能性があります。この場合は二重登録を避けるため停止します。ログと`notion-upload.json`の`pending`を見てNotion側を確認し、該当操作が未実行、または今回の結果不明な操作でできたページ・ブロックを手動で整理したことを確認してから再試行します。既存の無関係なページ・ブロックは削除しないでください。

```bash
mise run import-cd "/取り込み済みフォルダ" --retry-uncertain
```

CD読み取り・音声処理自体の失敗はdiskflow側の再開対象ではありません。失敗時の資料は残し、完了したcaptureがあれば新しい出力へ復元します。

## ZIPからの復元

アルバムタグページからZIPをダウンロードし、展開すると`capture/`が得られます。そこにはAACではなく、CDから読み取った未加工音声が入っています。

AACを作り直すだけならdiskflow側で実行します。Notionへは送信しません。

```bash
cd ~/github/diskflow
mise run import -- "/展開先/capture"
```

未加工の曲別WAVを取り出す場合もCDは不要です。既存ファイルを上書きしないよう、新しい出力先を指定します。

```bash
mise run split -- "/展開先/capture" --output "/新しいWAV出力先"
```

shortcuts_appから新規AAC作成とNotion登録をまとめて行う場合は、次を使います。

```bash
cd ~/github/shortcuts_app
mise run import-cd --from-capture "/展開先/capture"
```

保存したPCM・曲情報・画像・設定は復元できますが、ditherやmacOSエンコーダーの違いによりAACのバイト一致は保証しません。対応するmacOS実行環境が必要です。読み取り一致は独立したセキュアリップ検証ではなく、diskflowの`archival_verified: false`という評価は変えません。

## Notionに接続しない確認

`--prepare-only`は認証情報を読み込まず、Notionクライアントも作りません。CD取り込みまたは保存済み出力の検証、ZIP作成までを実行します。保存済みcaptureなら、曲情報もキャッシュから再利用します。

```bash
mise run import-cd --prepare-only --from-capture "/保存済み/capture"
mise run import-cd "/完成済みdiskflow出力" --prepare-only
```

通常実行の進捗は標準エラー、最終結果は標準出力のJSONです。終了コードは成功0、失敗1、中断130です。引数エラーはargparseの終了コード2になります。

## 使用するNotion API

本文の位置指定とアイコン更新だけ`Notion-Version: 2026-03-11`を使います。既存DBクエリを壊さないよう、ヘルパー全体のAPIバージョンは変更しません。

- [本文の先頭・指定ブロック直後への追加](https://developers.notion.com/docs/upgrade-guide-2026-03-11)
- [ページアイコン更新](https://developers.notion.com/reference/patch-page)
- [大容量ファイルの分割送信](https://developers.notion.com/guides/data-apis/sending-larger-files)
- [ファイルサイズ上限の取得](https://developers.notion.com/reference/get-self)
