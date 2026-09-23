# notion-tools

Notion APIとファイルアップロードを扱うBunライブラリです。
`radiko2`などのドメイン固有処理は含めず、汎用的なページ作成・ファイル添付だけを担当します。

## セットアップとビルド

```bash
cd tools/notion
mise install
mise run build
```

## CLI

```bash
export NOTION_TOKEN="..."
export NOTION_DATABASE_ID="..."

# 1ファイル
./dist/notion upload ./recording.m4a \
  --title "番組タイトル" \
  --title-property "名前"

# 複数ファイル
./dist/notion upload ./one.m4a ./two.m4a

# マニフェスト
./dist/notion upload --manifest /tmp/radiko-downloads.json
```

マニフェストのパスは絶対パス、またはマニフェストからの相対パスとして解決されます。

```json
{
  "version": 1,
  "files": [
    { "path": "./episode.m4a", "title": "番組名 / 放送局 / 放送日時" }
  ]
}
```

20MiB以下はsingle-part、超過分は10MiB単位のmulti-part uploadを使用します。

## ライブラリ

```ts
import { NotionApi, NotionUploadWorkflow } from "./src";

const api = new NotionApi({ token: process.env.NOTION_TOKEN! });
const workflow = new NotionUploadWorkflow(api);

await workflow.execute({
  databaseId,
  title: "タイトル",
  filePath: "/path/to/file.m4a",
});
```

特殊処理は`NotionUploadHooks`または上位のオーケストレーターで追加します。
NotionライブラリはRadikoや音楽データベースの構造を知りません。
