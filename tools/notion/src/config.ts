import { chmod, mkdir, readFile, writeFile } from "fs/promises";
import { homedir } from "os";
import { dirname, isAbsolute, join, resolve } from "path";

export interface NotionConfig {
  token?: string;
  databaseId?: string;
  titleProperty?: string;
  filePropertyName?: string;
}

export interface AppConfig {
  notion?: NotionConfig;
}

export function getDefaultConfigPath(): string {
  const configHome = process.env.XDG_CONFIG_HOME || join(homedir(), ".config");
  return join(configHome, "shortcuts_app", "config.json");
}

export function resolveConfigPath(configPath?: string): string {
  const value = configPath || getDefaultConfigPath();
  if (value === "~") return homedir();
  if (value.startsWith("~/")) return join(homedir(), value.slice(2));
  return isAbsolute(value) ? value : resolve(process.cwd(), value);
}

export async function readAppConfig(configPath: string): Promise<AppConfig | undefined> {
  try {
    const content = await readFile(configPath, "utf8");
    const parsed: unknown = JSON.parse(content);
    return validateAppConfig(parsed, configPath);
  } catch (error) {
    if (isFileNotFound(error)) return undefined;
    throw error;
  }
}

export async function initializeConfig(configPath: string, force = false): Promise<void> {
  await mkdir(dirname(configPath), { recursive: true, mode: 0o700 });
  await chmod(dirname(configPath), 0o700);
  if (!force) {
    try {
      await readFile(configPath);
      throw new Error(`設定ファイルは既に存在します: ${configPath}（上書きする場合は --force）`);
    } catch (error) {
      if (!isFileNotFound(error)) throw error;
    }
  }

  const template: AppConfig = {
    notion: {
      token: "",
      databaseId: "",
      titleProperty: "Name"
    },
  };
  await writeFile(configPath, `${JSON.stringify(template, null, 2)}\n`, {
    encoding: "utf8",
    flag: "w",
  });
  await chmod(configPath, 0o600);
}

function validateAppConfig(value: unknown, configPath: string): AppConfig {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`設定ファイルの形式が不正です: ${configPath}`);
  }

  const root = value as Record<string, unknown>;
  if (root.notion === undefined) return {};
  if (!root.notion || typeof root.notion !== "object" || Array.isArray(root.notion)) {
    throw new Error(`設定ファイルのnotionセクションが不正です: ${configPath}`);
  }

  const notion = root.notion as Record<string, unknown>;
  return {
    notion: {
      token: readOptionalString(notion.token, "notion.token", configPath),
      databaseId: readOptionalString(notion.databaseId, "notion.databaseId", configPath),
      titleProperty: readOptionalString(
        notion.titleProperty,
        "notion.titleProperty",
        configPath,
      ),
      filePropertyName: readOptionalString(
        notion.filePropertyName,
        "notion.filePropertyName",
        configPath,
      ),
    },
  };
}

function readOptionalString(
  value: unknown,
  property: string,
  configPath: string,
): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "string") {
    throw new Error(`${property}は文字列で指定してください: ${configPath}`);
  }
  return value;
}

function isFileNotFound(error: unknown): boolean {
  return Boolean(
    error &&
      typeof error === "object" &&
      "code" in error &&
      (error as { code?: string }).code === "ENOENT",
  );
}
