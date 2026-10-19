#!/usr/bin/env -S /opt/homebrew/bin/mise exec bun@1.4.2 -- bun
import { spawnSync } from "node:child_process";
import { copyFile, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveDate } from "./tools/podcast/src/date";
import type { UploadManifestFile } from "./tools/notion/src/types";

export interface Options {
  radikoArgs: string[];
  notionArgs: string[];
  keywords?: string;
  date?: string;
  saveDirectory?: string;
  overwrite: boolean;
  podcastOnly: boolean;
  radikoOnly: boolean;
  latest: boolean;
  podcastFeeds?: string;
  manifestOutput?: string;
  help: boolean;
}

interface DownloadManifest {
  version: 1;
  generatedAt?: string;
  files: UploadManifestFile[];
}

export type ScriptRunner = (scriptPath: string, args: string[], cwd: string) => number | Promise<number>;

const projectRoot = dirname(fileURLToPath(import.meta.url));
const invocationDirectory = process.cwd();
const radikoDirectory = join(projectRoot, "tools", "radiko2");
const podcastDirectory = join(projectRoot, "tools", "podcast");
const notionDirectory = join(projectRoot, "tools", "notion");

function printUsage(): void {
  console.log(`使い方:
  ./download_radiko_and_upload_notion.ts --keywords "伊集院光|サンドウィッチマン"
  ./download_radiko_and_upload_notion.ts --podcast-only --latest

RadikoとPodcastを取得し、同じNotionデータベースに登録します。
既存のショートカットの呼び出しは変更不要です。

オプション:
  -k, --keywords <文字列>       Radikoの検索語（|でOR検索）
  -d, --date <日付>             両方の対象日: yesterday（既定）、today、YYYYMMDD
      --save-directory <パス>   両方の音声保存先（既定: ~/Downloads）
      --exclude-stations <ID>   Radikoの除外放送局ID（カンマ区切り）
      --overwrite               両方の既存音声を上書きする
      --include-future          Radikoの放送終了前の番組も対象にする
      --podcast-only            Podcastだけを処理する
      --radiko-only             従来どおりRadikoだけを処理する
      --latest                  Podcastの最新1回（--podcast-onlyと併用する初回用）
      --podcast-feeds <パス>    Podcastの番組一覧JSON
      --config <パス>           Notion設定ファイル
      --title-property <名前>   Notionのタイトルプロパティ名
      --file-property <名前>    NotionのFilesプロパティ名
      --no-file-property        Filesプロパティを更新しない
      --manifest-output <パス>  両方のファイル一覧JSONを保存する
  -h, --help                    このヘルプを表示

環境変数:
  RADIKO_KEYWORDS, RADIKO_DATE, RADIKO_SAVE_DIRECTORY,
  RADIKO_EXCLUDE_STATION_IDS, RADIKO_MANIFEST_OUTPUT, PODCAST_FEEDS_FILE,
  NOTION_TOKEN, NOTION_DATABASE_ID

日付は日本時間で確定します。Radikoは番組表上の放送日、PodcastはRSSの公開日が対象です。
Podcastの番組一覧は tools/podcast/feeds.json、Notion設定は ~/.config/shortcuts_app/config.json です。
処理済み履歴は保存しません。別DBへの移動後に同じ日を再実行すると再登録される場合があります。
`);
}

function getOptionValue(args: string[], index: number, option: string): string {
  const value = args[index + 1];
  if (!value || value.startsWith("-")) {
    throw new Error(`${option}には値を指定してください。`);
  }
  return value;
}

export function parseArguments(args: string[]): Options {
  const options: Options = {
    radikoArgs: [], notionArgs: [], overwrite: false,
    podcastOnly: false, radikoOnly: false, latest: false, help: false,
  };
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    switch (arg) {
      case "-h": case "--help": options.help = true; break;
      case "--overwrite": options.overwrite = true; break;
      case "--podcast-only": options.podcastOnly = true; break;
      case "--radiko-only": options.radikoOnly = true; break;
      case "--latest": options.latest = true; break;
      case "--include-future": options.radikoArgs.push(arg); break;
      case "--no-file-property": options.notionArgs.push(arg); break;
      case "-k": case "--keywords": case "-d": case "--date":
      case "--save-directory": case "--exclude-stations": case "--podcast-feeds":
      case "--config": case "--title-property": case "--file-property": case "--manifest-output": {
        const value = getOptionValue(args, index, arg);
        index += 1;
        if (arg === "-k" || arg === "--keywords") {
          options.keywords = value;
          options.radikoArgs.push(arg, value);
        } else if (arg === "-d" || arg === "--date") options.date = value;
        else if (arg === "--save-directory") options.saveDirectory = value;
        else if (arg === "--podcast-feeds") options.podcastFeeds = value;
        else if (arg === "--manifest-output") options.manifestOutput = value;
        else if (arg === "--exclude-stations") options.radikoArgs.push(arg, value);
        else options.notionArgs.push(arg, value);
        break;
      }
      default: throw new Error(`不明なオプションです: ${arg}`);
    }
  }
  if (options.podcastOnly && options.radikoOnly) throw new Error("--podcast-onlyと--radiko-onlyは同時に指定できません。");
  if (options.latest && (!options.podcastOnly || options.date !== undefined)) {
    throw new Error("--latestは--podcast-onlyと併用し、--dateは指定しないでください。");
  }
  return options;
}

function runBunScript(scriptPath: string, args: string[], cwd: string): number {
  const result = spawnSync(process.execPath, ["run", scriptPath, ...args], {
    cwd,
    env: { ...process.env, TZ: "Asia/Tokyo" },
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
    throw new Error(`マニフェスト形式が不正です: ${path}`);
  }
  if ((manifest as DownloadManifest).files.some((item) => !item || typeof item.path !== "string" || !item.path)) {
    throw new Error(`マニフェスト内のファイルパスが不正です: ${path}`);
  }
  return manifest as DownloadManifest;
}

export async function executeDownloads(
  options: Options,
  runScript: ScriptRunner = runBunScript,
  now = new Date(),
): Promise<number> {
  const keywords = options.keywords ?? process.env.RADIKO_KEYWORDS ?? "";
  if (!options.podcastOnly && !keywords.trim()) {
    throw new Error("Radikoの検索キーワードを指定してください（--keywords または RADIKO_KEYWORDS）。");
  }
  // 日付をここで一度だけ確定し、処理中に日付が変わっても両方に同じ値を渡します。
  const date = resolveDate(options.latest ? undefined : options.date ?? (process.env.RADIKO_DATE || undefined), now);
  const saveDirectory = options.saveDirectory ?? process.env.RADIKO_SAVE_DIRECTORY ?? "~/Downloads";
  const commonArgs = ["--save-directory", saveDirectory, ...(options.overwrite ? ["--overwrite"] : [])];
  const tempDirectory = await mkdtemp(join(tmpdir(), "audio-notion-"));
  const manifestPath = join(tempDirectory, "downloads.json");
  const sources = [];
  if (!options.podcastOnly) sources.push({
    name: "Radiko", script: join(radikoDirectory, "src", "download.ts"),
    args: [...options.radikoArgs, ...commonArgs, "--date", date],
  });
  if (!options.radikoOnly) sources.push({
    name: "Podcast", script: join(podcastDirectory, "src", "download.ts"),
    args: [
      ...commonArgs,
      ...(options.latest ? ["--latest"] : ["--date", date]),
      ...(options.podcastFeeds ? ["--feeds", options.podcastFeeds] : []),
    ],
  });

  try {
    console.log(options.latest ? "対象: Podcastの各番組の最新1回" : `対象日: ${date}（日本時間）`);
    const manifest: DownloadManifest = { version: 1, generatedAt: now.toISOString(), files: [] };
    let failed = false;
    for (const source of sources) {
      const sourceManifestPath = join(tempDirectory, `${source.name}.json`);
      console.log(`=== ${source.name}の番組を検索・ダウンロード ===`);
      try {
        const status = await runScript(source.script, [
          ...source.args, "--manifest-include-existing", "--manifest-output", sourceManifestPath,
        ], invocationDirectory);
        if (status !== 0) {
          failed = true;
          console.error(`${source.name}のダウンロードで失敗がありました（終了コード: ${status}）。`);
        }
        manifest.files.push(...(await readManifest(sourceManifestPath)).files);
      } catch (error) {
        failed = true;
        console.error(`${source.name}の処理に失敗しました: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
    const manifestOutput = options.manifestOutput ?? process.env.RADIKO_MANIFEST_OUTPUT;
    if (manifestOutput) {
      const outputPath = resolve(invocationDirectory, expandHomeDirectory(manifestOutput));
      await mkdir(dirname(outputPath), { recursive: true });
      await copyFile(manifestPath, outputPath);
      console.log(`マニフェストを保存しました: ${outputPath}`);
    }
    if (manifest.files.length === 0) {
      console.log("Notionにアップロードする番組はありませんでした。");
      return failed ? 1 : 0;
    }

    console.log(`=== Notionへ${manifest.files.length}件アップロード ===`);
    const notionStatus = await runScript(
      join(notionDirectory, "src", "cli.ts"),
      ["upload", ...options.notionArgs, "--manifest", manifestPath],
      invocationDirectory,
    );
    if (notionStatus !== 0) {
      console.error(`Notionへのアップロードで失敗がありました（終了コード: ${notionStatus}）。`);
      return 1;
    }
    if (failed) {
      console.error(`一部の取得に失敗しましたが、取得できた${manifest.files.length}件はNotionへアップロードしました。`);
    } else {
      console.log("音声のダウンロードとNotionへのアップロードが完了しました。");
    }
    return failed ? 1 : 0;
  } finally {
    await rm(tempDirectory, { recursive: true, force: true });
  }
}

async function main(): Promise<void> {
  if (!process.versions.bun) {
    throw new Error("このスクリプトの実行にはBunが必要です（bun run download_radiko_and_upload_notion.ts）。");
  }
  await loadProjectEnv();
  const options = parseArguments(process.argv.slice(2));
  if (options.help) return printUsage();
  process.exitCode = await executeDownloads(options);
}

if (import.meta.main) {
  void main().catch((error) => {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`エラー: ${message}`);
    process.exitCode = 1;
  });
}
