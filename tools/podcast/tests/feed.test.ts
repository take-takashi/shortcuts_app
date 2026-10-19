import { describe, expect, test } from "bun:test";
import { formatJstDate, formatJstDateTime, resolveDate } from "../src/date";
import { parseFeed, selectEpisodes } from "../src/feed";
import { rss } from "./fixtures";

const feedUrl = "https://example.test/feed.rss";

describe("日本時間の対象日", () => {
  test("UTCから日付が変わる境界を扱う", () => {
    expect(formatJstDate(new Date("2026-10-18T14:59:59Z"))).toBe("20261018");
    expect(formatJstDate(new Date("2026-10-18T15:00:00Z"))).toBe("20261019");
    expect(formatJstDateTime(new Date("2026-10-18T15:00:00Z"))).toBe("2026-10-19 00:00:00");
  });
  test("today/yesterdayの年・月・うるう年の境界", () => {
    expect(resolveDate("today", new Date("2025-12-31T15:00:00Z"))).toBe("20260101");
    expect(resolveDate("yesterday", new Date("2025-12-31T15:00:00Z"))).toBe("20251231");
    expect(resolveDate(undefined, new Date("2024-03-01T00:00:00+09:00"))).toBe("20240229");
    expect(resolveDate("20240229")).toBe("20240229");
  });
  test("不正な日付は実行前に拒否する", () => {
    for (const value of ["20260229", "20261301", "20260431", "20260100", "2026-10-18", ""]) {
      expect(() => resolveDate(value)).toThrow();
    }
  });
  test("ホストのタイムゾーンに依存しない", () => {
    const original = process.env.TZ;
    try {
      for (const zone of ["UTC", "America/Los_Angeles", "Asia/Tokyo"]) {
        process.env.TZ = zone;
        expect(resolveDate("today", new Date("2026-10-18T16:00:00Z"))).toBe("20261019");
        expect(resolveDate("yesterday", new Date("2026-10-18T16:00:00Z"))).toBe("20261018");
      }
    } finally {
      if (original === undefined) delete process.env.TZ;
      else process.env.TZ = original;
    }
  });
});

describe("RSS", () => {
  test("単一item、文字参照、先頭ゼロのGUID、画像を保持する", () => {
    const feed = parseFeed(rss([{ id: "00123", title: "#1 A & B", image: "/episode.png" }], {
      title: "番組 & 名前", image: "/show.png",
    }), feedUrl);
    expect(feed.title).toBe("番組 & 名前");
    expect(feed.author).toBe("出演者");
    expect(feed.imageUrl).toBe("https://example.test/show.png");
    expect(feed.episodes).toHaveLength(1);
    expect(feed.episodes[0].id).toBe("00123");
    expect(feed.episodes[0].title).toBe("#1 A & B");
    expect(feed.episodes[0].imageUrl).toBe("https://example.test/episode.png");
  });
  test("GUIDのない回は音声URLで識別し、重複GUIDをまとめる", () => {
    const feed = parseFeed(rss([{ id: "one" }, { id: "one" }, {}]), feedUrl);
    expect(feed.episodes).toHaveLength(2);
    expect(feed.episodes[1].id).toBe("https://example.test/audio.mp3");
  });
  test("RSS順ではなく公開日時で最新回を選び、公開予定回を除く", () => {
    const feed = parseFeed(rss([
      { id: "old", date: "Sat, 17 Oct 2026 09:00:00 +0000" },
      { id: "future", date: "Wed, 21 Oct 2026 09:00:00 +0000" },
      { id: "new", date: "Sun, 18 Oct 2026 09:00:00 +0000" },
    ]), feedUrl);
    const episodes = selectEpisodes(feed, { latest: true, now: new Date("2026-10-20T00:00:00Z") });
    expect(episodes.map((episode) => episode.id)).toEqual(["new"]);
  });
  test("-0000はUTCとして扱い、日本時間の同じ日の回をすべて選ぶ", () => {
    const feed = parseFeed(rss([
      { id: "before", date: "Sun, 18 Oct 2026 14:59:59 -0000" },
      { id: "start", date: "Sun, 18 Oct 2026 15:00:00 -0000" },
      { id: "end", date: "Mon, 19 Oct 2026 14:59:59 +0000" },
      { id: "after", date: "Mon, 19 Oct 2026 15:00:00 +0000" },
    ]), feedUrl);
    expect(selectEpisodes(feed, { date: "20261019", now: new Date("2026-10-21T00:00:00Z") })
      .map((episode) => episode.id)).toEqual(["end", "start"]);
  });
  test("空の番組と対象日なしは正常な0件", () => {
    expect(parseFeed(rss([]), feedUrl).episodes).toEqual([]);
    expect(selectEpisodes(parseFeed(rss([{}]), feedUrl), { date: "20200101" })).toEqual([]);
  });
  test("不正なitemは警告し、正常なitemは残す", () => {
    const feed = parseFeed(rss([{ id: "bad", date: "not-a-date" }, { id: "good" }]), feedUrl);
    expect(feed.warnings).toHaveLength(1);
    expect(feed.episodes.map((episode) => episode.id)).toEqual(["good"]);
  });
  test("XML/番組名の不足とDTDを拒否する", () => {
    for (const value of ["<rss>", "<rss><channel/></rss>", '<!DOCTYPE rss SYSTEM "file:///etc/passwd"><rss/>']) {
      expect(() => parseFeed(value, feedUrl)).toThrow();
    }
  });
});
