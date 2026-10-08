import { z } from 'zod';

// 외부 자원(Google 파일, Zoom 미팅)을 Synsory가 저장·표시하는 공통 형식.
// activities.external_refs 항목과 화면 DTO의 근거가 된다. 시각은 ISO 8601 문자열로 둔다.
export const documentKind = z.enum(['doc', 'sheet', 'slides', 'form', 'folder', 'file']);
export type DocumentKind = z.infer<typeof documentKind>;

// Docs·Sheets·Slides·Forms·Drive 파일의 공통 표현. owner·created_at·modified_at·url은 Drive files.get에서 온다.
export const externalDocument = z.object({
  id: z.string().min(1),
  provider: z.literal('google'),
  kind: documentKind,
  title: z.string(),
  url: z.string().nullable(),
  mime_type: z.string().nullable(),
  // 소유자 표시 이름. 이메일은 넣지 않는다.
  owner: z.string().nullable(),
  created_at: z.string().nullable(),
  modified_at: z.string().nullable(),
  parent_folder_id: z.string().nullable(),
  // 휴지통 문서도 Drive·Docs API는 200을 돌려주므로 호출자가 이 값을 봐야 한다.
  trashed: z.boolean(),
  // Drive contentRestrictions.readOnly. 마감은 권한 낮추기로 하므로 보통 false다.
  locked: z.boolean(),
  // 본문 평문. 읽기 흐름에서만 채운다.
  text: z.string().nullable(),
});
export type ExternalDocument = z.infer<typeof externalDocument>;

// 그룹 파일 제목·본문의 {{team_name}} 같은 태그를 치환한다. 없는 변수는 그대로 둔다(Markdown의 다른 중괄호와 충돌 방지).
export function renderTemplate(template: string, variables: Record<string, string>): string {
  return template.replace(/\{\{\s*([\p{L}\p{N}_]+)\s*\}\}/gu, (tag, key: string) =>
    Object.hasOwn(variables, key) ? (variables[key] ?? tag) : tag,
  );
}

// 그룹 파일 템플릿 변수. Docs·Slides·Sheets가 같은 이름을 쓴다.
export function groupVariables(
  teamName: string,
  activityName: string,
  due: string | null,
): Record<string, string> {
  return { team_name: teamName, activity_name: activityName, due: due ?? '' };
}
