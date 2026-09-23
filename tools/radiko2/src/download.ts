import { access, constants, mkdir } from "fs/promises";
import { RadikoClient, RadikoProgram } from "./radiko-client";
import { logger } from "./logger";
import { expandHomeDirectory, getSearchKeywords, matchesSearch, resolveDate } from "./utils";

interface CliOptions {
  keywords: string;
  date: string;
  saveDirectory: string;
  ffmpegPath: string;
  excludeStationIds: string[];
  overwrite: boolean;
  includeFuture: boolean;
}

function printUsage(): void {
  console.log(`使い方:
  pnpm run download --keywords "伊集院光|サンドウィッチマン"

オプション:
  -k, --keywords <文字列>       番組名・パーソナリティの検索語（|でOR検索）
  -d, --date <日付>             yesterday（既定）、today、またはYYYYMMDD
      --save-directory <パス>   保存先（既定: ~/Downloads）
      --ffmpeg-path <パス>      ffmpegのパス（既定: ffmpeg）
      --exclude-stations <ID>   除外する放送局ID（カンマ区切り）
      --overwrite               既存ファイルを上書きする
      --include-future          放送終了前の番組も対象にする
  -h, --help                    このヘルプを表示

環境変数でも指定できます:
  RADIKO_KEYWORDS, RADIKO_DATE, RADIKO_SAVE_DIRECTORY,
  RADIKO_FFMPEG_PATH, RADIKO_EXCLUDE_STATION_IDS
`);
}

function getOptionValue(args: string[], index: number, option: string): string {
  const value = args[index + 1];
  if (!value || value.startsWith("-")) {
    throw new Error(`${option}には値を指定してください。`);
  }
  return value;
}

function parseArguments(args: string[]): Partial<CliOptions> & { help?: boolean } {
  const options: Partial<CliOptions> & { help?: boolean } = {};

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    switch (arg) {
      case "-h":
      case "--help":
        options.help = true;
        break;
      case "-k":
      case "--keywords":
        options.keywords = getOptionValue(args, index, arg);
        index += 1;
        break;
      case "-d":
      case "--date":
        options.date = getOptionValue(args, index, arg);
        index += 1;
        break;
      case "--save-directory":
        options.saveDirectory = getOptionValue(args, index, arg);
        index += 1;
        break;
      case "--ffmpeg-path":
        options.ffmpegPath = getOptionValue(args, index, arg);
        index += 1;
        break;
      case "--exclude-stations":
        options.excludeStationIds = getOptionValue(args, index, arg)
          .split(",")
          .map((id) => id.trim())
          .filter(Boolean);
        index += 1;
        break;
      case "--overwrite":
        options.overwrite = true;
        break;
      case "--include-future":
        options.includeFuture = true;
        break;
      default:
        throw new Error(`不明なオプションです: ${arg}`);
    }
  }

  return options;
}

function buildOptions(args: string[]): CliOptions {
  const parsed = parseArguments(args);
  if (parsed.help) {
    printUsage();
    process.exit(0);
  }

  const keywords = parsed.keywords ?? process.env.RADIKO_KEYWORDS ?? "";
  if (getSearchKeywords(keywords).length === 0) {
    throw new Error("検索キーワードを指定してください（--keywords または RADIKO_KEYWORDS）。");
  }

  const saveDirectory = expandHomeDirectory(
    parsed.saveDirectory ?? process.env.RADIKO_SAVE_DIRECTORY ?? "~/Downloads",
  );
  const excludeStationIds = parsed.excludeStationIds ??
    (process.env.RADIKO_EXCLUDE_STATION_IDS ?? "")
      .split(",")
      .map((id) => id.trim())
      .filter(Boolean);

  return {
    keywords,
    date: resolveDate(parsed.date ?? process.env.RADIKO_DATE),
    saveDirectory,
    ffmpegPath: parsed.ffmpegPath ?? process.env.RADIKO_FFMPEG_PATH ?? "ffmpeg",
    excludeStationIds,
    overwrite: parsed.overwrite ?? false,
    includeFuture: parsed.includeFuture ?? false,
  };
}

function parseRadikoDateTime(value: string): Date {
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6)) - 1;
  const day = Number(value.slice(6, 8));
  const hour = Number(value.slice(8, 10));
  const minute = Number(value.slice(10, 12));
  const second = Number(value.slice(12, 14));
  return new Date(year, month, day, hour, minute, second);
}

function isProgramFinished(program: RadikoProgram): boolean {
  return parseRadikoDateTime(program.to).getTime() <= Date.now();
}

async function fileExists(filePath: string): Promise<boolean> {
  try {
    await access(filePath, constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

async function run(options: CliOptions): Promise<void> {
  await mkdir(options.saveDirectory, { recursive: true });

  const keywords = getSearchKeywords(options.keywords);
  console.log(`検索語: ${keywords.join(" OR ")}`);
  console.log(`対象日: ${options.date}`);
  console.log(`保存先: ${options.saveDirectory}`);

  logger.info("自動ダウンロードを開始しました", { ...options, keywords });
  const client = new RadikoClient(options.ffmpegPath);
  await client.authenticate();

  const stations = (await client.getStationList()).filter(
    (station) => !options.excludeStationIds.includes(station.id),
  );
  if (stations.length === 0) {
    throw new Error("利用可能な放送局が見つかりませんでした。");
  }

  const stationPrograms = await Promise.all(
    stations.map(async (station) => client.getPrograms(station.id, options.date)),
  );
  const matchingPrograms = stationPrograms
    .flat()
    .filter((program) => matchesSearch(program, keywords));

  console.log(`検索結果: ${matchingPrograms.length}件`);
  if (matchingPrograms.length === 0) {
    logger.info("検索に一致する番組はありませんでした");
    return;
  }

  let downloaded = 0;
  let skippedExisting = 0;
  let skippedFuture = 0;
  let failed = 0;

  for (const program of matchingPrograms) {
    if (!options.includeFuture && !isProgramFinished(program)) {
      skippedFuture += 1;
      console.log(`スキップ（放送終了前）: ${program.stationName} / ${program.title}`);
      continue;
    }

    const outputPath = client.getProgramOutputPath(program, options.saveDirectory);
    if (!options.overwrite && await fileExists(outputPath)) {
      skippedExisting += 1;
      console.log(`スキップ（既存）: ${outputPath}`);
      continue;
    }

    console.log(`ダウンロード中: ${program.stationName} / ${program.title}`);
    try {
      await client.recordProgram(
        program,
        program.stationId,
        program.title,
        program.img,
        program.ft,
        program.to,
        options.saveDirectory,
      );
      downloaded += 1;
      console.log(`完了: ${outputPath}`);
      logger.info("番組のダウンロードが完了しました", { program, outputPath });
    } catch (error) {
      failed += 1;
      const message = error instanceof Error ? error.message : String(error);
      console.error(`失敗: ${program.title}: ${message}`);
      logger.error("番組のダウンロードに失敗しました", { program, error: message });
    }
  }

  console.log(
    `結果: ダウンロード${downloaded}件、既存${skippedExisting}件、` +
      `放送終了前${skippedFuture}件、失敗${failed}件`,
  );
  if (failed > 0) {
    throw new Error(`${failed}件のダウンロードに失敗しました。`);
  }
}

async function main(): Promise<void> {
  try {
    const options = buildOptions(process.argv.slice(2));
    await run(options);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`エラー: ${message}`);
    logger.error("自動ダウンロードに失敗しました", message);
    process.exitCode = 1;
  }
}

void main();
