import { basename } from "path";
import { NotionFileUploader, getMimeTypeFromPath } from "./file-uploader";
import { NotionApi } from "./notion-api";
import type {
  NotionProperties,
  NotionUploadHooks,
  NotionUploadResult,
  PageCreatePatch,
  UploadContext,
  UploadPlan,
} from "./types";

export class NotionUploadWorkflow {
  private readonly uploader: NotionFileUploader;

  constructor(
    private readonly api: NotionApi,
    uploader = new NotionFileUploader(api),
  ) {
    this.uploader = uploader;
  }

  public async execute(
    plan: UploadPlan,
    hooks: NotionUploadHooks = {},
  ): Promise<NotionUploadResult> {
    const context: UploadContext = { api: this.api, plan };

    try {
      let pageId = await this.api.findPageByTitle(
        plan.databaseId,
        plan.title,
        plan.titleProperty ?? "Name",
      );

      if (!pageId) {
        const patchResult = await hooks.beforePageCreate?.(context);
        const patch: PageCreatePatch | undefined =
          patchResult === undefined ? undefined : patchResult;
        const pageProperties = makePageProperties(plan, patch);
        const page = await this.api.createDatabasePage(plan.databaseId, pageProperties);
        pageId = page.id;
        context.pageId = pageId;
        await hooks.afterPageCreated?.(context);
      } else {
        context.pageId = pageId;
      }

      await hooks.afterPageResolved?.(context);
      const fileName = basename(plan.filePath);
      const existingUploadId = await this.api.findFileUploadIdByCaption(pageId, fileName);

      await hooks.beforeFileUpload?.(context);
      const upload = existingUploadId
        ? { id: existingUploadId }
        : await this.uploader.uploadFile(plan.filePath, { fileType: plan.fileType });
      context.fileUpload = upload;
      if (!existingUploadId) await hooks.afterFileUploaded?.(context);

      const mimeTypeInfo = getMimeTypeFromPath(plan.filePath);
      await hooks.beforeFileAttached?.(context);
      if (!existingUploadId) {
        await this.api.appendFileBlock(
          pageId,
          upload.id,
          plan.fileType ?? mimeTypeInfo.fileType,
          fileName,
        );
      }

      if (plan.filePropertyName !== null) {
        context.filePropertyName = await this.api.appendFileProperty(
          pageId,
          upload.id,
          fileName,
          plan.filePropertyName,
        );
      }

      await hooks.afterFileAttached?.(context);
      await hooks.afterSuccess?.(context);

      return {
        pageId,
        fileUploadId: upload.id,
        filePath: plan.filePath,
        filePropertyName: context.filePropertyName,
      };
    } catch (error) {
      await hooks.onError?.(context, error);
      throw error;
    }
  }
}

function makePageProperties(plan: UploadPlan, patch?: PageCreatePatch): NotionProperties {
  const titleProperty = plan.titleProperty ?? "Name";
  const title = patch?.title ?? plan.title;
  return {
    [titleProperty]: {
      title: [{ text: { content: title } }],
    },
    ...plan.properties,
    ...patch?.properties,
  };
}
