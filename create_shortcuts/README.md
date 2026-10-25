# ショートカットの作成と管理

ショートカット.app用の共通ライブラリと、用途別のPython定義をこのフォルダで管理します。実際のCD読み取りやNotion登録のコードは、従来のスクリプトに残します。

```text
create_shortcuts/
  .mise.toml                  定義名と同名の作成タスク
  __init__.py                 Shortcutの公開入口
  builder.py                  アクション・plist生成・署名・出力
  definitions/
    cd_import.py              CD取り込み用の手順定義と生成コマンド
```

## 既存のショートカットを生成する

このフォルダで、定義名と同じタスクを実行します。

```bash
cd ~/github/shortcuts_app/create_shortcuts
mise run cd-import
```

タスク名は定義ファイル名の`_`を`-`に置き換えたものに揃えます。`definitions/cd_import.py`には`cd-import`を対応させ、別名や互換エイリアスは作りません。

生成先は`~/Downloads/CDをNotionへ（ショートカット）.shortcut`です。生成・署名だけを行い、インポートや実行はしません。既存ファイルは上書きしないため、作り直す場合は出力先を変えるか、既存の生成物を手動で移動してください。

```bash
mise run cd-import --output ~/Downloads/CD-import-new.shortcut
```

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

ファイル生成は署名用のコマンドだけを実行し、定義したアクションの実行やショートカット.appへの自動追加は行いません。出力は一時フォルダで作成してから公開し、失敗や競合で既存ファイルを上書きしない構成です。

CD用定義はTerminalで既存の`.command`を開きます。ショートカット側の成功表示は起動完了であり、取り込み・アップロードの完了ではありません。詳細は[CD取り込みの説明](../docs/cd_import.md)を参照してください。
