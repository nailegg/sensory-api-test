// 브라우저 전용: Google Picker를 띄워 교수자가 고른 파일 ID를 돌려준다(취소하면 빈 배열).
// synsory-api app/services/google_drive/picker.py 테스트 페이지 JS의 이식본. 조건은 docs/google_drive.md 2.1절.
// - drive.file 앱에 파일 접근이 생기려면 developerKey·appId(프로젝트 번호)·oauthToken 셋 다 필요하다.
// - 브라우저가 Google에 로그인돼 있어야 한다(토큰만으로는 "Sign in" 화면, 2026-10-04 실측).
// - access token은 인자로만 받고 저장하지 않는다(localStorage 등 금지). 쓰고 나서 revoke하지 않는다:
//   revoke하면 같은 프로젝트의 서버 refresh token까지 무효가 된다는 보고가 있다(1시간 만료에 맡긴다).

export type PickableKind = 'doc' | 'slides' | 'sheet' | 'form' | 'folder';

const MIME: Record<PickableKind, string> = {
  doc: 'application/vnd.google-apps.document',
  slides: 'application/vnd.google-apps.presentation',
  sheet: 'application/vnd.google-apps.spreadsheet',
  form: 'application/vnd.google-apps.form',
  folder: 'application/vnd.google-apps.folder',
};

// google.picker 중 쓰는 부분만.
interface DocsView {
  setMimeTypes(mimeTypes: string): DocsView;
  setIncludeFolders(include: boolean): DocsView;
  setSelectFolderEnabled(enabled: boolean): DocsView;
}
interface PickerBuilder {
  setOAuthToken(token: string): PickerBuilder;
  setDeveloperKey(key: string): PickerBuilder;
  setAppId(appId: string): PickerBuilder;
  setOrigin(origin: string): PickerBuilder;
  setTitle(title: string): PickerBuilder;
  addView(view: DocsView): PickerBuilder;
  enableFeature(feature: string): PickerBuilder;
  setCallback(callback: (data: PickerResponse) => void): PickerBuilder;
  build(): { setVisible(visible: boolean): void };
}
interface PickerResponse {
  action: string;
  docs?: { id: string }[];
}
export interface PickerApi {
  PickerBuilder: new () => PickerBuilder;
  DocsView: new (viewId: string) => DocsView;
  ViewId: { DOCS: string };
  Feature: { MULTISELECT_ENABLED: string };
  Action: { PICKED: string; CANCEL: string };
}

export interface PickerOptions {
  accessToken: string;
  developerKey: string;
  appId: string;
  // 이 페이지의 origin(iframe postMessage 대상 확인용).
  origin: string;
  kinds: PickableKind[];
  multiple?: boolean;
  title?: string;
}

// gapi 스크립트를 한 번만 올리고 picker 모듈을 불러온다.
let loading: Promise<PickerApi> | null = null;
export function loadPickerApi(): Promise<PickerApi> {
  loading ??= new Promise<PickerApi>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://apis.google.com/js/api.js';
    script.async = true;
    script.onerror = () => {
      loading = null;
      reject(new Error('Google Picker를 불러오지 못했습니다.'));
    };
    script.onload = () => {
      const w = window as unknown as {
        gapi: { load(name: string, callback: () => void): void };
        google: { picker: PickerApi };
      };
      w.gapi.load('picker', () => resolve(w.google.picker));
    };
    document.head.append(script);
  });
  return loading;
}

export async function pickGoogleFiles(
  options: PickerOptions,
  load: () => Promise<PickerApi> = loadPickerApi,
): Promise<string[]> {
  const picker = await load();
  const view = new picker.DocsView(picker.ViewId.DOCS)
    .setMimeTypes(options.kinds.map((k) => MIME[k]).join(','))
    .setIncludeFolders(true)
    .setSelectFolderEnabled(options.kinds.includes('folder'));
  return new Promise<string[]>((resolve) => {
    const builder = new picker.PickerBuilder()
      .setOAuthToken(options.accessToken)
      .setDeveloperKey(options.developerKey)
      .setAppId(options.appId)
      .setOrigin(options.origin)
      .setTitle(options.title ?? '템플릿으로 쓸 파일 고르기')
      .addView(view)
      // 콜백은 PICKED·CANCEL 말고 "loaded"도 온다. 그건 무시한다.
      .setCallback((data) => {
        if (data.action === picker.Action.PICKED) resolve((data.docs ?? []).map((d) => d.id));
        else if (data.action === picker.Action.CANCEL) resolve([]);
      });
    if (options.multiple) builder.enableFeature(picker.Feature.MULTISELECT_ENABLED);
    builder.build().setVisible(true);
  });
}
