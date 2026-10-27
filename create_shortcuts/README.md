# ショートカットの作成と管理

ショートカット.app用の共通ライブラリと、用途別のPython定義をこのフォルダで管理します。実際のCD読み取りやNotion登録のコードは、従来のスクリプトに残します。

```text
create_shortcuts/
  .mise.toml                  定義名と同名の作成タスク
  __init__.py                 Shortcutの公開入口
  builder.py                  アクション・plist生成・署名・出力
  app.py                      登録名・UUIDの確認、追加画面の起動
  definitions/
    cd_import.py              CD取り込み用の手順定義と生成コマンド
```

## ショートカットを作成する

このフォルダで、定義名と同じタスクを実行します。

```bash
cd ~/github/shortcuts_app/create_shortcuts
mise run cd-import
```

タスク名は定義ファイル名の`_`を`-`に置き換えたものに揃えます。`definitions/cd_import.py`には`cd-import`を対応させ、別名や互換エイリアスは作りません。

CD用の登録名は`CDを取り込んでNotionへUpload`です。作成・署名は行いますが、登録済み本体の更新機能ではありません。このMacでは同名ファイルの追加で「2」という別UUIDのコピーができたため、更新できるとは扱いません。

- 同名の登録がなければ、署名後にもう一度未登録を確認して追加画面を開きます。
- 同名の登録が1件あれば、名前・UUIDを表示してファイル生成だけを行います。追加画面は開きません。
- 同名の登録が複数あれば停止します。

初回と再生成は同じコマンドです。既存のショートカットを変更する場合はアプリで編集してください。アプリ内の登録を自動で変更・削除したり、取り込みを実行したりはしません。

生成物は`~/Library/Caches/shortcuts_app/create_shortcuts/cd-import/実行ごとの識別子/`へ保存します。毎回別のフォルダへ同じ名前のファイルを作るため、以前の生成物は上書きしません。保存先を指定する場合も、登録名とファイル名を揃えます。

```bash
mise run cd-import --output "$HOME/Downloads/cd-import-new/CDを取り込んでNotionへUpload.shortcut"
```

名前やUUIDの確認は、既存本体の置換先指定ではありません。日本語の合成・分解表現（NFC/NFD）が異なる場合も、同名として確認します。生成ファイルを手動で開いても既存更新になる保証はなく、新しいコピーが追加される場合があります。

タスクはリポジトリのルートを作業ディレクトリにして、`python -m create_shortcuts.definitions.cd_import`を実行します。

## Pythonで手順を定義する

次のコードは定義と出力の例です。ショートカット本体のアクションは実行しません。

```python
from pathlib import Path

from create_shortcuts import Shortcut

shortcut = Shortcut("サンプル")
shortcut.comment("ショートカットの説明")
shortcut.alert("実行しますか？", "続けるとメッセージを表示します。", cancel=True)
shortcut.run_shell("printf '%s\\n' 'Hello'", shell="/bin/zsh")

# テキストエディタで読めるXML。署名もAppleへの通信も行わない。
shortcut.export(Path.home() / "Downloads/sample.plist", sign=False)

# ショートカット.appに追加できる署名済みファイル。
shortcut.export(Path.home() / "Downloads/sample.shortcut")
```

メソッドは同じ`Shortcut`を返すので、続けて呼び出すこともできます。

```python
shortcut = (
    Shortcut("サンプル").comment("説明").alert("続けますか？").run_shell("printf hello")
)
```

## 対応する操作

| API | 内容 |
| --- | --- |
| `comment(text)` | コメントを追加 |
| `alert(title, message="", cancel=True)` | キャンセル可能な確認を追加 |
| `run_shell(script, shell="/bin/zsh", input_mode="to stdin")` | シェルスクリプトを実行するアクションを追加 |
| `to_plist()` | 手順データの独立した辞書を取得 |
| `export(path)` | 署名済みの`.shortcut`を新規出力 |
| `export(path, sign=False)` | 未署名のXML `.plist`を新規出力 |

`input_mode`は`"to stdin"`または`"as arguments"`です。シェルは絶対パスで指定します。XMLは閲覧・確認用で、そのままショートカット.appへ追加するものではありません。

保存形式のキーやアクション識別子は`builder.py`に集約しています。現時点では上記の3種類のアクションを扱い、条件分岐・繰り返し・変数参照などは未対応です。Apple公式のPython作成APIではないため、対応アクションや保存形式を変える場合は実際のmacOSで確認します。

## 定義を増やす

`definitions/`に用途別のファイルを追加し、`create_shortcut()`で手順を返す形にすると、CD用定義と揃えられます。

```python
from pathlib import Path

from create_shortcuts import Shortcut


def create_shortcut() -> Shortcut:
    return Shortcut("新しい手順").comment("説明").run_shell("printf hello")


if __name__ == "__main__":
    create_shortcut().export(Path.home() / "Downloads/new-task.shortcut")
```

ファイル名を`new_task.py`にしたら、このフォルダの`.mise.toml`に同名の`new-task`タスクを追加します。

```toml
[tasks.new-task]
description = "新しい手順のショートカットを作成・署名"
dir = ".."
raw_args = true
run = "uv run --locked python -m create_shortcuts.definitions.new_task"
```

このフォルダで`mise run new-task`を実行して生成します。importしただけで署名・出力されないよう、生成処理には上記のガードか`main()`を使ってください。

## Git管理と同期

Python定義と共通ライブラリをGit管理します。署名済み`.shortcut`は生成物として除外します。ショートカット.appでの編集内容はPythonへ自動反映されないため、Git管理する変更は定義側へ反映して再生成します。

iCloudで同期されるのは、ショートカット.appに追加した手順です。呼び出すPythonファイルや実行環境は、各Macに別途用意してください。CD用定義は`$HOME`を使い、このMacのユーザー名を埋め込みません。

## 署名と実行上の注意

署名はmacOS標準の`shortcuts sign --mode anyone`を使います。署名時には手順データがAppleの検証サービスへ送られるため、定義内にトークンやパスワードを埋め込まないでください。ライブラリは認証情報の検出・除去を行いません。

`Shortcut.export()`は署名用のコマンドだけを実行し、定義したアクションの実行やショートカット.appへの自動追加は行いません。出力は一時フォルダで作成してから公開し、失敗や競合で既存ファイルを上書きしない構成です。CD用の作成タスクは、未登録の場合だけ`app.open_import()`で追加画面を開きます。同名の登録が確認できる場合は画面を開きません。

CD用定義は`osascript`でTerminalを開き、リポジトリのルートで`mise run import-cd`を直接実行します。`.command`や`.app`は経由しません。ショートカット側の成功表示は起動完了であり、取り込み・アップロードの完了ではありません。登録済みのShell欄は自動更新されないため、定義にある`LAUNCH_SCRIPT`を貼り替えるか、作り直したショートカットを追加してください。詳細は[CD取り込みの説明](../docs/cd_import.md)を参照してください。
