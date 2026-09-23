import * as fs from "fs";
import * as path from "path";
import { homedir } from "os";

enum LogLevel {
  INFO = "INFO",
  WARN = "WARN",
  ERROR = "ERROR",
  DEBUG = "DEBUG",
}

const logDirectory = path.join(homedir(), "Library", "Logs", "radiko2");
const logFilePath = path.join(logDirectory, "radiko2.log");
const maxLogFileSizeBytes = 5 * 1024 * 1024;
const maxLogBackups = 5;

function rotateLogFileBySize(): void {
  if (!fs.existsSync(logFilePath)) return;

  try {
    if (fs.statSync(logFilePath).size < maxLogFileSizeBytes) return;

    const oldestBackupPath = `${logFilePath}.${maxLogBackups}`;
    if (fs.existsSync(oldestBackupPath)) fs.unlinkSync(oldestBackupPath);

    for (let generation = maxLogBackups - 1; generation >= 1; generation -= 1) {
      const sourcePath = `${logFilePath}.${generation}`;
      const destinationPath = `${logFilePath}.${generation + 1}`;
      if (fs.existsSync(sourcePath)) fs.renameSync(sourcePath, destinationPath);
    }

    fs.renameSync(logFilePath, `${logFilePath}.1`);
  } catch (error) {
    console.error("ログファイルのローテーションに失敗しました:", error);
  }
}

function log(level: LogLevel, message: string, ...optionalParams: unknown[]): void {
  try {
    fs.mkdirSync(logDirectory, { recursive: true });
    rotateLogFileBySize();

    const timestamp = new Date().toISOString();
    const params = optionalParams.length > 0
      ? ` ${optionalParams.map((param) => JSON.stringify(param)).join(" ")}`
      : "";
    fs.appendFileSync(logFilePath, `[${timestamp}] [${level}] ${message}${params}\n`, "utf8");
  } catch (error) {
    console.error("ログの書き込みに失敗しました:", error);
  }
}

export const logger = {
  info: (message: string, ...optionalParams: unknown[]) => log(LogLevel.INFO, message, ...optionalParams),
  warn: (message: string, ...optionalParams: unknown[]) => log(LogLevel.WARN, message, ...optionalParams),
  error: (message: string, ...optionalParams: unknown[]) => log(LogLevel.ERROR, message, ...optionalParams),
  debug: (message: string, ...optionalParams: unknown[]) => log(LogLevel.DEBUG, message, ...optionalParams),
  getLogFilePath: () => logFilePath,
};
