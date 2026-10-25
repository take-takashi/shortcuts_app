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

## 登録済みショートカットの更新画面を開く

このフォルダで、定義名と同じタスクを実行します。

```bash
cd ~/github/shortcuts_app/create_shortcuts
mise run cd-import
```

タスク名は定義ファイル名の`_`を`-`に置き換えたものに揃えます。`definitions/cd_import.py`には`cd-import`を対応させ、別名や互換エイリアスは作りません。

CD用の登録名は`CDを取り込んでNotionへUpload`です。同名の登録が1件であることを確認して名前・UUIDを表示し、作成・署名後にショートカット.appの追加画面を開きます。最後の置換・追加は画面で確認してください。アプリ内のショートカットを無確認で更新したり、取り込みを実行したりはしません。

署名中に対象のUUIDが変わった場合や、登録が0件・複数ある場合は停止します。名前を変更した場合はPython定義の`NAME`も揃えてください。単に名前が見つからないという理由で、新規作成へ自動切り替えはしません。

初回で本当に未登録の場合だけ、`mise run cd-import --new`を使います。同名の登録がある場合は`--new`を受け付けません。

生成物は`~/Library/Caches/shortcuts_app/create_shortcuts/cd-import/実行ごとの識別子/`へ保存します。毎回別のフォルダへ同じ名前のファイルを作るため、以前の生成物は上書きしません。保存先を指定する場合も、登録名とファイル名を揃えます。

```bash
mise run cd-import --output "$HOME/Downloads/cd-import-new/CDを取り込んでNotionへUpload.shortcut"
```

UUIDは追加画面を開く前の対象確認に使います。UUIDを指定してアプリ内の本体を更新する標準APIはなく、置換後に同じUUIDが維持されることも保証しません。

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

`Shortcut.export()`は署名用のコマンドだけを実行し、定義したアクションの実行やショートカット.appへの自動追加は行いません。出力は一時フォルダで作成してから公開し、失敗や競合で既存ファイルを上書きしない構成です。CD用の作成タスクはその後に登録対象を再確認し、`app.open_import()`で追加画面を開くところまで行います。

CD用定義は`osascript`でTerminalを開き、リポジトリのルートで`mise run import-cd`を直接実行します。`.command`や`.app`は経由しません。ショートカット側の成功表示は起動完了であり、取り込み・アップロードの完了ではありません。登録済みのShell欄は自動更新されないため、定義にある`LAUNCH_SCRIPT`を貼り替えるか、作り直したショートカットを追加してください。詳細は[CD取り込みの説明](../docs/cd_import.md)を参照してください。
