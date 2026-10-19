import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import NodeID3 from "node-id3";
import { audioBytes, audioResponse, coverBytes, rss } from "./fixtures";

const script = fileURLToPath(new URL("../src/download.ts", import.meta.url));
const rootScript = fileURLToPath(new URL("../../../download_radiko_and_upload_notion.ts", import.meta.url));
let directory: string;
beforeEach(async () => { directory = await mkdtemp(join(tmpdir(), "podcast-cli-test-")); });
afterEach(async () => { await rm(directory, { recursive: true, force: true }); });

async function runScript(path: string, args: string[]) {
  const process = Bun.spawn([globalThis.process.execPath, path, ...args], {
    cwd: directory,
    env: { ...globalThis.process.env, HOME: directory, TZ: "America/Los_Angeles" },
    stdout: "pipe", stderr: "pipe",
  });
  const [status, stdout, stderr] = await Promise.all([
    process.exited, new Response(process.stdout).text(), new Response(process.stderr).text(),
  ]);
  return { status, stdout, stderr };
}

test("ショートカットと同じ既存の入口は、プロジェクト外から起動できる", async () => {
  const result = await runScript(rootScript, ["--help"]);
  expect(result.status).toBe(0);
  expect(result.stdout).toContain("--podcast-only");
  expect(result.stdout).toContain("--date");
});

test("CLIを別cwd・別TZから起動し、RSS取得・MP3保存・一覧出力・再実行まで確認する", async () => {
  let audioDownloads = 0;
  const taggedAudio = NodeID3.write({
    title: "元のタイトル", album: "元の番組",
    image: { mime: "image/png", type: { id: 3 }, description: "Cover", imageBuffer: coverBytes },
  }, audioBytes);
  const server = Bun.serve({
    hostname: "127.0.0.1", port: 0,
    fetch(request) {
      const url = new URL(request.url);
      if (url.pathname === "/feed.rss") return new Response(rss([
        { id: "before", date: "Sat, 01 Jan 2000 14:59:59 -0000", audio: "/before.mp3" },
        { id: "target", title: "対象回", date: "Sat, 01 Jan 2000 15:00:00 -0000", audio: "/audio.mp3" },
      ]));
      if (url.pathname === "/audio.mp3") { audioDownloads += 1; return audioResponse(taggedAudio); }
      return new Response(null, { status: 404 });
    },
  });
  try {
    await writeFile(join(directory, "feeds.json"), JSON.stringify([{ id: "fixture", url: `${server.url}feed.rss` }]));
    const args = [
      "--feeds", "./feeds.json", "--date", "20000102", "--save-directory", "./downloads",
      "--manifest-output", "./manifest.json", "--manifest-include-existing",
    ];
    const first = await runScript(script, args);
    expect(first.stderr).toBe("");
    expect(first.status).toBe(0);
    const manifest = JSON.parse(await readFile(join(directory, "manifest.json"), "utf8"));
    expect(manifest.version).toBe(1);
    expect(manifest.files).toHaveLength(1);
    expect(manifest.files[0].title).toBe("対象回 / テスト番組 / 2000-01-02 00:00:00");
    expect(await realpath(dirname(manifest.files[0].path))).toBe(await realpath(join(directory, "downloads")));
    expect(await readFile(manifest.files[0].path)).toEqual(Buffer.from(taggedAudio));
    const second = await runScript(script, args);
    expect(second.status).toBe(0);
    expect(second.stdout).toContain("既存1件");
    expect(audioDownloads).toBe(1);
    expect(await readFile(join(directory, "Library", "Logs", "shortcuts_app", "podcast.log"), "utf8")).toContain("20000102");
  } finally {
    server.stop(true);
  }
});
