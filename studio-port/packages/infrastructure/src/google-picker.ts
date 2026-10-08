// Picker setAppId 값 = Cloud 프로젝트 번호. 웹 클라이언트 ID가 `<프로젝트 번호>-xxxx.apps.googleusercontent.com`
// 꼴이라, 프로젝트 번호를 따로 설정하지 않았으면 거기서 꺼낸다(synsory-api config.picker_app_id, 2026-10-04 실측).
// Picker에 쓰는 토큰의 클라이언트가 속한 프로젝트와 같아야 한다.
export function pickerAppId(clientId: string, projectNumber?: string): string | null {
  if (projectNumber) return projectNumber;
  const head = clientId.split('-', 1)[0] ?? '';
  return /^\d+$/.test(head) ? head : null;
}
