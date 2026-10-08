import { z } from 'zod';

// Google Picker(교수자가 Drive에 이미 가진 파일을 템플릿으로 고르기)용 웹·API 계약.
// 결정(2026-10-09): Picker를 열 때만 서버가 그 교수자의 짧은 수명 access token을 내려준다.
// 브라우저는 메모리에만 두고 저장하지 않는다. refresh token은 절대 내려주지 않는다.

// Picker 세션 응답. 응답은 Cache-Control: no-store로 보낸다.
export const pickerSession = z.object({
  // drive.file scope의 access token. 만료까지 남은 시간이 짧으면 서버가 먼저 갱신해서 준다.
  access_token: z.string().min(1),
  expires_at: z.iso.datetime(),
  // Google Picker API를 사용 설정한 API 키(브라우저에 노출되는 값, 시크릿 아님).
  developer_key: z.string().min(1),
  // Cloud 프로젝트 번호. drive.file에서 빠뜨리면 고른 파일에 앱 권한이 기록되지 않는다.
  app_id: z.string().regex(/^\d+$/),
});
export type PickerSession = z.infer<typeof pickerSession>;

// 고른 파일 ID. 서버가 실제로 볼 수 있는지·템플릿 종류인지 확인한다.
export const pickedFiles = z.object({
  file_ids: z.array(z.string().min(1)).min(1).max(20),
});
export type PickedFiles = z.infer<typeof pickedFiles>;
