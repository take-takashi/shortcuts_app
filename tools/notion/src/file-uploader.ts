import { open, stat } from "fs/promises";
import { basename, extname } from "path";
import { NotionApi } from "./notion-api";
import type { FileUploadResult, MimeTypeInfo, NotionFileType } from "./types";

export const SINGLE_PART_LIMIT_BYTES = 20 * 1024 * 1024;
export const MULTI_PART_SIZE_BYTES = 10 * 1024 * 1024;

export interface UploadFileOptions {
  fileType?: NotionFileType;
  mimeType?: string;
  maxRetries?: number;
}

export class NotionFileUploader {
  constructor(private readonly api: NotionApi) {}

  public async uploadFile(
    filePath: string,
    options: UploadFileOptions = {},
  ): Promise<FileUploadResult> {
    const fileName = basename(filePath);
    const fileSize = (await stat(filePath)).size;
    const mimeTypeInfo = getMimeTypeFromPath(filePath);
    const mimeType = options.mimeType ?? mimeTypeInfo.mimeType;
    const maxRetries = options.maxRetries ?? 3;

    if (fileSize <= SINGLE_PART_LIMIT_BYTES) {
      const fileUpload = await this.api.createFileUpload({ filename: fileName });
      const fileData = await readFileBytes(filePath, 0, fileSize);
      await retry(
        () => {
          const formData = new FormData();
          formData.append("file", makeBlob(fileData, mimeType), fileName);
          return this.api.sendFileUploadPart(fileUpload.id, formData);
        },
        maxRetries,
      );
      return fileUpload;
    }

    const numberOfParts = Math.ceil(fileSize / MULTI_PART_SIZE_BYTES);
    const fileUpload = await this.api.createFileUpload({
      filename: fileName,
      contentType: mimeType,
      mode: "multi_part",
      numberOfParts,
    });

    const handle = await open(filePath, "r");
    try {
      for (let partNumber = 1; partNumber <= numberOfParts; partNumber += 1) {
        const offset = (partNumber - 1) * MULTI_PART_SIZE_BYTES;
        const length = Math.min(MULTI_PART_SIZE_BYTES, fileSize - offset);
        const fileData = await readFileBytesFromHandle(handle, offset, length);

        await retry(
          () => {
            const formData = new FormData();
            formData.append("file", makeBlob(fileData, mimeType), fileName);
            formData.append("part_number", String(partNumber));
            return this.api.sendFileUploadPart(fileUpload.id, formData);
          },
          maxRetries,
        );
      }
    } finally {
      await handle.close();
    }

    return this.api.completeFileUpload(fileUpload.id);
  }

  public async uploadAndAttach(
    pageId: string,
    filePath: string,
    options: UploadFileOptions & {
      caption?: string;
      filePropertyName?: string | null;
    } = {},
  ): Promise<{ fileUpload: FileUploadResult; filePropertyName?: string }> {
    const fileUpload = await this.uploadFile(filePath, options);
    const mimeTypeInfo = getMimeTypeFromPath(filePath);
    const fileType = options.fileType ?? mimeTypeInfo.fileType;
    const fileName = basename(filePath);

    await this.api.appendFileBlock(
      pageId,
      fileUpload.id,
      fileType,
      options.caption ?? fileName,
    );

    const filePropertyName =
      options.filePropertyName === null
        ? undefined
        : await this.api.appendFileProperty(
            pageId,
            fileUpload.id,
            fileName,
            options.filePropertyName,
          );

    return { fileUpload, filePropertyName };
  }
}

export function getMimeTypeFromPath(filePath: string): MimeTypeInfo {
  const extension = extname(filePath).toLowerCase();
  const mimeTypes: Record<string, MimeTypeInfo> = {
    ".m4a": { mimeType: "audio/mp4", fileType: "audio" },
    ".mp3": { mimeType: "audio/mpeg", fileType: "audio" },
    ".mp4": { mimeType: "video/mp4", fileType: "video" },
    ".mov": { mimeType: "video/quicktime", fileType: "video" },
    ".jpg": { mimeType: "image/jpeg", fileType: "image" },
    ".jpeg": { mimeType: "image/jpeg", fileType: "image" },
    ".png": { mimeType: "image/png", fileType: "image" },
    ".gif": { mimeType: "image/gif", fileType: "image" },
    ".webp": { mimeType: "image/webp", fileType: "image" },
  };
  return mimeTypes[extension] ?? { mimeType: "application/octet-stream", fileType: "file" };
}

async function readFileBytes(filePath: string, offset: number, length: number): Promise<Buffer> {
  const handle = await open(filePath, "r");
  try {
    return await readFileBytesFromHandle(handle, offset, length);
  } finally {
    await handle.close();
  }
}

function makeBlob(data: Buffer, mimeType: string): Blob {
  const arrayBuffer = new ArrayBuffer(data.byteLength);
  new Uint8Array(arrayBuffer).set(data);
  return new Blob([arrayBuffer], { type: mimeType });
}

async function readFileBytesFromHandle(
  handle: Awaited<ReturnType<typeof open>>,
  offset: number,
  length: number,
): Promise<Buffer> {
  const buffer = Buffer.alloc(length);
  const result = await handle.read(buffer, 0, length, offset);
  return result.bytesRead === length ? buffer : buffer.subarray(0, result.bytesRead);
}

async function retry<T>(operation: () => Promise<T>, maxRetries: number): Promise<T> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= maxRetries; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      if (attempt < maxRetries) {
        await new Promise((resolve) => setTimeout(resolve, 1000 * attempt));
      }
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}
