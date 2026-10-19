import { createHash } from "node:crypto";
import { createWriteStream } from "node:fs";
import { mkdir, mkdtemp, readFile, rename, rm, stat } from "node:fs/promises";
import { join, resolve } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import type { ReadableStream as NodeReadableStream } from "node:stream/web";
import { formatJstDateTime } from "./date";
import { parseFeed, selectEpisodes, type FeedSource, type PodcastEpisode, type PodcastFeed } from "./feed";
import { supplementMetadata, type DownloadLogger } from "./metadata";

export interface DownloadManifestEntry {
  path: string;
  title: string;
  metadata: Record<string, unknown>;
}

export interface DownloadOptions {
  feeds: FeedSource[];
  saveDirectory: string;
  date?: string;
  latest?: boolean;
  overwrite?: boolean;
  manifestIncludeExisting?: boolean;
  now?: Date;
}

export interface DownloadResult {
  files: DownloadManifestEntry[];
  downloaded: number;
  existing: number;
  failed: number;
}

export async function readFeedSources(path: string): Promise<FeedSource[]> {
  const entries: unknown = JSON.parse(await readFile(path, "utf8"));
  if (!Array.isArray(entries) || entries.length === 0) {
    throw new Error("Podcast設定には番組の配列（1件以上）を指定してください。");
  }
  const ids = new Set<string>();
  return entries.map((entry: unknown) => {
    if (!entry || typeof entry !== "object" || !("id" in entry) || !("url" in entry) ||
        typeof entry.id !== "string" || !entry.id.trim() || typeof entry.url !== "string") {
      throw new Error("Podcast設定の各番組にはidとurlが必要です。");
    }
    const url = new URL(entry.url);
    if (!["https:", "http:"].includes(url.protocol)) throw new Error("RSSにはHTTP(S)のURLを指定してください。");
    if (ids.has(entry.id)) throw new Error(`Podcastのidが重複しています: ${entry.id}`);
    ids.add(entry.id);
    return { id: entry.id, url: url.href };
  });
}

function safeFilenamePart(value: string, maxBytes: number): string {
  const safe = value.replace(/[\x00-\x1f\x7f/\\:*?"<>|]/g, "_").trim();
  let output = "";
  for (const character of safe) {
    if (Buffer.byteLength(output + character) > maxBytes) break;
    output += character;
  }
  return output || "untitled";
}

export function getEpisodeOutputPath(
  source: FeedSource,
  feed: PodcastFeed,
  episode: PodcastEpisode,
  saveDirectory: string,
): string {
  const timestamp = formatJstDateTime(episode.publishedAt).replace(/[- :]/g, "");
  const hash = createHash("sha256").update(`${source.id}\0${episode.id}`).digest("hex").slice(0, 12);
  const show = safeFilenamePart(feed.title, 90);
  const title = safeFilenamePart(episode.title, 110);
  return resolve(saveDirectory, `${timestamp}_${show}_${title}_${hash}.mp3`);
}

function manifestEntry(
  source: FeedSource,
  feed: PodcastFeed,
  episode: PodcastEpisode,
  path: string,
): DownloadManifestEntry {
  return {
    path,
    title: `${episode.title} / ${feed.title} / ${formatJstDateTime(episode.publishedAt)}`,
    metadata: {
      source: "podcast",
      feedId: source.id,
      feedUrl: source.url,
      episodeId: episode.id,
      showTitle: feed.title,
      publishedAt: episode.publishedAt.toISOString(),
    },
  };
}

async function nonemptyFileExists(path: string): Promise<boolean> {
  try {
    const info = await stat(path);
    return info.isFile() && info.size > 0;
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") return false;
    throw error;
  }
}

async function downloadEpisode(
  feed: PodcastFeed,
  episode: PodcastEpisode,
  outputPath: string,
  saveDirectory: string,
  fetcher: typeof fetch,
  logger: DownloadLogger,
): Promise<void> {
  const extension = new URL(episode.audioUrl).pathname.toLowerCase();
  if (!["audio/mpeg", "audio/mp3"].includes(episode.mediaType) && !(episode.mediaType === "" && extension.endsWith(".mp3"))) {
    throw new Error(`MP3以外の音声形式には未対応です: ${episode.mediaType || episode.audioUrl}`);
  }
  const tempDirectory = await mkdtemp(join(saveDirectory, ".podcast-"));
  try {
    const tempPath = join(tempDirectory, "audio.mp3");
    const response = await fetcher(episode.audioUrl, {
      headers: { "User-Agent": "shortcuts_app/podcast" },
      signal: AbortSignal.timeout(10 * 60_000),
    });
    if (!response.ok || !response.body) throw new Error(`音声の取得に失敗しました: HTTP ${response.status}`);
    const contentType = response.headers.get("content-type") ?? "";
    if (/^(text\/|application\/(json|xml))/i.test(contentType)) {
      await response.body.cancel();
      throw new Error(`音声ではない応答です: ${contentType}`);
    }
    // Bun/DOMとNodeでReadableStreamの型定義が異なるため、Node側の型へ合わせます。
    await pipeline(Readable.fromWeb(response.body as unknown as NodeReadableStream), createWriteStream(tempPath, { flags: "wx" }));
    if ((await stat(tempPath)).size === 0) throw new Error("音声ファイルが空です。");
    await supplementMetadata(tempPath, feed, episode, fetcher, logger);
    // 完了したファイルだけを公開し、失敗時は既存の音声を残します。
    await rename(tempPath, outputPath);
  } finally {
    await rm(tempDirectory, { recursive: true, force: true });
  }
}

export async function downloadPodcasts(
  options: DownloadOptions,
  dependencies: { fetcher?: typeof fetch; logger?: DownloadLogger } = {},
): Promise<DownloadResult> {
  const fetcher = dependencies.fetcher ?? fetch;
  const logger = dependencies.logger ?? console;
  const now = options.now ?? new Date();
  const saveDirectory = resolve(options.saveDirectory);
  await mkdir(saveDirectory, { recursive: true });
  const result: DownloadResult = { files: [], downloaded: 0, existing: 0, failed: 0 };

  for (const source of options.feeds) {
    try {
      const response = await fetcher(source.url, {
        headers: { "User-Agent": "shortcuts_app/podcast" },
        signal: AbortSignal.timeout(60_000),
      });
      if (!response.ok) throw new Error(`RSSの取得に失敗しました: HTTP ${response.status}`);
      const feed = parseFeed(await response.text(), response.url || source.url);
      for (const warning of feed.warnings) logger.warn(`${feed.title}: ${warning}`);
      const episodes = selectEpisodes(feed, { date: options.date, latest: options.latest, now });
      logger.log(`${feed.title}: 対象${episodes.length}件`);
      for (const episode of episodes) {
        const outputPath = getEpisodeOutputPath(source, feed, episode, saveDirectory);
        try {
          if (!options.overwrite && await nonemptyFileExists(outputPath)) {
            result.existing += 1;
            if (options.manifestIncludeExisting) result.files.push(manifestEntry(source, feed, episode, outputPath));
            logger.log(`スキップ（既存）: ${outputPath}`);
            continue;
          }
          logger.log(`ダウンロード中: ${feed.title} / ${episode.title}`);
          await downloadEpisode(feed, episode, outputPath, saveDirectory, fetcher, logger);
          result.downloaded += 1;
          result.files.push(manifestEntry(source, feed, episode, outputPath));
          logger.log(`完了: ${outputPath}`);
        } catch (error) {
          result.failed += 1;
          logger.error(`失敗: ${feed.title} / ${episode.title}: ${error instanceof Error ? error.message : String(error)}`);
        }
      }
    } catch (error) {
      result.failed += 1;
      logger.error(`失敗: RSS ${source.id}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  logger.log(`結果: ダウンロード${result.downloaded}件、既存${result.existing}件、失敗${result.failed}件`);
  return result;
}
