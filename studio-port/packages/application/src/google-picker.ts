import { AppError, type DocumentKind, type ExternalDocument } from '../../domain/src/index.ts';
import { mapConcurrently } from './concurrency.ts';
import type { GoogleDrivePort } from './integration-ports.ts';

// Picker로 고른 파일을 받아들이기 전에 서버가 실제로 볼 수 있는지, 허용한 종류인지 확인한다.
// 서버가 못 보면(404) setAppId 누락이나 다른 GCP 프로젝트의 토큰으로 띄운 경우다(docs/google_drive.md 2.1절).
// 공유받은 파일(소유자가 다른 사람)도 고를 수 있고 접근이 생긴다(2026-10-04 실측).

export interface PickedFileResult {
  file_id: string;
  document: ExternalDocument | null;
  error: AppError | null;
}

export async function acceptPickedFiles(
  drive: GoogleDrivePort,
  fileIds: string[],
  allowedKinds: DocumentKind[],
): Promise<PickedFileResult[]> {
  return mapConcurrently(fileIds, async (fileId): Promise<PickedFileResult> => {
    try {
      const document = await drive.getFile(fileId);
      if (document.trashed || !allowedKinds.includes(document.kind))
        return {
          file_id: fileId,
          document: null,
          error: new AppError('UNSUPPORTED_TEMPLATE', 422, '이 파일은 템플릿으로 쓸 수 없습니다.'),
        };
      return { file_id: fileId, document, error: null };
    } catch (e) {
      if (!(e instanceof AppError)) throw e;
      return { file_id: fileId, document: null, error: e };
    }
  });
}
