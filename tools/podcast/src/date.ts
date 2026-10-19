const JST_OFFSET_MS = 9 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

/** ホストのタイムゾーンに依存せず、日本時間で表示します。 */
export function formatJstDateTime(date: Date): string {
  return new Date(date.getTime() + JST_OFFSET_MS).toISOString().slice(0, 19).replace("T", " ");
}

export function formatJstDate(date: Date): string {
  return formatJstDateTime(date).slice(0, 10).replaceAll("-", "");
}

export function resolveDate(value = "yesterday", now = new Date()): string {
  if (value === "today") return formatJstDate(now);
  if (value === "yesterday") return formatJstDate(new Date(now.getTime() - DAY_MS));
  if (!/^\d{8}$/.test(value)) {
    throw new Error(`日付の形式が不正です: ${value}（today、yesterday、またはYYYYMMDDを指定してください）`);
  }
  const date = new Date(`${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}T00:00:00+09:00`);
  if (!Number.isFinite(date.getTime()) || formatJstDate(date) !== value) {
    throw new Error(`存在しない日付です: ${value}`);
  }
  return value;
}
