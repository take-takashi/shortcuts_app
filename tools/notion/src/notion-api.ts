import type {
  FileUploadResult,
  JsonObject,
  NotionPage,
  NotionProperties,
  NotionQueryResponse,
} from "./types";

export interface NotionApiOptions {
  token: string;
  version?: string;
  baseUrl?: string;
  fetcher?: typeof fetch;
}

export interface CreateFileUploadRequest {
  filename: string;
  contentType?: string;
  mode?: "single_part" | "multi_part";
  numberOfParts?: number;
}

export class NotionApiError extends Error {
  public readonly status: number;
  public readonly body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "NotionApiError";
    this.status = status;
    this.body = body;
  }
}

export class NotionApi {
  private readonly token: string;
  private readonly version: string;
  private readonly baseUrl: string;
  private readonly fetcher: typeof fetch;

  constructor(options: NotionApiOptions) {
    if (!options.token) {
      throw new Error("Notion APIトークンが指定されていません。");
    }

    this.token = options.token;
    this.version = options.version ?? "2022-06-28";
    this.baseUrl = (options.baseUrl ?? "https://api.notion.com/v1/").replace(/\/$/, "") + "/";
    this.fetcher = options.fetcher ?? fetch;
  }

  public async queryDatabase(
    databaseId: string,
    filter?: JsonObject,
  ): Promise<NotionQueryResponse> {
    const body: JsonObject = {};
    if (filter) body.filter = filter;

    return this.request<NotionQueryResponse>(`databases/${encodeURIComponent(databaseId)}/query`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  public async findPageByTitle(
    databaseId: string,
    title: string,
    titleProperty = "Name",
  ): Promise<string | undefined> {
    const response = await this.queryDatabase(databaseId, {
      property: titleProperty,
      title: { equals: title },
    });
    return response.results[0]?.id;
  }

  public async createDatabasePage(
    databaseId: string,
    properties: NotionProperties,
  ): Promise<NotionPage> {
    return this.request<NotionPage>("pages", {
      method: "POST",
      body: JSON.stringify({
        parent: { database_id: databaseId },
        properties,
      }),
    });
  }

  public async retrievePage(pageId: string): Promise<NotionPage> {
    return this.request<NotionPage>(`pages/${encodeURIComponent(pageId)}`);
  }

  public async findFileUploadIdByCaption(
    pageId: string,
    caption: string,
  ): Promise<string | undefined> {
    let cursor: string | undefined;

    while (true) {
      const params = new URLSearchParams({ page_size: "100" });
      if (cursor) params.set("start_cursor", cursor);
      const response = await this.request<{
        results?: JsonObject[];
        has_more?: boolean;
        next_cursor?: string | null;
      }>(`blocks/${encodeURIComponent(pageId)}/children?${params}`);

      for (const block of response.results ?? []) {
        const blockType = typeof block.type === "string" ? block.type : "";
        const blockContent = block[blockType];
        if (!blockContent || typeof blockContent !== "object") continue;

        const content = blockContent as JsonObject;
        if (content.type !== "file_upload" || getRichTextContent(content.caption) !== caption) {
          continue;
        }

        const fileUpload = content.file_upload;
        if (!fileUpload || typeof fileUpload !== "object") continue;
        const uploadId = (fileUpload as JsonObject).id;
        if (typeof uploadId === "string") return uploadId;
      }

      if (!response.has_more || !response.next_cursor) return undefined;
      cursor = response.next_cursor;
    }
  }

  public async updatePage(pageId: string, properties: NotionProperties): Promise<NotionPage> {
    return this.request<NotionPage>(`pages/${encodeURIComponent(pageId)}`, {
      method: "PATCH",
      body: JSON.stringify({ properties }),
    });
  }

  public async appendBlockChildren(pageId: string, children: JsonObject[]): Promise<JsonObject> {
    return this.request<JsonObject>(`blocks/${encodeURIComponent(pageId)}/children`, {
      method: "PATCH",
      body: JSON.stringify({ children }),
    });
  }

  public async appendFileBlock(
    pageId: string,
    fileUploadId: string,
    fileType: "audio" | "video" | "image" | "file",
    caption: string,
  ): Promise<void> {
    await this.appendBlockChildren(pageId, [
      {
        type: fileType,
        [fileType]: {
          caption: caption
            ? [
                {
                  type: "text",
                  text: { content: caption, link: null },
                },
              ]
            : [],
          type: "file_upload",
          file_upload: { id: fileUploadId },
        },
      },
    ]);
  }

  /**
   * Files & mediaプロパティへファイルを追加します。
   * propertyNameを省略すると、ページ内の最初のfilesプロパティを使用します。
   */
  public async appendFileProperty(
    pageId: string,
    fileUploadId: string,
    fileName: string,
    propertyName?: string,
  ): Promise<string | undefined> {
    const page = await this.retrievePage(pageId);
    const properties = page.properties ?? {};
    const targetPropertyName =
      propertyName ??
      Object.entries(properties).find(([, property]) => property.type === "files")?.[0];

    if (!targetPropertyName) return undefined;

    const currentProperty = properties[targetPropertyName];
    const existingFiles = Array.isArray(currentProperty?.files) ? currentProperty.files : [];
    const alreadyAttached = existingFiles.some((file) => {
      const existingUploadId = file.file_upload;
      return (
        file.name === fileName ||
        (existingUploadId &&
          typeof existingUploadId === "object" &&
          (existingUploadId as JsonObject).id === fileUploadId)
      );
    });
    if (alreadyAttached) return targetPropertyName;

    const newFile = {
      type: "file_upload",
      name: fileName,
      file_upload: { id: fileUploadId },
    };

    await this.updatePage(pageId, {
      [targetPropertyName]: { files: [...existingFiles, newFile] },
    });
    return targetPropertyName;
  }

  public async createFileUpload(request: CreateFileUploadRequest): Promise<FileUploadResult> {
    const payload: JsonObject = { filename: request.filename };
    if (request.contentType) payload.content_type = request.contentType;
    if (request.mode) payload.mode = request.mode;
    if (request.numberOfParts) payload.number_of_parts = request.numberOfParts;

    return this.request<FileUploadResult>("file_uploads", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  public async sendFileUploadPart(
    fileUploadId: string,
    formData: FormData,
  ): Promise<FileUploadResult> {
    return this.request<FileUploadResult>(
      `file_uploads/${encodeURIComponent(fileUploadId)}/send`,
      {
        method: "POST",
        body: formData,
      },
    );
  }

  public async completeFileUpload(fileUploadId: string): Promise<FileUploadResult> {
    return this.request<FileUploadResult>(
      `file_uploads/${encodeURIComponent(fileUploadId)}/complete`,
      { method: "POST" },
    );
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${this.token}`);
    headers.set("Notion-Version", this.version);
    headers.set("Accept", "application/json");

    if (
      init.body !== undefined &&
      init.body !== null &&
      !(init.body instanceof FormData) &&
      !headers.has("Content-Type")
    ) {
      headers.set("Content-Type", "application/json");
    }

    const response = await this.fetcher(new URL(path, this.baseUrl), {
      ...init,
      headers,
    });
    const text = await response.text();
    const body = parseResponseBody(text);

    if (!response.ok) {
      const detail = typeof body === "object" && body !== null ? JSON.stringify(body) : text;
      throw new NotionApiError(
        `Notion APIリクエストに失敗しました: ${response.status} ${detail}`,
        response.status,
        body,
      );
    }

    return body as T;
  }
}

function getRichTextContent(value: unknown): string {
  if (!Array.isArray(value)) return "";
  return value
    .map((item) => {
      if (!item || typeof item !== "object") return "";
      const richText = item as JsonObject;
      if (typeof richText.plain_text === "string") return richText.plain_text;
      const text = richText.text;
      return text && typeof text === "object" && typeof (text as JsonObject).content === "string"
        ? ((text as JsonObject).content as string)
        : "";
    })
    .join("");
}

function parseResponseBody(text: string): unknown {
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
