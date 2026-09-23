import { readFile } from "fs/promises";
import { basename, dirname, extname, isAbsolute, resolve } from "path";
import { homedir } from "os";
import {
  initializeConfig,
  readAppConfig,
  resolveConfigPath,
  type AppConfig,
  type NotionConfig,
} from "./config";
import { NotionApi } from "./notion-api";
import { NotionUploadWorkflow } from "./workflow";
import type { NotionUploadResult, UploadManifest, UploadManifestFile } from "./types";

interface CliOptions {
  token: string;
  databaseId: string;
  titleProperty: string;
  filePropertyName?: string | null;
  filePropertySpecified: boolean;
  items: UploadManifestFile[];
}

function printUsage(): void {
  console.log(`使い方:
  notion [--config <パス>] upload <ファイル...>
  notion [--config <パス>] upload --manifest <マニフェスト.json>
  notion [--config <パス>] config init
  notion [--config <パス>] config path
  notion [--config <パス>] config show

オプション:
      --config <パス>          設定ファイル（既定: ~/.config/shortcuts_app/config.json）
      --database-id <ID>       NotionデータベースID
      --manifest <パス>         アップロード対象のマニフェスト
      --title <タイトル>       ファイル1つの場合のページタイトル
      --title-property <名前>  タイトルプロパティ名
      --file-property <名前>   添付先のFilesプロパティ名
      --no-file-property       Filesプロパティを更新しない
  -h, --help                   このヘルプを表示

設定:
  notion config init           設定ファイルのテンプレートを生成
  notion config path           使用する設定ファイルのパスを表示
  notion config show           設定内容を表示（tokenはマスク）

環境変数は設定ファイルの値がない場合のフォールバックとして利用できます:
  NOTION_TOKEN, NOTION_DATABASE_ID
`);
}

function printConfigUsage(): void {
  console.log(`使い方:
  notion config init [--force]
  notion config path
  notion config show

config initは設定ファイルのテンプレートを生成します。
既存ファイルを上書きする場合は--forceを指定してください。
`);
}

function getOptionValue(args: string[], index: number, option: string): string {
  const value = args[index + 1];
  if (!value || value.startsWith("-")) {
    throw new Error(`${option}には値を指定してください。`);
  }
  return value;
}

function extractConfigOption(args: string[]): { args: string[]; configPath: string } {
  let configPath: string | undefined;
  const remaining: string[] = [];

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--config") {
      const value = getOptionValue(args, index, arg);
      configPath = value;
      index += 1;
    } else {
      remaining.push(arg);
    }
  }

  return { args: remaining, configPath: resolveConfigPath(configPath) };
}

async function parseArguments(
  args: string[],
  config: AppConfig | undefined,
  configPath: string,
): Promise<CliOptions | undefined> {
  if (args.length === 0 || args[0] === "-h" || args[0] === "--help") {
    printUsage();
    return undefined;
  }
  if (args[0] !== "upload") {
    throw new Error(`不明なコマンドです: ${args[0]}`);
  }

  const notion = config?.notion;
  let token = notion?.token || process.env.NOTION_TOKEN || "";
  let databaseId = notion?.databaseId || process.env.NOTION_DATABASE_ID || "";
  let manifestPath: string | undefined;
  let title: string | undefined;
  let titleProperty =
    notion?.titleProperty || process.env.NOTION_TITLE_PROPERTY || "Name";
  let filePropertyName: string | null | undefined =
    notion?.filePropertyName || process.env.NOTION_FILE_PROPERTY;
  let filePropertySpecified = Boolean(filePropertyName);
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
  if (!token || !databaseId) {
    throw new Error(
      `Notion設定が不足しています。設定ファイルを編集してください: ${configPath}（初期化: notion config init）`,
    );
  }

  const items = manifestPath
    ? await readManifest(manifestPath)
    : filePaths.map((filePath) => ({
        path: filePath,
        ...(title ? { title } : {}),
      }));
  if (items.length === 0) throw new Error("アップロードするファイルがありません。");

  return {
    token,
    databaseId,
    titleProperty,
    filePropertyName,
    filePropertySpecified,
    items,
  };
}

async function readManifest(manifestPath: string): Promise<UploadManifestFile[]> {
  const resolvedManifestPath = resolveInputPath(manifestPath);
  const manifestText = await readFile(resolvedManifestPath, "utf8");
  const manifest = JSON.parse(manifestText) as Partial<UploadManifest>;
  if (manifest.version !== 1 || !Array.isArray(manifest.files)) {
    throw new Error("未対応のマニフェスト形式です。");
  }

  const baseDirectory = dirname(resolveManifestPath(resolvedManifestPath, process.cwd()));
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

function resolveInputPath(filePath: string): string {
  if (filePath === "~") return homedir();
  if (filePath.startsWith("~/")) return resolve(homedir(), filePath.slice(2));
  return isAbsolute(filePath) ? filePath : resolve(process.cwd(), filePath);
}

function resolveManifestPath(filePath: string, baseDirectory: string): string {
  if (filePath === "~") return homedir();
  if (filePath.startsWith("~/")) return resolve(homedir(), filePath.slice(2));
  return isAbsolute(filePath) ? filePath : resolve(baseDirectory, filePath);
}

function defaultTitle(filePath: string): string {
  return basename(filePath, extname(filePath));
}

async function runConfigCommand(args: string[], configPath: string): Promise<void> {
  const command = args[1] ?? "";
  if (!command || command === "-h" || command === "--help") {
    printConfigUsage();
    return;
  }

  switch (command) {
    case "init": {
      const initArgs = args.slice(2);
      if (initArgs.includes("-h") || initArgs.includes("--help")) {
        printConfigUsage();
        return;
      }
      const force = initArgs.includes("--force");
      const unexpected = initArgs.filter((arg) => arg !== "--force");
      if (unexpected.length > 0) throw new Error(`不明なオプションです: ${unexpected[0]}`);
      await initializeConfig(configPath, force);
      console.log(`設定ファイルを生成しました: ${configPath}`);
      console.log("tokenとdatabaseIdを編集してください。");
      return;
    }
    case "path":
      if (args.length > 2) throw new Error("config pathには追加の引数を指定できません。");
      console.log(configPath);
      return;
    case "show": {
      if (args.length > 2) throw new Error("config showには追加の引数を指定できません。");
      const config = await readAppConfig(configPath);
      if (!config) {
        console.log(`設定ファイルがありません: ${configPath}`);
        return;
      }
      console.log(JSON.stringify(maskToken(config), null, 2));
      return;
    }
    default:
      throw new Error("configのサブコマンドはinit、path、showのいずれかです。");
  }
}

function maskToken(config: AppConfig): AppConfig {
  const notion: NotionConfig | undefined = config.notion
    ? { ...config.notion, token: config.notion.token ? "********" : "" }
    : undefined;
  return { ...config, notion };
}

async function main(): Promise<void> {
  const extracted = extractConfigOption(process.argv.slice(2));
  const { args, configPath } = extracted;

  if (args[0] === "config") {
    await runConfigCommand(args, configPath);
    return;
  }

  const config = await readAppConfig(configPath);
  const options = await parseArguments(args, config, configPath);
  if (!options) return;

  const api = new NotionApi({ token: options.token });
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
