import { mkdir, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveDate } from "./date";
import { downloadPodcasts, readFeedSources } from "./downloader";
import { logger } from "./logger";

export interface CliOptions {
  feedsFile: string;
  saveDirectory: string;
  date?: string;
  latest: boolean;
  overwrite: boolean;
  manifestOutput?: string;
  manifestIncludeExisting: boolean;
  help: boolean;
}

const defaultFeedsFile = fileURLToPath(new URL("../feeds.json", import.meta.url));

function expandHome(path: string): string {
  return path === "~" ? homedir() : path.startsWith("~/") ? join(homedir(), path.slice(2)) : path;
}

export function parseArguments(args: string[], now = new Date()): CliOptions {
  const options: CliOptions = {
    feedsFile: process.env.PODCAST_FEEDS_FILE ?? defaultFeedsFile,
    saveDirectory: process.env.PODCAST_SAVE_DIRECTORY ?? "~/Downloads",
    latest: false,
    overwrite: false,
    manifestIncludeExisting: false,
    help: false,
  };
  let date: string | undefined;
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    switch (arg) {
      case "-h": case "--help": options.help = true; break;
      case "--latest": options.latest = true; break;
      case "--overwrite": options.overwrite = true; break;
      case "--manifest-include-existing": options.manifestIncludeExisting = true; break;
      case "-d": case "--date": case "--feeds": case "--save-directory": case "--manifest-output": {
        const value = args[++index];
        if (!value || value.startsWith("-")) throw new Error(`${arg}には値を指定してください。`);
        if (arg === "-d" || arg === "--date") date = value;
        else if (arg === "--feeds") options.feedsFile = value;
        else if (arg === "--save-directory") options.saveDirectory = value;
        else options.manifestOutput = value;
        break;
      }
      default: throw new Error(`不明なオプションです: ${arg}`);
    }
  }
  if (options.latest && date !== undefined) throw new Error("--latestと--dateは同時に指定できません。");
  if (!options.help && !options.latest) options.date = resolveDate(date, now);
  options.feedsFile = resolve(expandHome(options.feedsFile));
  options.saveDirectory = resolve(expandHome(options.saveDirectory));
  if (options.manifestOutput) options.manifestOutput = resolve(expandHome(options.manifestOutput));
  return options;
}

function printUsage(): void {
  console.log(`使い方:
  bun run tools/podcast/src/download.ts --date yesterday
  bun run tools/podcast/src/download.ts --latest

オプション:
  -d, --date <日付>             yesterday（既定）、today、またはYYYYMMDD
      --latest                  各番組の公開済み最新1回だけを取得（初回用）
      --feeds <パス>            番組一覧JSON（既定: tools/podcast/feeds.json）
      --save-directory <パス>   保存先（既定: ~/Downloads）
      --overwrite               既存の音声を上書き
      --manifest-output <パス>  Notion用のファイル一覧JSONを保存
      --manifest-include-existing 既存音声もファイル一覧に含める
  -h, --help                    このヘルプを表示

日付はRSSの公開日時を日本時間に変換して判定します。処理済み履歴は保存しません。
MP3の既存タイトル・番組名・カバー画像を維持し、不足時のみRSSから補完します。
環境変数: PODCAST_FEEDS_FILE, PODCAST_SAVE_DIRECTORY
ログ: ~/Library/Logs/shortcuts_app/podcast.log
`);
}

async function main(): Promise<void> {
  const options = parseArguments(process.argv.slice(2));
  if (options.help) return printUsage();
  logger.log(`対象: ${options.latest ? "各番組の最新1回" : `${options.date}公開分（日本時間）`}`);
  logger.log(`保存先: ${options.saveDirectory}`);
  const result = await downloadPodcasts({
    ...options,
    feeds: await readFeedSources(options.feedsFile),
  }, { logger });
  if (options.manifestOutput) {
    await mkdir(dirname(options.manifestOutput), { recursive: true });
    await writeFile(options.manifestOutput, `${JSON.stringify({
      version: 1,
      generatedAt: new Date().toISOString(),
      files: result.files,
    }, null, 2)}\n`, "utf8");
  }
  if (result.failed > 0) process.exitCode = 1;
}

if (import.meta.main) {
  void main().catch((error) => {
    logger.error(`エラー: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  });
}
