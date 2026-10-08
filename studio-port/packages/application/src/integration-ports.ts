import type { ExternalDocument } from '../../domain/src/index.ts';

// 외부 서비스 port. 메서드는 의미 단위이고 Google 요청 모양은 infrastructure 어댑터 뒤에 둔다.
// 토큰은 인자로 받지 않는다. 어댑터가 만들어질 때 그 교수자의 토큰 공급자를 받는다.
// synsory-api에서 실측된 흐름(usecases.py)이 쓰는 호출만 둔다.

export type DriveRole = 'reader' | 'commenter' | 'writer';

export interface DrivePermission {
  id: string;
  type: 'user' | 'group' | 'domain' | 'anyone';
  role: string;
  email: string | null;
  display_name: string | null;
  // Forms 응답자 권한이면 'published'.
  view: string | null;
}

// 변환 업로드: Markdown·docx → Docs, pptx → Slides, xlsx·csv → Sheets.
export type UploadSource = 'markdown' | 'docx' | 'pptx' | 'xlsx' | 'csv';
export type UploadTarget = 'doc' | 'slides' | 'sheet';

// files.export 형식. Drive에는 Slides 이미지 형식이 없고, Sheets csv·tsv는 첫 시트만 나온다.
export type ExportFormat =
  'docx' | 'pdf' | 'txt' | 'md' | 'html' | 'pptx' | 'odp' | 'xlsx' | 'csv' | 'tsv' | 'ods' | 'zip';

export interface ExportedFile {
  file_id: string;
  filename: string;
  mime_type: string;
  content: Uint8Array;
}

// Google Drive. drive.file scope라 앱이 만든 파일과 사용자가 Picker로 고른 파일만 보인다.
// 그 밖의 파일은 오타 ID와 같은 404다.
export interface GoogleDrivePort {
  getFile(fileId: string): Promise<ExternalDocument>;
  // 사용자가 Drive 웹에서 만든(앱이 못 보는) 폴더 아래에도 만들 수 있다.
  createFolder(name: string, parentFolderId?: string): Promise<ExternalDocument>;
  // 업로드하면서 Google 형식으로 변환한다. multipart 업로드라 5MB 이하.
  createFromContent(input: {
    name: string;
    content: Uint8Array | string;
    source: UploadSource;
    target: UploadTarget;
    parentFolderId?: string;
  }): Promise<ExternalDocument>;
  // 사본은 앱이 만든 파일이 된다. 원본이 앱에 안 보이면(Picker로 안 고른 템플릿) 404.
  copyFile(fileId: string, name: string, parentFolderId?: string): Promise<ExternalDocument>;
  // Docs·Slides·Sheets·Forms 생성 API는 폴더를 못 정해서 만든 뒤 옮긴다.
  moveFile(fileId: string, toFolderId: string): Promise<ExternalDocument>;
  // 휴지통 파일은 뺀다.
  listFiles(pageSize?: number): Promise<ExternalDocument[]>;
  // 파일 종류에 맞는 형식표로 내보낸다. 파일 이름은 Drive 이름 + 확장자. 10MB 상한.
  exportFile(fileId: string, format: ExportFormat): Promise<ExportedFile>;
  trashFile(fileId: string): Promise<void>;
  shareWithUser(
    fileId: string,
    email: string,
    role: DriveRole,
    options?: { notify?: boolean; message?: string },
  ): Promise<DrivePermission>;
  // Forms 응답자 권한(view=published). email이 null이면 "링크가 있는 모든 사용자". 알림은 보내지 않는다.
  shareAsResponder(fileId: string, email: string | null): Promise<DrivePermission>;
  // includePublishedView면 Forms 응답자 권한도 함께 온다.
  listPermissions(
    fileId: string,
    options?: { includePublishedView?: boolean },
  ): Promise<DrivePermission[]>;
  // 마감: 편집자(writer)를 commenter·reader로 낮춘다.
  updatePermissionRole(
    fileId: string,
    permissionId: string,
    role: DriveRole,
  ): Promise<DrivePermission>;
  deletePermission(fileId: string, permissionId: string): Promise<void>;
}
