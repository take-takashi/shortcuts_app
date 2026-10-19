import NodeID3 from "node-id3";
import type { PodcastEpisode, PodcastFeed } from "./feed";

export interface DownloadLogger {
  log(message: string): void;
  warn(message: string): void;
  error(message: string): void;
}

function coverMimeType(data: Buffer): string | undefined {
  if (data[0] === 0xff && data[1] === 0xd8 && data[2] === 0xff) return "image/jpeg";
  if (data.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) return "image/png";
  return undefined;
}

/** 既存のタイトル・番組名・画像を維持し、不足しているものだけを補完します。 */
export async function supplementMetadata(
  filePath: string,
  feed: PodcastFeed,
  episode: PodcastEpisode,
  fetcher: typeof fetch = fetch,
  logger: DownloadLogger = console,
): Promise<void> {
  const tags = await NodeID3.Promise.read(filePath);
  const patch: NodeID3.Tags = {};
  if (!tags.title?.trim()) patch.title = episode.title;
  if (!tags.album?.trim()) patch.album = feed.title;

  const image = tags.image;
  if (!image || typeof image === "string" || image.imageBuffer.length === 0) {
    const imageUrls = [...new Set([episode.imageUrl, feed.imageUrl].filter((url): url is string => Boolean(url)))];
    for (const url of imageUrls) {
      try {
        const response = await fetcher(url, {
          headers: { Accept: "image/jpeg,image/png", "User-Agent": "shortcuts_app/podcast" },
          signal: AbortSignal.timeout(30_000),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = Buffer.from(await response.arrayBuffer());
        const mime = coverMimeType(data);
        if (!mime) throw new Error("JPEG/PNG以外の画像です。");
        patch.image = {
          mime,
          type: { id: 3 },
          description: "Cover",
          imageBuffer: data,
        };
        break;
      } catch (error) {
        logger.warn(`カバー画像を取得できませんでした: ${url}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
  }

  // 情報が揃っているMP3は書き換えません。音声の再エンコードは行いません。
  if (Object.keys(patch).length > 0) {
    if (!tags.artist?.trim() && feed.author) patch.artist = feed.author;
    await NodeID3.Promise.update(patch, filePath);
  }
}
