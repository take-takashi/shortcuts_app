import { appendFileSync, mkdirSync, renameSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { DownloadLogger } from "./metadata";

function log(level: "INFO" | "WARN" | "ERROR", message: string): void {
  if (level === "ERROR") console.error(message);
  else if (level === "WARN") console.warn(message);
  else console.log(message);
  try {
    const directory = join(homedir(), "Library", "Logs", "shortcuts_app");
    const path = join(directory, "podcast.log");
    mkdirSync(directory, { recursive: true });
    try {
      if (statSync(path).size >= 5 * 1024 * 1024) renameSync(path, `${path}.1`);
    } catch (error) {
      if (!(error && typeof error === "object" && "code" in error && error.code === "ENOENT")) throw error;
    }
    appendFileSync(path, `[${new Date().toISOString()}] [${level}] ${message}\n`, "utf8");
  } catch (error) {
    console.error(`Podcastのログを書き込めませんでした: ${String(error)}`);
  }
}

export const logger: DownloadLogger = {
  log: (message) => log("INFO", message),
  warn: (message) => log("WARN", message),
  error: (message) => log("ERROR", message),
};
