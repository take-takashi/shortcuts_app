import { afterEach, beforeEach, describe, expect, mock, spyOn, test } from "bun:test";
import { access, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { executeDownloads, parseArguments, type ScriptRunner } from "../../../download_radiko_and_upload_notion";
import { parseArguments as parsePodcastArguments } from "../src/download";

let directory: string;
beforeEach(async () => {
  directory = await mkdtemp(join(tmpdir(), "audio-orchestrator-test-"));
  spyOn(console, "log").mockImplementation(() => {});
  spyOn(console, "error").mockImplementation(() => {});
});
afterEach(async () => {
  mock.restore();
  await rm(directory, { recursive: true, force: true });
});

function value(args: string[], option: string): string {
  const index = args.indexOf(option);
  if (index < 0) throw new Error(`Missing ${option}`);
  return args[index + 1];
}

function fixtureRunner(settings: {
  radikoStatus?: number;
  podcastStatus?: number;
  notionStatus?: number;
  radikoMissingManifest?: boolean;
  radikoMalformedManifest?: boolean;
  radikoThrow?: boolean;
  empty?: boolean;
} = {}) {
  const calls: { script: string; args: string[]; cwd: string }[] = [];
  const uploaded: { path: string; title?: string }[] = [];
  const manifests: string[] = [];
  const runner: ScriptRunner = async (script, args, cwd) => {
    calls.push({ script, args, cwd });
    if (script.includes("/notion/")) {
      const manifest = JSON.parse(await readFile(value(args, "--manifest"), "utf8"));
      uploaded.push(...manifest.files);
      return settings.notionStatus ?? 0;
    }
    const radiko = script.includes("/radiko2/");
    if (radiko && settings.radikoThrow) throw new Error("spawn failed");
    const manifestPath = value(args, "--manifest-output");
    manifests.push(manifestPath);
    if (!(radiko && settings.radikoMissingManifest)) {
      await writeFile(manifestPath, JSON.stringify(radiko && settings.radikoMalformedManifest ? { version: 99 } : {
        version: 1,
        files: settings.empty ? [] : [{ path: `/audio/${radiko ? "radiko.m4a" : "podcast.mp3"}`, title: radiko ? "Radiko" : "Podcast" }],
      }));
    }
    return radiko ? settings.radikoStatus ?? 0 : settings.podcastStatus ?? 0;
  };
  return { calls, uploaded, manifests, runner };
}

const now = new Date("2026-10-18T15:30:00Z");

describe("既存ショートカットとの互換性", () => {
  test("既存の引数で両方を処理し、同じ確定日・保存先・上書き指定を渡す", async () => {
    const options = parseArguments([
      "-k", "伊集院光|サンドウィッチマン", "--date", "yesterday",
      "--save-directory", directory, "--exclude-stations", "TEST", "--include-future", "--overwrite",
      "--config", "/tmp/config.json", "--title-property", "名前", "--file-property", "音声",
    ]);
    const fixture = fixtureRunner();
    expect(await executeDownloads(options, fixture.runner, now)).toBe(0);
    const downloads = fixture.calls.slice(0, 2);
    expect(downloads.map((call) => value(call.args, "--date"))).toEqual(["20261018", "20261018"]);
    for (const call of downloads) {
      expect(value(call.args, "--save-directory")).toBe(directory);
      expect(call.args).toContain("--overwrite");
      expect(call.args).toContain("--manifest-include-existing");
      expect(call.args.filter((arg) => arg === "--date")).toHaveLength(1);
    }
    expect(downloads[0].args).toContain("--exclude-stations");
    expect(downloads[1].args).not.toContain("--exclude-stations");
    expect(downloads[1].args).not.toContain("--include-future");
    expect(fixture.uploaded.map((entry) => entry.title)).toEqual(["Radiko", "Podcast"]);
    expect(fixture.calls[2].args.slice(0, 7)).toEqual([
      "upload", "--config", "/tmp/config.json", "--title-property", "名前", "--file-property", "音声",
    ]);
    for (const path of fixture.manifests) await expect(access(path)).rejects.toThrow();
  });

  test("日付省略の既存コマンドでも昨日分を両方に渡す", async () => {
    const fixture = fixtureRunner();
    await executeDownloads(parseArguments(["--keywords", "test"]), fixture.runner, now);
    expect(fixture.calls.slice(0, 2).map((call) => value(call.args, "--date"))).toEqual(["20261018", "20261018"]);
  });

  test("従来の環境変数を共通設定として使い、CLI指定を優先する", async () => {
    const originalDate = process.env.RADIKO_DATE;
    const originalDirectory = process.env.RADIKO_SAVE_DIRECTORY;
    try {
      process.env.RADIKO_DATE = "20240229";
      process.env.RADIKO_SAVE_DIRECTORY = directory;
      const fixture = fixtureRunner();
      await executeDownloads(parseArguments(["--keywords", "test"]), fixture.runner, now);
      for (const call of fixture.calls.slice(0, 2)) {
        expect(value(call.args, "--date")).toBe("20240229");
        expect(value(call.args, "--save-directory")).toBe(directory);
      }
      const override = fixtureRunner();
      await executeDownloads(parseArguments(["--keywords", "test", "--date", "today"]), override.runner, now);
      expect(value(override.calls[0].args, "--date")).toBe("20261019");
      process.env.RADIKO_DATE = "";
      const empty = fixtureRunner();
      await executeDownloads(parseArguments(["--keywords", "test"]), empty.runner, now);
      expect(value(empty.calls[0].args, "--date")).toBe("20261018");
      process.env.RADIKO_DATE = "not-a-date";
      const latest = fixtureRunner();
      expect(await executeDownloads(parseArguments(["--podcast-only", "--latest"]), latest.runner, now)).toBe(0);
    } finally {
      if (originalDate === undefined) delete process.env.RADIKO_DATE;
      else process.env.RADIKO_DATE = originalDate;
      if (originalDirectory === undefined) delete process.env.RADIKO_SAVE_DIRECTORY;
      else process.env.RADIKO_SAVE_DIRECTORY = originalDirectory;
    }
  });

  test("指定日と統合ファイル一覧の保存", async () => {
    const output = join(directory, "downloads.json");
    const fixture = fixtureRunner();
    expect(await executeDownloads(parseArguments([
      "--keywords", "test", "--date", "20240229", "--manifest-output", output,
    ]), fixture.runner, now)).toBe(0);
    expect(fixture.calls.slice(0, 2).map((call) => value(call.args, "--date"))).toEqual(["20240229", "20240229"]);
    expect(JSON.parse(await readFile(output, "utf8")).files).toHaveLength(2);
  });
});

describe("失敗の分離", () => {
  test("片方が部分失敗しても取得分は両方アップロードする", async () => {
    for (const settings of [{ radikoStatus: 1 }, { podcastStatus: 1 }]) {
      const fixture = fixtureRunner(settings);
      expect(await executeDownloads(parseArguments(["--keywords", "test"]), fixture.runner, now)).toBe(1);
      expect(fixture.uploaded).toHaveLength(2);
    }
  });
  test("Radikoの一覧なし・不正・起動失敗でもPodcastを続ける", async () => {
    for (const settings of [
      { radikoMissingManifest: true, radikoStatus: 1 },
      { radikoMalformedManifest: true },
      { radikoThrow: true },
    ]) {
      const fixture = fixtureRunner(settings);
      expect(await executeDownloads(parseArguments(["--keywords", "test"]), fixture.runner, now)).toBe(1);
      expect(fixture.uploaded.map((entry) => entry.title)).toEqual(["Podcast"]);
    }
  });
  test("対象0件ではNotionを呼ばない", async () => {
    const fixture = fixtureRunner({ empty: true });
    expect(await executeDownloads(parseArguments(["--keywords", "test"]), fixture.runner, now)).toBe(0);
    expect(fixture.calls).toHaveLength(2);
  });
  test("Notionの失敗は終了コード1", async () => {
    const fixture = fixtureRunner({ notionStatus: 1 });
    expect(await executeDownloads(parseArguments(["--keywords", "test"]), fixture.runner, now)).toBe(1);
  });
});

describe("Podcastのみ・Radikoのみ・初回latest", () => {
  test("PodcastのみならRadikoキーワード不要で最新回を取得できる", async () => {
    const fixture = fixtureRunner();
    expect(await executeDownloads(parseArguments([
      "--podcast-only", "--latest", "--podcast-feeds", "/tmp/feeds.json",
    ]), fixture.runner, now)).toBe(0);
    expect(fixture.calls).toHaveLength(2);
    expect(fixture.calls[0].script).toContain("/podcast/");
    expect(fixture.calls[0].args).toContain("--latest");
    expect(fixture.calls[0].args).not.toContain("--date");
    expect(value(fixture.calls[0].args, "--feeds")).toBe("/tmp/feeds.json");
  });
  test("Radikoのみで従来どおり動作する", async () => {
    const fixture = fixtureRunner();
    await executeDownloads(parseArguments(["--radiko-only", "--keywords", "test"]), fixture.runner, now);
    expect(fixture.calls).toHaveLength(2);
    expect(fixture.uploaded.map((entry) => entry.title)).toEqual(["Radiko"]);
  });
  test("不正な対象日はダウンロードやNotionを呼ばずに拒否する", async () => {
    const fixture = fixtureRunner();
    await expect(executeDownloads(parseArguments(["--keywords", "test", "--date", "20260229"]), fixture.runner, now)).rejects.toThrow();
    expect(fixture.calls).toEqual([]);
  });

  test("不正なフラグの組み合わせや値不足を拒否する", () => {
    for (const args of [
      ["--latest"], ["--radiko-only", "--podcast-only"], ["--date"], ["--unknown"],
      ["--podcast-only", "--latest", "--date", "today"],
    ]) expect(() => parseArguments(args)).toThrow();
    expect(() => parsePodcastArguments(["--date", "today", "--latest"])).toThrow();
    expect(parsePodcastArguments(["--latest"], now).date).toBeUndefined();
    expect(parsePodcastArguments([], now).date).toBe("20261018");
  });
});
