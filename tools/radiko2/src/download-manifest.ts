import { mkdir, writeFile } from "fs/promises";
import { dirname, resolve } from "path";
import type { RadikoProgram } from "./radiko-client";

export interface DownloadManifestEntry {
  path: string;
  title: string;
  metadata: {
    source: "radiko";
    programId: string;
    stationId: string;
    stationName: string;
    startTime: string;
    endTime: string;
    personality: string;
  };
}

export interface DownloadManifest {
  version: 1;
  generatedAt: string;
  files: DownloadManifestEntry[];
}

export function createDownloadManifestEntry(
  program: RadikoProgram,
  filePath: string,
): DownloadManifestEntry {
  return {
    path: resolve(filePath),
    title: makeEpisodeTitle(program),
    metadata: {
      source: "radiko",
      programId: program.id,
      stationId: program.stationId,
      stationName: program.stationName,
      startTime: program.ft,
      endTime: program.to,
      personality: program.pfm,
    },
  };
}

export async function writeDownloadManifest(
  manifestPath: string,
  entries: readonly DownloadManifestEntry[],
): Promise<void> {
  await mkdir(dirname(manifestPath), { recursive: true });
  const manifest: DownloadManifest = {
    version: 1,
    generatedAt: new Date().toISOString(),
    files: [...entries],
  };
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
}

function makeEpisodeTitle(program: RadikoProgram): string {
  const startTime = program.ft.replace(
    /^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})$/,
    "$1-$2-$3 $4:$5:$6",
  );
  return `${program.title} / ${program.stationName} / ${startTime} (${program.stationId})`;
}
