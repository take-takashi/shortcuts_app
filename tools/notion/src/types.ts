import type { NotionApi } from "./notion-api";

export type JsonObject = Record<string, unknown>;

export type NotionProperty = JsonObject & {
  type?: string;
  files?: JsonObject[];
};

export type NotionProperties = Record<string, NotionProperty>;

export interface NotionPage {
  id: string;
  properties?: NotionProperties;
  [key: string]: unknown;
}

export interface NotionQueryResponse {
  results: NotionPage[];
  has_more?: boolean;
  next_cursor?: string | null;
}

export interface FileUploadResult {
  id: string;
  object?: string;
  [key: string]: unknown;
}

export type NotionFileType = "audio" | "video" | "image" | "file";

export interface MimeTypeInfo {
  mimeType: string;
  fileType: NotionFileType;
}

export interface UploadPlan {
  databaseId: string;
  title: string;
  filePath: string;
  titleProperty?: string;
  properties?: NotionProperties;
  filePropertyName?: string | null;
  fileType?: NotionFileType;
}

export interface UploadManifestFile {
  path: string;
  title?: string;
  properties?: NotionProperties;
  filePropertyName?: string | null;
  fileType?: NotionFileType;
  metadata?: JsonObject;
}

export interface UploadManifest {
  version: 1;
  generatedAt?: string;
  files: UploadManifestFile[];
}

export interface UploadContext {
  readonly api: NotionApi;
  readonly plan: UploadPlan;
  pageId?: string;
  fileUpload?: FileUploadResult;
  filePropertyName?: string;
}

export interface PageCreatePatch {
  title?: string;
  properties?: NotionProperties;
}

export interface NotionUploadHooks {
  beforePageCreate?: (context: UploadContext) => Promise<PageCreatePatch | void>;
  afterPageCreated?: (context: UploadContext) => Promise<void>;
  afterPageResolved?: (context: UploadContext) => Promise<void>;
  beforeFileUpload?: (context: UploadContext) => Promise<void>;
  afterFileUploaded?: (context: UploadContext) => Promise<void>;
  beforeFileAttached?: (context: UploadContext) => Promise<void>;
  afterFileAttached?: (context: UploadContext) => Promise<void>;
  afterSuccess?: (context: UploadContext) => Promise<void>;
  onError?: (context: UploadContext, error: unknown) => Promise<void>;
}

export interface NotionUploadResult {
  pageId: string;
  fileUploadId: string;
  filePath: string;
  filePropertyName?: string;
}
