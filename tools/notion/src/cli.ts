import { readFile } from "fs/promises";
import { basename, dirname, extname, isAbsolute, resolve } from "path";
import { homedir } from "os";
import { NotionApi } from "./notion-api";
import { NotionUploadWorkflow } from "./workflow";
import type { NotionUploadResult, UploadManifest, UploadManifestFile } from "./types";

interface CliOptions {
  databaseId: string;
  titleProperty: string;
  filePropertyName?: string | null;
  filePropertySpecified: boolean;
  items: UploadManifestFile[];
}

function printUsage(): void {
  console.log(`使い方:
  notion upload <ファイル...>
  notion upload --manifest <マニフェスト.json>

オプション:
      --database-id <ID>       NotionデータベースID（既定: NOTION_DATABASE_ID）
      --manifest <パス>         アップロード対象のマニフェスト
      --title <タイトル>       ファイル1つの場合のページタイトル
      --title-property <名前>  タイトルプロパティ名（既定: Name）
      --file-property <名前>   添付先のFilesプロパティ名
      --no-file-property       Filesプロパティを更新しない
  -h, --help                   このヘルプを表示

環境変数:
  NOTION_TOKEN
  NOTION_DATABASE_ID
`);
}

function getOptionValue(args: string[], index: number, option: string): string {
  const value = args[index + 1];
  if (!value || value.startsWith("-")) {
    throw new Error(`${option}には値を指定してください。`);
  }
  return value;
}

async function parseArguments(args: string[]): Promise<CliOptions | undefined> {
  if (args.length === 0 || args[0] === "-h" || args[0] === "--help") {
    printUsage();
    return undefined;
  }
  if (args[0] !== "upload") {
    throw new Error(`不明なコマンドです: ${args[0]}`);
  }

  let databaseId = process.env.NOTION_DATABASE_ID ?? "";
  let manifestPath: string | undefined;
  let title: string | undefined;
  let titleProperty = "Name";
  let filePropertyName: string | null | undefined;
  let filePropertySpecified = false;
  const filePaths: string[] = [];

  for (let index = 1; index < args.length; index += 1) {
    const arg = args[index];
    switch (arg) {
      case "-h":
      case "--help":
        printUsage();
        return undefined;
      case "--database-id":
        databaseId = getOptionValue(args, index, arg);
        index += 1;
        break;
      case "--manifest":
        manifestPath = getOptionValue(args, index, arg);
        index += 1;
        break;
      case "--title":
        title = getOptionValue(args, index, arg);
        index += 1;
        break;
      case "--title-property":
        titleProperty = getOptionValue(args, index, arg);
        index += 1;
        break;
      case "--file-property":
        filePropertyName = getOptionValue(args, index, arg);
        filePropertySpecified = true;
        index += 1;
        break;
      case "--no-file-property":
        filePropertyName = null;
        filePropertySpecified = true;
        break;
      default:
        if (arg.startsWith("-")) throw new Error(`不明なオプションです: ${arg}`);
        filePaths.push(arg);
        break;
    }
  }

  if (manifestPath && filePaths.length > 0) {
    throw new Error("--manifestとファイルパスは同時に指定できません。");
  }
  if (title && (manifestPath || filePaths.length !== 1)) {
    throw new Error("--titleはファイルを1つ指定する場合のみ使用できます。");
  }
  if (!databaseId) throw new Error("NotionデータベースIDを指定してください。");

  const items = manifestPath
    ? await readManifest(manifestPath)
    : filePaths.map((filePath) => ({
        path: filePath,
        ...(title ? { title } : {}),
      }));
  if (items.length === 0) throw new Error("アップロードするファイルがありません。");

  return {
    databaseId,
    titleProperty,
    filePropertyName,
    filePropertySpecified,
    items,
  };
}

async function readManifest(manifestPath: string): Promise<UploadManifestFile[]> {
  const manifestText = await readFile(manifestPath, "utf8");
  const manifest = JSON.parse(manifestText) as Partial<UploadManifest>;
  if (manifest.version !== 1 || !Array.isArray(manifest.files)) {
    throw new Error("未対応のマニフェスト形式です。");
  }

  const baseDirectory = dirname(resolve(manifestPath));
  return manifest.files.map((item) => {
    if (!item || typeof item.path !== "string" || item.path.length === 0) {
      throw new Error("マニフェスト内のファイルパスが不正です。");
    }
    return {
      ...item,
      path: resolveManifestPath(item.path, baseDirectory),
    };
  });
}

function resolveManifestPath(filePath: string, baseDirectory: string): string {
  if (filePath === "~") return homedir();
  if (filePath.startsWith("~/")) return resolve(homedir(), filePath.slice(2));
  return isAbsolute(filePath) ? filePath : resolve(baseDirectory, filePath);
}

function defaultTitle(filePath: string): string {
  return basename(filePath, extname(filePath));
}

async function main(): Promise<void> {
  const options = await parseArguments(process.argv.slice(2));
  if (!options) return;

  const token = process.env.NOTION_TOKEN;
  if (!token) throw new Error("環境変数NOTION_TOKENが設定されていません。");

  const api = new NotionApi({ token });
  const workflow = new NotionUploadWorkflow(api);
  const uploaded: NotionUploadResult[] = [];
  const failures: { path: string; error: string }[] = [];

  for (const item of options.items) {
    const filePropertyName = options.filePropertySpecified
      ? options.filePropertyName
      : item.filePropertyName;
    const title = item.title ?? defaultTitle(item.path);

    try {
      const result = await workflow.execute({
        databaseId: options.databaseId,
        title,
        titleProperty: options.titleProperty,
        filePath: item.path,
        properties: item.properties,
        filePropertyName,
        fileType: item.fileType,
      });
      uploaded.push(result);
      console.log(`完了: ${item.path}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      failures.push({ path: item.path, error: message });
      console.error(`失敗: ${item.path}: ${message}`);
    }
  }

  console.log(JSON.stringify({ uploaded, failures }, null, 2));
  if (failures.length > 0) process.exitCode = 1;
}

void main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`エラー: ${message}`);
  process.exitCode = 1;
});
