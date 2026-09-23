import { writeFile, readFile, stat, mkdir, rm } from "fs/promises";
import { join } from "path";
import { randomBytes } from "crypto";
import { XMLParser } from "fast-xml-parser";
import { tmpdir } from "os";
import { logger } from "./logger";
import { writeM4aFromAdtsFiles, type M4aCover, type M4aMetadata } from "./m4a-writer";

/**
 * 放送局情報を表すインターフェース。
 */
export interface Station {
  /** 放送局ID (例: "TBS") */
  id: string;
  /** 放送局名 (例: "TBSラジオ") */
  name: string;
}

/**
 * Radikoの番組情報を表すインターフェース。
 */
export interface RadikoProgram {
  /** 番組ID */
  id: string;
  /** 番組名 */
  title: string;
  /** 開始時間 (形式: YYYYMMDDHHmmss) */
  ft: string;
  /** 終了時間 (形式: YYYYMMDDHHmmss) */
  to: string;
  /** 番組の画像URL */
  img: string;
  /** パーソナリティ名 */
  pfm: string;
  /** 放送局ID */
  stationId: string;
  /** 放送局名 */
  stationName: string;
}

/**
 * RadikoのAPIと通信し、番組情報の取得、録音などを行うクライアントクラス。
 */
export class RadikoClient {
  private static readonly SEEK_SEC = 300;

  /** Radiko認証で使用する固定キー */
  private static readonly AUTH_KEY = "bcd151073c03b352e1ef2fd66c32209da9ca0afa";
  /** 認証後に取得する認証トークン */
  private authToken: string | null = null;
  /** 認証後に取得するエリアコード */
  private areaCode: string | null = null;
  /** 番組表XMLのキャッシュを保存するディレクトリ */
  private cacheDir: string;

  private static asText(value: unknown): string {
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    if (Array.isArray(value)) {
      return value
        .map((item) => RadikoClient.asText(item))
        .filter(Boolean)
        .join(" ");
    }
    return "";
  }

  private static detectCoverMimeType(
    data: Uint8Array,
    contentType: string | null,
    imageUrl: string,
  ): M4aCover["mimeType"] | undefined {
    if (data.length >= 3 && data[0] === 0xff && data[1] === 0xd8 && data[2] === 0xff) {
      return "image/jpeg";
    }
    if (
      data.length >= 8 &&
      data[0] === 0x89 &&
      data[1] === 0x50 &&
      data[2] === 0x4e &&
      data[3] === 0x47 &&
      data[4] === 0x0d &&
      data[5] === 0x0a &&
      data[6] === 0x1a &&
      data[7] === 0x0a
    ) {
      return "image/png";
    }

    const normalizedContentType = contentType?.split(";", 1)[0].trim().toLowerCase();
    if (normalizedContentType === "image/jpeg" || normalizedContentType === "image/jpg") {
      return "image/jpeg";
    }
    if (normalizedContentType === "image/png") return "image/png";

    try {
      const extension = new URL(imageUrl).pathname.toLowerCase().split(".").pop();
      if (extension === "jpg" || extension === "jpeg") return "image/jpeg";
      if (extension === "png") return "image/png";
    } catch {
      // URLとして解釈できない場合はカバー画像なしで続行します。
    }

    return undefined;
  }

  /**
   * RadikoClientの新しいインスタンスを作成します。
   */
  constructor() {
    this.cacheDir = join(tmpdir(), "radiko-cache");
    // キャッシュディレクトリが存在しない場合は作成する
    mkdir(this.cacheDir, { recursive: true });
  }

  // --- 認証関連 ---

  /**
   * Radikoの認証処理を実行します。
   * 認証トークンとエリアコードを取得し、インスタンス変数に格納します。
   * @returns 認証トークンとエリアコードを含むオブジェクト。
   */
  public async authenticate(): Promise<{ authToken: string; areaCode: string }> {
    // 認証処理1を実行
    const auth1Response = await this.authenticate1();
    // レスポンスから認証トークンを取得
    const authToken = this.getAuthTokenFromAuthResponse(auth1Response);
    // レスポンスから部分キーを取得
    const partialKey = this.getPartialKeyFromAuthResponse(auth1Response);
    // 認証処理2を実行
    const areaCode = await this.authenticate2(authToken, partialKey);

    // 取得したトークンとエリアコードをインスタンス変数に保存
    this.authToken = authToken;
    this.areaCode = areaCode;

    return { authToken, areaCode };
  }

  /**
   * Radiko認証のステップ1を実行します。
   * @returns `fetch` APIのレスポンスオブジェクト。
   * @throws 認証に失敗した場合にエラーをスローします。
   */
  private async authenticate1(): Promise<Response> {
    const url = "https://radiko.jp/v2/api/auth1";
    const headers = {
      "User-Agent": "curl/7.56.1",
      Accept: "*/*",
      "X-Radiko-App": "pc_html5",
      "X-Radiko-App-Version": "0.0.1",
      "X-Radiko-User": "dummy_user",
      "X-Radiko-Device": "pc",
    };

    const response = await fetch(url, {
      method: "GET",
      headers: headers,
    });

    if (!response.ok) {
      logger.error("Radikoの認証(auth1)に失敗しました。", response);
      throw new Error("Radikoの認証(auth1)に失敗しました。");
    }

    return response;
  }

  /**
   * 認証レスポンスヘッダーから認証トークンを抽出します。
   * @param auth_response 認証APIからのレスポンス。
   * @returns 認証トークン。
   * @throws レスポンスに認証トークンが見つからない場合にエラーをスローします。
   */
  private getAuthTokenFromAuthResponse(auth_response: Response): string {
    const authtoken = auth_response.headers.get("X-Radiko-AuthToken");
    if (!authtoken) {
      logger.error("レスポンスに認証トークンが見つかりませんでした。", auth_response.headers);
      throw new Error("レスポンスに認証トークンが見つかりませんでした。");
    }
    return authtoken;
  }

  /**
   * 認証レスポンスヘッダーから部分キーを生成します。
   * @param auth_response 認証APIからのレスポンス。
   * @returns Base64エンコードされた部分キー。
   * @throws レスポンスにキーのオフセットまたは長さが見つからない場合にエラーをスローします。
   */
  private getPartialKeyFromAuthResponse(auth_response: Response): string {
    const offsetHeader = auth_response.headers.get("X-Radiko-KeyOffset");
    const lengthHeader = auth_response.headers.get("X-Radiko-KeyLength");

    if (!offsetHeader || !lengthHeader) {
      logger.error("レスポンスにキーのオフセットまたは長さが見つかりませんでした。", auth_response.headers);
      throw new Error("レスポンスにキーのオフセットまたは長さが見つかりませんでした。");
    }

    const offset = Number(offsetHeader);
    const length = Number(lengthHeader);

    const partialKeyBase = RadikoClient.AUTH_KEY.slice(offset, offset + length);
    return Buffer.from(partialKeyBase).toString("base64");
  }

  /**
   * Radiko認証のステップ2を実行します。
   * @param authToken 認証ステップ1で取得した認証トークン。
   * @param partialKey 認証ステップ1で生成した部分キー。
   * @returns エリアコード。
   * @throws 認証に失敗した場合にエラーをスローします。
   */
  private async authenticate2(authToken: string, partialKey: string): Promise<string> {
    const url = "https://radiko.jp/v2/api/auth2";
    const headers = {
      "User-Agent": "curl/7.56.1",
      Accept: "*/*",
      "X-Radiko-App": "pc_html5",
      "X-Radiko-App-Version": "0.0.1",
      "X-Radiko-User": "dummy_user",
      "X-Radiko-Device": "pc",
      "X-Radiko-AuthToken": authToken,
      "X-Radiko-PartialKey": partialKey,
    };

    const response = await fetch(url, {
      method: "GET",
      headers: headers,
    });

    if (!response.ok) {
      logger.error("Radikoの認証(auth2)に失敗しました。", response);
      throw new Error("Radikoの認証(auth2)に失敗しました。");
    }

    const body = await response.text();
    const areaCode = body.split(",")[0];
    return areaCode;
  }

  /**
   * APIレスポンスヘッダーをJSONファイルに保存します。デバッグ目的で使用します。
   * @param response `fetch` APIから返される`Response`オブジェクト。
   * @param filename 保存するファイル名。デフォルトは "response_headers.json"。
   */
  public static async saveAuthHeaders(response: Response, filename = "response_headers.json"): Promise<void> {
    const headerObject: Record<string, string> = {};
    response.headers.forEach((value, key) => {
      headerObject[key] = value;
    });

    const json = JSON.stringify(headerObject, null, 2);
    await writeFile(filename, json, "utf8");
  }

  // --- 放送局・番組情報関連 ---

  /**
   * 指定されたエリアのRadiko放送局リストを取得します。
   * @param areaCode エリアコード (例: "JP13")。指定しない場合は認証時に取得したエリアコードを使用します。
   * @returns `Station`オブジェクトの配列。
   * @throws エリアコードが利用できない場合にエラーをスローします。
   */
  public async getStationList(areaCode?: string): Promise<Station[]> {
    const code = areaCode || this.areaCode;
    if (!code) {
      logger.error("エリアコードが指定されておらず、認証情報からも取得できませんでした。", { areaCode: this.areaCode });
      throw new Error(
        "エリアコードが指定されておらず、認証情報からも取得できませんでした。先に認証を行うか、エリアコードを指定してください。",
      );
    }
    const xmlData = await this.fetchStationListXml(code);
    return RadikoClient.parseStationListXml(xmlData);
  }

  /**
   * 放送局リストのXMLをRadikoサーバーから取得します。
   * @param areaCode エリアコード。
   * @returns 放送局リストのXML文字列。
   * @throws XMLの取得に失敗した場合にエラーをスローします。
   */
  private async fetchStationListXml(areaCode: string): Promise<string> {
    const response = await fetch(`https://radiko.jp/v2/station/list/${areaCode}.xml`);
    if (!response.ok) {
      logger.error("Radiko放送局リストの取得に失敗しました。", {
        areaCode,
        status: response.status,
        statusText: response.statusText,
      });
      throw new Error("Radiko放送局リストの取得に失敗しました。");
    }
    return response.text();
  }

  /**
   * 放送局リストのXML文字列をパースし、`Station`オブジェクトの配列に変換します。
   * @param xmlData 放送局リストのXML文字列。
   * @returns パースされた`Station`オブジェクトの配列。
   */
  public static parseStationListXml(xmlData: string): Station[] {
    const parser = new XMLParser();
    const jsonObj = parser.parse(xmlData);
    const stationsArray = jsonObj.stations.station;
    return stationsArray.map((s: { id: string; name: string }) => ({
      id: s.id,
      name: s.name,
    }));
  }

  /**
   * 指定した放送局と日付の番組表を取得します。
   * @param stationId 放送局ID。
   * @param date 日付 (形式: YYYYMMDD)。
   * @returns `RadikoProgram`オブジェクトの配列。
   */
  public async getPrograms(stationId: string, date: string): Promise<RadikoProgram[]> {
    const xmlData = await this.fetchProgramsXml(stationId, date);
    return RadikoClient.parseRadikoProgramXml(xmlData);
  }

  /**
   * 番組表のXMLをRadikoサーバーから取得、またはキャッシュから読み込みます。
   * @param stationId 放送局ID。
   * @param date 日付 (形式: YYYYMMDD)。
   * @returns 番組表のXML文字列。
   * @throws XMLの取得に失敗した場合にエラーをスローします。
   */
  private async fetchProgramsXml(stationId: string, date: string): Promise<string> {
    const cachePath = join(this.cacheDir, `${stationId}_${date}.xml`);
    const cacheExpiry = 60 * 60 * 1000; // 1時間

    try {
      const stats = await stat(cachePath);
      // キャッシュが有効期限内の場合
      if (new Date().getTime() - stats.mtime.getTime() < cacheExpiry) {
        logger.info(`番組表データをキャッシュから使用します: ${cachePath}`);
        return await readFile(cachePath, "utf-8");
      }
    } catch (_error) {
      logger.debug(`キャッシュが見つからないか期限切れです: ${cachePath}`, _error);
      // キャッシュが見つからない場合は、そのまま処理を続行してRadikoから取得
    }

    logger.info(`番組表データをRadikoから取得します: ${stationId}, ${date}`);
    const url = `https://radiko.jp/v3/program/station/date/${date}/${stationId}.xml`;
    const response = await fetch(url);
    if (!response.ok) {
      logger.error("Radiko番組表の取得に失敗しました。", {
        stationId,
        date,
        status: response.status,
        statusText: response.statusText,
      });
      throw new Error("Radiko番組表の取得に失敗しました。");
    }
    const xmlData = await response.text();
    // 取得したXMLをキャッシュに保存
    await writeFile(cachePath, xmlData, "utf-8");
    return xmlData;
  }

  /**
   * 番組情報のXMLをパースして、`RadikoProgram`オブジェクトの配列に変換します。
   * @param xmlData 番組情報を含むXML文字列。
   * @returns パースされた`RadikoProgram`オブジェクトの配列。
   */
  public static parseRadikoProgramXml(xmlData: string): RadikoProgram[] {
    const parser = new XMLParser({
      ignoreAttributes: false, // ft, to, dur などの属性をパースするために必要
      // Radikoの番組表には通常のXMLエンティティが大量に含まれるため、
      // fast-xml-parserの既定値（1,000件）を超えることがあります。
      processEntities: {
        enabled: true,
        maxTotalExpansions: 10_000,
        maxExpandedLength: 1_000_000,
      },
    });
    const jsonObj = parser.parse(xmlData);

    const stationId = jsonObj?.radiko?.stations?.station?.["@_id"] || "不明な放送局ID";
    const stationName = jsonObj?.radiko?.stations?.station?.name || "不明な放送局";

    const programNodes = jsonObj?.radiko?.stations?.station?.progs?.prog;

    if (!programNodes) return [];

    const programs = Array.isArray(programNodes) ? programNodes : [programNodes];

    return programs.map((p, index) => {
      const ft = RadikoClient.asText(p["@_ft"]);
      const to = RadikoClient.asText(p["@_to"]);
      const id = RadikoClient.asText(p["@_id"]) || `${stationId}_${ft}_${index}`;

      return {
        id, // 番組ID
        title: RadikoClient.asText(p.title), // 番組名
        ft, // 開始時間
        to, // 終了時間
        img: RadikoClient.asText(p.img), // 画像URL
        pfm: RadikoClient.asText(p.pfm), // パーソナリティ
        stationId: RadikoClient.asText(stationId), // 放送局ID
        stationName: RadikoClient.asText(stationName), // 放送局名
      };
    });
  }

  // --- 録音関連 ---

  /**
   * Radikoのタイムフリー番組を録音し、M4Aファイルとして保存します。
   * @param program 録音する番組情報 (`RadikoProgram`オブジェクト)。
   * @param stationId 放送局ID (例: "TBS")。
   * @param programTitle 番組名（ファイル名として使用）。
   * @param programImage 番組の画像URL。
   * @param startTime 録音開始時間 (形式: YYYYMMDDHHmmss)。
   * @param endTime 録音終了時間 (形式: YYYYMMDDHHmmss)。
   * @param saveDirectory ファイルを保存するディレクトリのパス。
   * @returns 録音されたファイルのフルパスを含む`Promise<string>`。
   * @throws 認証トークンが見つからない場合にエラーをスローします。
   */
  public getProgramOutputPath(program: RadikoProgram, saveDirectory: string): string {
    const safeProgramTitle = program.title.replace(/[/:*?"<>|]/g, "_");
    const filename = `${program.stationId}_${safeProgramTitle}_${program.ft}.m4a`;
    return join(saveDirectory, filename);
  }

  public async recordProgram(
    program: RadikoProgram,
    stationId: string,
    programTitle: string,
    programImage: string | undefined,
    startTime: string,
    endTime: string,
    saveDirectory: string,
  ): Promise<string> {
    if (!this.authToken) {
      logger.error("録音を開始できません。認証トークンが見つかりません。");
      throw new Error("録音を開始できません。認証トークンが見つかりません。先に認証を行ってください。");
    }

    const finalOutputPath = this.getProgramOutputPath(
      { ...program, stationId, title: programTitle, ft: startTime },
      saveDirectory,
    );

    let cover: M4aCover | undefined;
    if (programImage) {
      try {
        const imageResponse = await fetch(programImage);
        if (!imageResponse.ok) {
          throw new Error(`HTTP ${imageResponse.status} ${imageResponse.statusText}`);
        }

        const imageBuffer = Buffer.from(await imageResponse.arrayBuffer());
        const mimeType = RadikoClient.detectCoverMimeType(
          imageBuffer,
          imageResponse.headers.get("content-type"),
          programImage,
        );
        if (mimeType) {
          cover = { data: imageBuffer, mimeType };
        } else {
          logger.warn("対応していない形式のカバー画像なので、画像なしで保存します。", { programImage });
        }
      } catch (error) {
        logger.warn("カバー画像のダウンロードに失敗したため、画像なしで保存します。", {
          programImage,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }

    const metadata: M4aMetadata = {
      title: programTitle,
      artist: program.pfm,
      album: program.stationName,
      cover,
    };

    return this.executeRecording(stationId, startTime, endTime, finalOutputPath, metadata);
  }

  /**
   * AACセグメントを取得し、M4Aファイルとして保存します。
   * @param stationId 放送局ID。
   * @param startTime 録音開始時間 (形式: YYYYMMDDHHmmss)。
   * @param endTime 録音終了時間 (形式: YYYYMMDDHHmmss)。
   * @param outputPath 出力ファイルのパス。
   * @param metadata M4Aに埋め込むメタデータ。
   * @returns 録音されたファイルのパスを含むPromise。
   * @throws 認証トークンが見つからない場合にエラーをスローします。
   */
  private async executeRecording(
    stationId: string,
    startTime: string,
    endTime: string,
    outputPath: string,
    metadata: M4aMetadata = {},
  ): Promise<string> {
    if (!this.authToken) {
      logger.error("認証トークンが見つかりません。録音を実行できません。");
      return Promise.reject(new Error("認証トークンが見つかりません。"));
    }
    if (!this.areaCode) {
      logger.error("エリアコードが見つかりません。録音を実行できません。");
      return Promise.reject(new Error("エリアコードが見つかりません。"));
    }

    const lsid = randomBytes(16).toString("hex");
    const baseUrl = new URL("https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/playlist.m3u8");
    const headers = {
      "X-Radiko-Authtoken": this.authToken,
      "X-Radiko-AreaId": this.areaCode,
    };

    const segmentUrls = await this.fetchSegmentUrls(baseUrl, headers, {
      stationId,
      startTime,
      endTime,
      lsid,
    });

    if (segmentUrls.length === 0) {
      logger.error("セグメントURLが取得できませんでした。", { stationId, startTime, endTime });
      throw new Error("セグメントURLが取得できませんでした。");
    }

    const tempDir = join(tmpdir(), `radiko_${lsid}`);
    await mkdir(tempDir, { recursive: true });

    try {
      const segmentPaths = await this.downloadSegments(segmentUrls, tempDir);
      await writeM4aFromAdtsFiles(segmentPaths, outputPath, metadata);
      logger.info(`録音が完了しました: ${outputPath}`);
      return outputPath;
    } finally {
      await rm(tempDir, { recursive: true, force: true });
    }
  }

  private async fetchSegmentUrls(
    baseUrl: URL,
    headers: Record<string, string>,
    params: { stationId: string; startTime: string; endTime: string; lsid: string },
  ): Promise<string[]> {
    const { stationId, startTime, endTime, lsid } = params;
    const seekStart = RadikoClient.parseTimeString(startTime);
    const seekEnd = RadikoClient.parseTimeString(endTime);
    const seen = new Set<string>();
    const segments: string[] = [];

    let seekTime = seekStart;

    while (seekTime.getTime() < seekEnd.getTime()) {
      const seekStr = RadikoClient.formatTimeString(seekTime);
      const url = new URL(baseUrl.toString());
      url.searchParams.set("lsid", lsid);
      url.searchParams.set("station_id", stationId);
      url.searchParams.set("l", String(RadikoClient.SEEK_SEC));
      url.searchParams.set("start_at", startTime);
      url.searchParams.set("end_at", endTime);
      url.searchParams.set("type", "b");
      url.searchParams.set("ft", startTime);
      url.searchParams.set("to", endTime);
      url.searchParams.set("seek", seekStr);

      const prePlaylist = await RadikoClient.fetchText(url.toString(), headers);
      const playlistUrls = RadikoClient.parsePlaylist(prePlaylist, url.toString());

      for (const playlistUrl of playlistUrls) {
        const playlist = await RadikoClient.fetchText(playlistUrl);
        const segs = RadikoClient.parsePlaylist(playlist, playlistUrl);
        for (const seg of segs) {
          if (!seen.has(seg)) {
            seen.add(seg);
            segments.push(seg);
          }
        }
      }

      seekTime = new Date(seekTime.getTime() + RadikoClient.SEEK_SEC * 1000);
    }

    return segments;
  }

  private async downloadSegments(segmentUrls: string[], dir: string): Promise<string[]> {
    const filePaths: string[] = [];

    for (let i = 0; i < segmentUrls.length; i++) {
      const segmentUrl = segmentUrls[i];
      const filename = `seg_${String(i).padStart(6, "0")}.aac`;
      const filePath = join(dir, filename);

      const response = await fetch(segmentUrl);
      if (!response.ok) {
        throw new Error(`セグメントのダウンロードに失敗しました: ${response.status} ${response.statusText}`);
      }
      const buffer = Buffer.from(await response.arrayBuffer());
      await writeFile(filePath, buffer);
      filePaths.push(filePath);
    }

    return filePaths;
  }

  private static parsePlaylist(playlist: string, baseUrl: string): string[] {
    return playlist
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line.length > 0 && !line.startsWith("#"))
      .map((line) => new URL(line, baseUrl).toString());
  }

  private static async fetchText(url: string, headers?: Record<string, string>): Promise<string> {
    const response = await fetch(url, headers ? { headers } : undefined);
    if (!response.ok) {
      throw new Error(`HTTPエラー: ${response.status} ${response.statusText}`);
    }
    return response.text();
  }

  private static parseTimeString(value: string): Date {
    if (!/^\d{14}$/.test(value)) {
      throw new Error(`時刻の形式が不正です: ${value}`);
    }
    const year = Number(value.slice(0, 4));
    const month = Number(value.slice(4, 6));
    const day = Number(value.slice(6, 8));
    const hour = Number(value.slice(8, 10));
    const minute = Number(value.slice(10, 12));
    const second = Number(value.slice(12, 14));
    return new Date(year, month - 1, day, hour, minute, second);
  }

  private static formatTimeString(date: Date): string {
    const pad = (num: number) => String(num).padStart(2, "0");
    return (
      `${date.getFullYear()}` +
      `${pad(date.getMonth() + 1)}` +
      `${pad(date.getDate())}` +
      `${pad(date.getHours())}` +
      `${pad(date.getMinutes())}` +
      `${pad(date.getSeconds())}`
    );
  }
}
