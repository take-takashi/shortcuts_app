import { XMLParser, XMLValidator } from "fast-xml-parser";
import { formatJstDate } from "./date";

export interface FeedSource {
  id: string;
  url: string;
}

export interface PodcastEpisode {
  id: string;
  title: string;
  publishedAt: Date;
  audioUrl: string;
  mediaType: string;
  imageUrl?: string;
}

export interface PodcastFeed {
  title: string;
  author: string;
  imageUrl?: string;
  episodes: PodcastEpisode[];
  warnings: string[];
}

type XmlObject = Record<string, unknown>;

function object(value: unknown): XmlObject {
  return value && typeof value === "object" ? value as XmlObject : {};
}

function text(value: unknown): string {
  if (typeof value === "string") return value.trim();
  return typeof object(value)["#text"] === "string" ? String(object(value)["#text"]).trim() : "";
}

function array(value: unknown): unknown[] {
  return value === undefined ? [] : Array.isArray(value) ? value : [value];
}

function httpUrl(value: unknown, baseUrl: string): string | undefined {
  const string = text(value);
  if (!string) return undefined;
  try {
    const url = new URL(string, baseUrl);
    return ["http:", "https:"].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}

function imageUrl(node: XmlObject, baseUrl: string): string | undefined {
  return httpUrl(object(node["itunes:image"])["@_href"], baseUrl) ??
    httpUrl(object(node.image).url, baseUrl);
}

export function parseFeed(xml: string, baseUrl: string): PodcastFeed {
  // Podcastの取得にDTDは不要。外部エンティティや独自エンティティを受け付けません。
  if (/<!DOCTYPE/i.test(xml) || XMLValidator.validate(xml) !== true) {
    throw new Error("RSSのXML形式が不正です（DTDには対応していません）。");
  }
  const parser = new XMLParser({
    ignoreAttributes: false,
    parseTagValue: false,
    parseAttributeValue: false,
  });
  const root = object(parser.parse(xml));
  const channel = object(object(root.rss).channel);
  const title = text(channel.title);
  if (!title) throw new Error("RSSに番組名（channel/title）がありません。");

  const feed: PodcastFeed = {
    title,
    author: text(channel["itunes:author"]),
    imageUrl: imageUrl(channel, baseUrl),
    episodes: [],
    warnings: [],
  };
  const seen = new Set<string>();
  for (const value of array(channel.item)) {
    const item = object(value);
    const episodeTitle = text(item.title) || text(item["itunes:title"]);
    const enclosure = array(item.enclosure).map(object).find((entry) => {
      const type = text(entry["@_type"]);
      return !type || type.startsWith("audio/");
    });
    const audioUrl = httpUrl(enclosure?.["@_url"], baseUrl);
    const publishedAt = new Date(text(item.pubDate));
    if (!episodeTitle || !audioUrl || !Number.isFinite(publishedAt.getTime())) {
      feed.warnings.push(`スキップ（タイトル・音声URL・公開日時の不足）: ${episodeTitle || "タイトルなし"}`);
      continue;
    }
    const id = text(item.guid) || audioUrl;
    if (seen.has(id)) continue;
    seen.add(id);
    feed.episodes.push({
      id,
      title: episodeTitle,
      publishedAt,
      audioUrl,
      mediaType: text(enclosure?.["@_type"]).split(";", 1)[0].toLowerCase(),
      imageUrl: imageUrl(item, baseUrl),
    });
  }
  return feed;
}

export function selectEpisodes(
  feed: PodcastFeed,
  options: { date?: string; latest?: boolean; now?: Date },
): PodcastEpisode[] {
  const now = options.now ?? new Date();
  const published = feed.episodes
    .filter((episode) => episode.publishedAt.getTime() <= now.getTime())
    .sort((a, b) => b.publishedAt.getTime() - a.publishedAt.getTime());
  if (options.latest) return published.slice(0, 1);
  return published.filter((episode) => formatJstDate(episode.publishedAt) === options.date);
}
