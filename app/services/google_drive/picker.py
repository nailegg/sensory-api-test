"""Google Picker 테스트 페이지 (GET /google/picker). 라우터처럼 서비스 레포로 옮기지 않는다.

목적: 교수자가 Drive에 이미 가진 Docs·Slides·Sheets 파일(앱이 만들지 않은 파일)을 Picker로 고르면
`drive.file` scope만으로 그 파일에 앱 접근이 생기는지 실측한다. 고른 파일 ID를 화면에 보여 주고,
바로 `GET /google/drive/file-meta/{id}`를 불러 서버(같은 토큰)가 그 파일을 볼 수 있게 됐는지 확인한다.

조건(docs/google_drive.md 2.1절, 공식 문서 2026-09-03/09-14 기준):
- `setDeveloperKey(API 키)`: 콘솔에서 Google Picker API 사용 설정 후 만든 API 키. 없거나 제한이 틀리면 "API developer key is invalid".
- `setAppId(Cloud 프로젝트 번호)`: **drive.file scope에 필수.** 빠뜨리면 선택은 되지만 앱에 파일 접근 권한이 기록되지 않는다.
- `setOAuthToken(access token)`: drive.file로 받은 토큰. 이 토큰의 클라이언트가 속한 프로젝트 번호 = setAppId 값이어야 한다.

이 테스트 페이지는 토큰을 **서버 token_store에서 꺼내** 브라우저에 넘긴다(/google/picker/config). 서버가 쓰는 토큰과 같은 토큰으로
Picker를 띄워야 "고른 뒤 서버가 접근 가능해지는가"를 그대로 검증할 수 있기 때문이다. Synsory 프론트엔드에서는 아래 HTML의
주석처럼 GIS(`google.accounts.oauth2.initTokenClient`)로 브라우저가 직접 토큰을 받는 방식도 가능하다(같은 프로젝트의 클라이언트여야 함).
"""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.core.config import Settings, get_settings
from app.core.oauth import access_token_dependency

router = APIRouter(prefix="/google/picker", tags=["google_picker"])

google_token = access_token_dependency("google")


@router.get("/config")
async def picker_config(settings: Settings = Depends(get_settings), token: str = Depends(google_token)):
    """Picker를 띄우는 데 필요한 값. 테스트 페이지 전용 — access token을 브라우저에 그대로 준다(localhost 테스트에서만 허용)."""
    return {
        "api_key": settings.google_picker_api_key,
        "app_id": settings.picker_app_id(),
        "client_id": settings.google_client_id,
        "access_token": token,
        "origin": settings.app_base_url,
    }


@router.get("", response_class=HTMLResponse)
async def picker_page():
    return PICKER_HTML


# 아래 HTML/JS는 Synsory 프론트엔드가 그대로 참고하도록 주석을 달았다. 서버 의존은 /google/picker/config 하나다.
PICKER_HTML = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Google Picker 테스트 — synsory-api</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 860px; margin: 32px auto; padding: 0 16px; color: #222; }
  button { padding: 8px 14px; margin: 4px 6px 4px 0; cursor: pointer; }
  pre { background: #f5f5f5; padding: 12px; overflow: auto; font-size: 13px; }
  .ok { color: #137333; } .bad { color: #c5221f; } .muted { color: #666; }
  input[type=text] { width: 420px; padding: 6px; }
  fieldset { margin: 16px 0; }
</style>
</head>
<body>
<h1>Google Picker 테스트</h1>
<p class="muted">서버(<code>/auth/google/login</code>)에 로그인된 토큰으로 Picker를 띄운다. 고른 파일 ID로 서버가 <code>files.get</code>을 호출해 접근이 생겼는지 바로 확인한다.</p>

<fieldset>
  <legend>1. 설정 확인</legend>
  <pre id="config">불러오는 중…</pre>
</fieldset>

<fieldset>
  <legend>2. Picker 띄우기 (고를 종류)</legend>
  <button onclick="openPicker('documents')">Google Docs</button>
  <button onclick="openPicker('presentations')">Google Slides</button>
  <button onclick="openPicker('spreadsheets')">Google Sheets</button>
  <button onclick="openPicker('forms')">Google Forms</button>
  <button onclick="openPicker('folders')">폴더</button>
  <button onclick="openPicker('all')">Docs·Slides·Sheets 전부 (MIME 필터)</button>
  <br>
  <label><input type="checkbox" id="multi"> 여러 개 선택</label>
  <label><input type="checkbox" id="noKey"> API 키 없이 띄우기 (실험: setDeveloperKey 생략)</label>
  <label><input type="checkbox" id="noAppId"> appId 없이 띄우기 (실험: setAppId 생략 → 권한이 기록되지 않아야 함)</label>
  <label><input type="checkbox" id="navHidden"> 왼쪽 탐색 패널 숨김 (NAV_HIDDEN. 끄면 내 드라이브·공유 문서함·최근 항목을 오갈 수 있다)</label>
  <br>
  <input type="text" id="fileIds" placeholder="파일 ID로 바로 보여 주기 (쉼표 구분, DocsView.setFileIds)">
  <button onclick="openPicker('byId')">이 ID만 보여 주는 Picker</button>
</fieldset>

<fieldset>
  <legend>3. 결과</legend>
  <pre id="result">아직 고른 파일 없음</pre>
</fieldset>

<fieldset>
  <legend>4. 임의 ID로 서버 접근 확인 (Picker 전/후 비교)</legend>
  <input type="text" id="checkId" placeholder="Drive 파일 ID">
  <button onclick="checkAccess(document.getElementById('checkId').value)">files.get 호출</button>
  <pre id="check"></pre>
</fieldset>

<!-- (1) Picker 라이브러리. gapi를 올린 뒤 gapi.load('picker')로 Picker 모듈만 불러온다. -->
<script async defer src="https://apis.google.com/js/api.js" onload="gapi.load('picker', onPickerLoaded)"></script>
<!--
  (2) Synsory 프론트엔드에서 브라우저가 직접 토큰을 받으려면 GIS도 올린다. 이 테스트 페이지는 서버 토큰을 쓰므로 생략.
  <script async defer src="https://accounts.google.com/gsi/client"></script>
  const tokenClient = google.accounts.oauth2.initTokenClient({
    client_id: CLIENT_ID,                                     // 서버와 같은 GCP 프로젝트의 웹 클라이언트 ID (승인된 JavaScript 원본에 프론트 도메인 등록)
    scope: 'https://www.googleapis.com/auth/drive.file',      // Picker에는 drive.file만 있으면 된다
    callback: (resp) => openPickerWithToken(resp.access_token),
  });
  tokenClient.requestAccessToken({ prompt: '' });             // 이미 동의한 사용자는 팝업 없이 토큰이 온다
  주의: 이렇게 받은 토큰은 브라우저용(1시간)이고 refresh token이 없다. 서버는 자기 refresh token으로 계속 접근한다.
       파일 접근 권한은 토큰이 아니라 "프로젝트(appId) × 사용자 × 파일"에 기록되므로, Picker에 쓴 토큰과 서버 토큰이 달라도
       같은 프로젝트면 서버도 그 파일에 접근할 수 있어야 한다(2026-10 실측으로 확인, docs/google_drive.md 2.1절).
-->
<script>
let cfg = null;        // /google/picker/config 응답
let pickerReady = false;

function onPickerLoaded() { pickerReady = true; }

async function loadConfig() {
  const r = await fetch('/google/picker/config');
  if (!r.ok) {
    document.getElementById('config').textContent = '설정 실패 ' + r.status + ': ' + await r.text() + '\n→ /auth/google/login 으로 먼저 로그인';
    return;
  }
  cfg = await r.json();
  document.getElementById('config').textContent = JSON.stringify({
    api_key: cfg.api_key ? cfg.api_key.slice(0, 6) + '…' : '(비어 있음 → GOOGLE_PICKER_API_KEY)',
    app_id: cfg.app_id || '(비어 있음 → GOOGLE_PROJECT_NUMBER)',
    access_token: cfg.access_token ? '…' + cfg.access_token.slice(-6) : '(없음)',
    origin: cfg.origin,
  }, null, 2);
}
loadConfig();

// (3) 보기(View) 만들기. ViewId로 종류를 고르거나 DocsView(DOCS) + setMimeTypes로 MIME을 직접 제한한다.
//     setIncludeFolders(true): 폴더를 "탐색용"으로 보여 준다. setSelectFolderEnabled(true): 폴더 자체를 고를 수 있게 한다.
const MIME = {
  doc: 'application/vnd.google-apps.document',
  slides: 'application/vnd.google-apps.presentation',
  sheet: 'application/vnd.google-apps.spreadsheet',
  form: 'application/vnd.google-apps.form',
};
function buildView(kind) {
  const V = google.picker.ViewId;
  switch (kind) {
    case 'documents':     return new google.picker.DocsView(V.DOCUMENTS).setIncludeFolders(true);
    case 'presentations': return new google.picker.DocsView(V.PRESENTATIONS).setIncludeFolders(true);
    case 'spreadsheets':  return new google.picker.DocsView(V.SPREADSHEETS).setIncludeFolders(true);
    case 'forms':         return new google.picker.DocsView(V.FORMS).setIncludeFolders(true);
    case 'folders':       return new google.picker.DocsView(V.FOLDERS).setIncludeFolders(true).setSelectFolderEnabled(true);
    case 'byId':          // 특정 파일만 보여 준다. 사용자가 "어느 파일인지 아는데 목록에서 못 찾을 때"(다른 폴더·공유 문서함) 유용
      return new google.picker.DocsView(V.DOCS).setFileIds(document.getElementById('fileIds').value.replace(/\s/g, ''));
    default:              return new google.picker.DocsView(V.DOCS).setMimeTypes([MIME.doc, MIME.slides, MIME.sheet].join(',')).setIncludeFolders(true);
  }
}

// (4) Picker 띄우기. 세 가지가 모두 있어야 drive.file 앱에 파일 접근이 생긴다: developerKey, appId(프로젝트 번호), oauthToken.
function openPicker(kind) {
  if (!pickerReady || !cfg) { alert('아직 로딩 중'); return; }
  const b = new google.picker.PickerBuilder()
    .setOAuthToken(cfg.access_token)          // drive.file 토큰. 여러 계정 로그인 상태면 이 토큰의 계정 파일이 보인다
    .setOrigin(cfg.origin)                     // 페이지 origin. iframe 안에서 띄울 때 postMessage 대상 확인용
    .addView(buildView(kind))
    .setCallback(onPicked)
    .setTitle('템플릿으로 쓸 파일 고르기');
  if (!document.getElementById('noKey').checked)   b.setDeveloperKey(cfg.api_key);
  if (!document.getElementById('noAppId').checked) b.setAppId(cfg.app_id);   // drive.file이면 필수 (공식 레퍼런스)
  if (document.getElementById('multi').checked)    b.enableFeature(google.picker.Feature.MULTISELECT_ENABLED);
  if (document.getElementById('navHidden').checked) b.enableFeature(google.picker.Feature.NAV_HIDDEN);   // 보기 하나만 쓸 때 깔끔. 기본은 탐색 패널 표시
  b.build().setVisible(true);
}

// (5) 콜백. action: PICKED | CANCEL | ERROR(가 아니라 "loaded"도 온다). docs[]에 id·name·mimeType·url 등이 온다.
async function onPicked(data) {
  const out = document.getElementById('result');
  if (data.action === google.picker.Action.CANCEL) { out.textContent = '취소'; return; }
  if (data.action !== google.picker.Action.PICKED) { return; }   // 'loaded' 등은 무시
  // 참고: 공유받은 파일(소유자가 다른 사람)도 고를 수 있고 앱 접근이 생긴다(2026-10-04 실측). 소유자는 서버 files.get의 owners로 확인.
  const docs = data.docs.map(d => ({ id: d.id, name: d.name, mimeType: d.mimeType, url: d.url, parentId: d.parentId, isShared: d.isShared }));
  out.textContent = JSON.stringify(docs, null, 2) + '\n\n서버 접근 확인 중…';
  // 고른 직후 서버가 같은 파일을 볼 수 있는지 확인. 프론트엔드는 이 ID만 Synsory 서버에 넘기면 된다.
  const checks = [];
  for (const d of docs) checks.push(await serverCheck(d.id));
  out.textContent = JSON.stringify(docs, null, 2) + '\n\n--- 서버 files.get ---\n' + checks.join('\n');
}

async function serverCheck(id) {
  const r = await fetch('/google/drive/file-meta/' + encodeURIComponent(id));
  const body = await r.text();
  return (r.ok ? '[OK ' : '[FAIL ') + r.status + '] ' + id + ' → ' + body.slice(0, 300);
}

async function checkAccess(id) {
  if (!id) return;
  document.getElementById('check').textContent = await serverCheck(id.trim());
}
</script>
</body>
</html>
"""
