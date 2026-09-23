import { homedir } from "os";
import { join } from "path";

export function formatDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}${month}${day}`;
}

export function resolveDate(value?: string): string {
  if (!value || value === "yesterday") {
    const date = new Date();
    date.setDate(date.getDate() - 1);
    return formatDate(date);
  }

  if (value === "today") return formatDate(new Date());

  if (!/^\d{8}$/.test(value)) {
    throw new Error(`日付の形式が不正です: ${value}（today、yesterday、またはYYYYMMDDを指定してください）`);
  }

  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
    throw new Error(`存在しない日付です: ${value}`);
  }
  return value;
}

export function getSearchKeywords(query: string): string[] {
  return query
    .split("|")
    .map((keyword) => keyword.trim().toLocaleLowerCase())
    .filter((keyword) => keyword.length > 0);
}

export function matchesSearch(program: { title?: string; pfm?: string }, keywords: string[]): boolean {
  if (keywords.length === 0) return true;

  const title = (program.title ?? "").toLocaleLowerCase();
  const personality = (program.pfm ?? "").toLocaleLowerCase();
  return keywords.some((keyword) => title.includes(keyword) || personality.includes(keyword));
}

export function expandHomeDirectory(directory: string): string {
  if (directory === "~") return homedir();
  if (directory.startsWith("~/")) return join(homedir(), directory.slice(2));
  return directory;
}
