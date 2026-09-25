#!/usr/bin/env -S /opt/homebrew/bin/mise exec bun@1.4.2 -- bun
import { spawnSync } from "node:child_process";
import { copyFile, mkdir, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

interface Options {
  radikoArgs: string[];
  notionArgs: string[];
  keywords?: string;
  manifestOutput?: string;
  help: boolean;
}

interface DownloadManifest {
  version: number;
  files: unknown[];
}

const projectRoot = dirname(fileURLToPath(import.meta.url));
const invocationDirectory = process.cwd();
const radikoDirectory = join(projectRoot, "tools", "radiko2");
const notionDirectory = join(projectRoot, "tools", "notion");

function printUsage(): void {
  console.log(`使い方:
  ./download_radiko_and_upload_notion.ts --keywords "伊集院光|サンドウィッチマン"

オプション:
  -k, --keywords <文字列>       番組名・パーソナリティの検索語（|でOR検索）
  -d, --date <日付>             yesterday（既定）、today、またはYYYYMMDD
      --save-directory <パス>   音声の保存先（既定: ~/Downloads）
      --exclude-stations <ID>   除外する放送局ID（カンマ区切り）
      --overwrite               既存の音声ファイルを上書きする
      --include-future          放送終了前の番組も対象にする
      --config <パス>           Notion設定ファイル
      --title-property <名前>   Notionのタイトルプロパティ名
      --file-property <名前>    NotionのFilesプロパティ名
      --no-file-property        Filesプロパティを更新しない
      --manifest-output <パス>  処理後もマニフェストを保存する
  -h, --help                    このヘルプを表示

環境変数:
  RADIKO_KEYWORDS, RADIKO_DATE, RADIKO_SAVE_DIRECTORY,
  RADIKO_EXCLUDE_STATION_IDS, RADIKO_MANIFEST_OUTPUT,
  NOTION_TOKEN, NOTION_DATABASE_ID

Notionの設定は既定で ~/.config/shortcuts_app/config.json を使用します。
`);
}

function getOptionValue(args: string[], index: number, option: string): string {
  const value = args[index + 1];
  if (!value || value.startsWith("-")) {
    throw new Error(`${option}には値を指定してください。`);
  }
  return value;
}

function parseArguments(args: string[]): Options {
  const radikoArgs: string[] = [];
  const notionArgs: string[] = [];
  let keywords: string | undefined;
  let manifestOutput: string | undefined;
  let help = false;

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    switch (arg) {
      case "-h":
      case "--help":
        help = true;
        break;
      case "-k":
      case "--keywords":
        keywords = getOptionValue(args, index, arg);
        radikoArgs.push(arg, keywords);
        index += 1;
        break;
      case "-d":
      case "--date":
      case "--save-directory":
      case "--exclude-stations": {
        const value = getOptionValue(args, index, arg);
        radikoArgs.push(arg, value);
        index += 1;
        break;
      }
      case "--overwrite":
      case "--include-future":
        radikoArgs.push(arg);
        break;
      case "--config":
      case "--title-property":
      case "--file-property": {
        const value = getOptionValue(args, index, arg);
        notionArgs.push(arg, value);
        index += 1;
        break;
      }
      case "--no-file-property":
        notionArgs.push(arg);
        break;
      case "--manifest-output":
        manifestOutput = getOptionValue(args, index, arg);
        index += 1;
        break;
      default:
        throw new Error(`不明なオプションです: ${arg}`);
    }
  }

  return { radikoArgs, notionArgs, keywords, manifestOutput, help };
}

function runBunScript(scriptPath: string, args: string[], cwd: string): number {
  const result = spawnSync(process.execPath, ["run", scriptPath, ...args], {
    cwd,
    env: process.env,
    stdio: "inherit",
  });

  if (result.error) throw result.error;
  if (result.status === null) {
    throw new Error(`${scriptPath}の実行が終了しませんでした（signal: ${result.signal ?? "unknown"}）。`);
  }
  return result.status;
}

function expandHomeDirectory(path: string): string {
  if (path === "~") return process.env.HOME ?? path;
  if (path.startsWith("~/")) return join(process.env.HOME ?? "", path.slice(2));
  return path;
}

async function loadProjectEnv(): Promise<void> {
  let content: string;
  try {
    content = await readFile(join(projectRoot, ".env"), "utf8");
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") return;
    throw error;
  }

  for (const line of content.split(/\r?\n/)) {
    const match = /^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/.exec(line);
    if (!match || process.env[match[1]] !== undefined) continue;

    let value = match[2];
    const quote = value[0];
    if ((quote === '\"' || quote === "'") && value.endsWith(quote)) {
      value = value.slice(1, -1);
      if (quote === '\"') value = value.replace(/\\n/g, "\n").replace(/\\r/g, "\r");
    } else {
      value = value.replace(/\s+#.*$/, "").trim();
    }
    process.env[match[1]] = value;
  }
}

async function readManifest(path: string): Promise<DownloadManifest> {
  const content = await readFile(path, "utf8");
  const manifest: unknown = JSON.parse(content);
  if (
    !manifest ||
    typeof manifest !== "object" ||
    (manifest as DownloadManifest).version !== 1 ||
    !Array.isArray((manifest as DownloadManifest).files)
  ) {
    throw new Error(`Radikoのマニフェスト形式が不正です: ${path}`);
  }
  return manifest as DownloadManifest;
}

async function main(): Promise<void> {
  if (!process.versions.bun) {
    throw new Error("このスクリプトの実行にはBunが必要です（bun run download_radiko_and_upload_notion.ts）。");
  }

  await loadProjectEnv();
  const options = parseArguments(process.argv.slice(2));
  if (options.help) {
    printUsage();
    return;
  }

  const keywords = options.keywords ?? process.env.RADIKO_KEYWORDS ?? "";
  if (!keywords.trim()) {
    throw new Error("検索キーワードを指定してください（--keywords または RADIKO_KEYWORDS）。");
  }

  const tempDirectory = await mkdtemp(join(tmpdir(), "radiko-notion-"));
  const manifestPath = join(tempDirectory, "downloads.json");

  try {
    console.log("=== Radikoの番組を検索・ダウンロード ===");
    const radikoStatus = runBunScript(
      join(radikoDirectory, "src", "download.ts"),
      [
        ...options.radikoArgs,
        "--manifest-include-existing",
        "--manifest-output",
        manifestPath,
      ],
      invocationDirectory,
    );

    let manifest: DownloadManifest;
    try {
      manifest = await readManifest(manifestPath);
    } catch (error) {
      if (radikoStatus !== 0) {
        throw new Error(`Radikoのダウンロードに失敗しました（終了コード: ${radikoStatus}）。`);
      }
      throw error;
    }

    const manifestOutput = options.manifestOutput ?? process.env.RADIKO_MANIFEST_OUTPUT;
    if (manifestOutput) {
      const outputPath = resolve(invocationDirectory, expandHomeDirectory(manifestOutput));
      await mkdir(dirname(outputPath), { recursive: true });
      await copyFile(manifestPath, outputPath);
      console.log(`マニフェストを保存しました: ${outputPath}`);
    }

    if (manifest.files.length === 0) {
      console.log("Notionにアップロードする番組はありませんでした。");
      if (radikoStatus !== 0) process.exitCode = radikoStatus;
      return;
    }

    console.log(`=== Notionへ${manifest.files.length}件アップロード ===`);
    const notionStatus = runBunScript(
      join(notionDirectory, "src", "cli.ts"),
      ["upload", ...options.notionArgs, "--manifest", manifestPath],
      invocationDirectory,
    );
    if (notionStatus !== 0) {
      throw new Error(`Notionへのアップロードに失敗しました（終了コード: ${notionStatus}）。`);
    }

    if (radikoStatus !== 0) {
      console.error(
        `一部のダウンロードに失敗しましたが、取得できた${manifest.files.length}件はNotionへアップロードしました。`,
      );
      process.exitCode = radikoStatus;
    } else {
      console.log("RadikoのダウンロードとNotionへのアップロードが完了しました。");
    }
  } finally {
    await rm(tempDirectory, { recursive: true, force: true });
  }
}

void main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`エラー: ${message}`);
  process.exitCode = 1;
});
