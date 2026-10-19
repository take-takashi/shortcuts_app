import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import NodeID3 from "node-id3";
import { downloadPodcasts, getEpisodeOutputPath, readFeedSources, type DownloadOptions } from "../src/downloader";
import { parseFeed } from "../src/feed";
import { audioBytes, audioResponse, coverBytes, mockFetch, rss, silentLogger } from "./fixtures";

const source = { id: "test", url: "https://example.test/feed.rss" };
let directory: string;
let options: DownloadOptions;
beforeEach(async () => {
  directory = await mkdtemp(join(tmpdir(), "podcast-test-"));
  options = {
    feeds: [source], saveDirectory: directory, date: "20261018",
    now: new Date("2026-10-20T00:00:00Z"), manifestIncludeExisting: true,
  };
});
afterEach(async () => { await rm(directory, { recursive: true, force: true }); });

describe("ダウンロードとメタデータ", () => {
  test("埋め込み済みMP3はバイト単位で維持し、NotionタイトルはRSSから作る", async () => {
    const original = NodeID3.write({
      title: "元のタイトル", album: "元のアルバム",
      image: { mime: "image/png", type: { id: 3 }, description: "Original", imageBuffer: coverBytes },
    }, audioBytes);
    const requests: string[] = [];
    const fetcher = mockFetch({
      [source.url]: () => new Response(rss([{ id: "one" }], { image: "https://example.test/cover.png" })),
      "https://example.test/audio.mp3": () => audioResponse(original),
    }, requests);
    const result = await downloadPodcasts(options, { fetcher, logger: silentLogger });
    expect(result.downloaded).toBe(1);
    expect(result.failed).toBe(0);
    expect(await readFile(result.files[0].path)).toEqual(Buffer.from(original));
    expect(result.files[0].title).toBe("エピソード / テスト番組 / 2026-10-18 18:00:00");
    expect(result.files[0].metadata.publishedAt).toBe("2026-10-18T09:00:00.000Z");
    expect(requests).toEqual([source.url, "https://example.test/audio.mp3"]);
  });

  test("不足タグだけ補完し、回別画像を優先する。音声データは変えない", async () => {
    const original = NodeID3.write({ title: "配信タイトル", comment: { language: "eng", text: "keep me" } }, audioBytes);
    const requests: string[] = [];
    const fetcher = mockFetch({
      [source.url]: () => new Response(rss([{ id: "one", image: "/episode.png" }], { image: "/show.png" })),
      "https://example.test/audio.mp3": () => audioResponse(original),
      "https://example.test/episode.png": () => new Response(new Uint8Array(coverBytes)),
    }, requests);
    const result = await downloadPodcasts(options, { fetcher, logger: silentLogger });
    expect(result.failed).toBe(0);
    const output = await readFile(result.files[0].path);
    const tags = NodeID3.read(output);
    expect(tags.title).toBe("配信タイトル");
    expect(tags.album).toBe("テスト番組");
    expect(tags.artist).toBe("出演者");
    expect(tags.comment?.text).toBe("keep me");
    expect(typeof tags.image === "object" && tags.image.imageBuffer).toEqual(coverBytes);
    const tagSize = output.subarray(6, 10).reduce((size, byte) => (size << 7) | byte, 0);
    expect(output.subarray(10 + tagSize)).toEqual(audioBytes);
    expect(requests.at(-1)).toBe("https://example.test/episode.png");
    expect(requests).not.toContain("https://example.test/show.png");
  });

  test("回別画像の失敗時は番組画像にフォールバックする", async () => {
    const fetcher = mockFetch({
      [source.url]: () => new Response(rss([{ image: "/missing.png" }], { image: "/show.png" })),
      "https://example.test/audio.mp3": () => audioResponse(),
      "https://example.test/missing.png": () => new Response(null, { status: 404 }),
      "https://example.test/show.png": () => new Response(new Uint8Array(coverBytes)),
    });
    const result = await downloadPodcasts(options, { fetcher, logger: silentLogger });
    expect(result.failed).toBe(0);
    const tags = NodeID3.read(await readFile(result.files[0].path));
    expect(tags.title).toBe("エピソード");
    expect(typeof tags.image === "object" && tags.image.imageBuffer).toEqual(coverBytes);
  });

  test("画像を取得できなくても音声は保存する", async () => {
    const fetcher = mockFetch({
      [source.url]: () => new Response(rss([{}], { image: "/bad.png" })),
      "https://example.test/audio.mp3": () => audioResponse(),
      "https://example.test/bad.png": () => new Response("not an image"),
    });
    const result = await downloadPodcasts(options, { fetcher, logger: silentLogger });
    expect(result.downloaded).toBe(1);
    expect(NodeID3.read(await readFile(result.files[0].path)).image).toBeUndefined();
  });

  test("既存音声は再DLせず一覧に含め、--overwriteでは再DLする", async () => {
    let downloads = 0;
    const fetcher = mockFetch({
      [source.url]: () => new Response(rss([{ id: "one" }])),
      "https://example.test/audio.mp3": () => { downloads += 1; return audioResponse(); },
    });
    const first = await downloadPodcasts(options, { fetcher, logger: silentLogger });
    const second = await downloadPodcasts(options, { fetcher, logger: silentLogger });
    expect(downloads).toBe(1);
    expect(second.existing).toBe(1);
    expect(second.files).toEqual(first.files);
    const third = await downloadPodcasts({ ...options, overwrite: true }, { fetcher, logger: silentLogger });
    expect(downloads).toBe(2);
    expect(third.downloaded).toBe(1);
    expect((await downloadPodcasts({ ...options, manifestIncludeExisting: false }, { fetcher, logger: silentLogger })).files).toEqual([]);
  });

  test("失敗した上書きで既存音声を壊さず、途中ファイルも残さない", async () => {
    const xml = rss([{ id: "one" }]);
    const feed = parseFeed(xml, source.url);
    const path = getEpisodeOutputPath(source, feed, feed.episodes[0], directory);
    await writeFile(path, "previous audio");
    const fetcher = mockFetch({
      [source.url]: () => new Response(xml),
      "https://example.test/audio.mp3": () => new Response(new ReadableStream({
        start(controller) { controller.enqueue(audioBytes); controller.error(new Error("connection lost")); },
      })),
    });
    const result = await downloadPodcasts({ ...options, overwrite: true }, { fetcher, logger: silentLogger });
    expect(result.failed).toBe(1);
    expect(result.files).toEqual([]);
    expect(await readFile(path, "utf8")).toBe("previous audio");
    expect(await readdir(directory)).toEqual([basename(path)]);
  });

  test("RSSや個別音声の失敗があっても、ほかの番組・回は続行する", async () => {
    const fetcher = mockFetch({
      "https://example.test/bad.rss": () => new Response(null, { status: 500 }),
      [source.url]: () => new Response(rss([
        { id: "bad", audio: "/bad.mp3" }, { id: "good", audio: "/good.mp3" },
      ])),
      "https://example.test/bad.mp3": () => new Response(null, { status: 404 }),
      "https://example.test/good.mp3": () => audioResponse(),
    });
    const result = await downloadPodcasts({
      ...options, feeds: [{ id: "bad", url: "https://example.test/bad.rss" }, source],
    }, { fetcher, logger: silentLogger });
    expect(result.failed).toBe(2);
    expect(result.downloaded).toBe(1);
    expect(result.files[0].metadata.episodeId).toBe("good");
  });

  test("音声でない応答・空ファイル・未対応形式は完了扱いにしない", async () => {
    for (const [type, response] of [
      ["audio/mpeg", () => new Response("<html>error</html>", { headers: { "Content-Type": "text/html" } })],
      ["audio/mpeg", () => audioResponse(Buffer.alloc(0))],
      ["audio/mp4", () => audioResponse()],
    ] as const) {
      const fetcher = mockFetch({
        [source.url]: () => new Response(rss([{ mediaType: type }])),
        "https://example.test/audio.mp3": response,
      });
      const result = await downloadPodcasts(options, { fetcher, logger: silentLogger });
      expect(result.failed).toBe(1);
      expect(result.files).toEqual([]);
      expect(await readdir(directory)).toEqual([]);
    }
  });

  test("初回latestは各番組1回だけ、対象日なしは0件", async () => {
    const fetcher = mockFetch({
      [source.url]: () => new Response(rss([
        { id: "older", date: "Sat, 17 Oct 2026 09:00:00 +0000" }, { id: "latest" },
      ])),
      "https://example.test/audio.mp3": () => audioResponse(),
    });
    expect((await downloadPodcasts({ ...options, date: "20200101" }, { fetcher, logger: silentLogger })).files).toEqual([]);
    const result = await downloadPodcasts({ ...options, date: undefined, latest: true }, { fetcher, logger: silentLogger });
    expect(result.files.map((entry) => entry.metadata.episodeId)).toEqual(["latest"]);
  });
});

test("ファイル名は長い日本語でも255バイト以内・安全・回ごとに一意", () => {
  const feed = parseFeed(rss([{ id: "one", title: '長い題名/\\:*?"<>|'.repeat(30) }], { title: "長い番組名".repeat(30) }), source.url);
  const path = getEpisodeOutputPath(source, feed, feed.episodes[0], directory);
  expect(Buffer.byteLength(basename(path))).toBeLessThanOrEqual(255);
  expect(basename(path)).not.toMatch(/[\\/:*?"<>|]/);
  expect(getEpisodeOutputPath(source, feed, { ...feed.episodes[0], id: "two" }, directory)).not.toBe(path);
});

test("番組設定を検証する", async () => {
  const path = join(directory, "feeds.json");
  await writeFile(path, JSON.stringify([source]));
  expect(await readFeedSources(path)).toEqual([source]);
  for (const value of [[], null, [{}], [source, source], [{ id: "x", url: "file:///etc/passwd" }]]) {
    await writeFile(path, JSON.stringify(value));
    await expect(readFeedSources(path)).rejects.toThrow();
  }
});
