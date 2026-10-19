import type { DownloadLogger } from "../src/metadata";

export const silentLogger: DownloadLogger = { log() {}, warn() {}, error() {} };
export const audioBytes = Buffer.concat([Buffer.from([0xff, 0xfb, 0x90, 0x64]), Buffer.alloc(413)]);
export const coverBytes = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=",
  "base64",
);

export interface EpisodeFixture {
  id?: string;
  title?: string;
  date?: string;
  audio?: string;
  image?: string;
  mediaType?: string;
}

function escape(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;");
}

export function rss(episodes: EpisodeFixture[], options: { title?: string; image?: string } = {}): string {
  return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>
<title>${escape(options.title ?? "テスト番組")}</title><itunes:author>出演者</itunes:author>
${options.image ? `<itunes:image href="${escape(options.image)}"/>` : ""}
${episodes.map((episode) => `<item>
<title>${escape(episode.title ?? "エピソード")}</title>
${episode.id ? `<guid isPermaLink="false">${escape(episode.id)}</guid>` : ""}
<pubDate>${escape(episode.date ?? "Sun, 18 Oct 2026 09:00:00 +0000")}</pubDate>
<enclosure url="${escape(episode.audio ?? "https://example.test/audio.mp3")}" length="0" type="${escape(episode.mediaType ?? "audio/mpeg")}"/>
${episode.image ? `<itunes:image href="${escape(episode.image)}"/>` : ""}
</item>`).join("\n")}
</channel></rss>`;
}

export function mockFetch(
  routes: Record<string, () => Response | Promise<Response>>,
  requests: string[] = [],
): typeof fetch {
  return (async (input: string | URL | Request) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    requests.push(url);
    if (!routes[url]) throw new Error(`Unexpected fetch: ${url}`);
    return routes[url]();
  }) as typeof fetch;
}

export function audioResponse(bytes: Buffer = audioBytes): Response {
  return new Response(new Uint8Array(bytes), { headers: { "Content-Type": "audio/mpeg" } });
}
