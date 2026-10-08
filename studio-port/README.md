# studio-port

synsory-api에서 검증한 연동 코드를 synsory-studio(TypeScript)로 이식하기 전에, studio와 같은 검사 기준으로 미리 작성하는 작업 폴더다. 여기서 `pnpm verify`를 통과한 `packages/` 아래 파일을 studio의 같은 경로로 복사하는 것이 목표다. 배치·형식·결정 필요 항목은 `../docs/STUDIO_PORTING.md`.

여기서 하는 것은 studio의 DB·팀·권한·큐에 닿지 않는 부분뿐이다: `infrastructure` 서비스 어댑터, `domain` 순수 함수, port 인터페이스 초안, `samples/` 기반 vitest 테스트. 연결 흐름·토큰 테이블·`ToolHandler` 등록·API 라우트·worker 작업은 studio 쪽 결정 뒤에 studio에서 한다.

## 기준

설정은 synsory-studio `255dde3`(2026-10-08 확인) 기준으로 복사했다. studio가 설정이나 의존성 버전을 바꾸면 여기도 다시 맞추고 이 줄을 고친다.

| 파일 | studio와의 차이 |
| --- | --- |
| `tsconfig.json` | `types`에서 `vite/client` 제거(웹 없음), `include`에서 `apps/**` 제거 |
| `scripts/check-boundaries.ts` | 검사 대상에서 `apps/web` 제거(폴더 없음) |
| `package.json` | studio 것에서 이 폴더에 필요한 의존성·스크립트만 남김. 버전은 같음 |
| `eslint.config.js`, `.prettierrc.json`, `.node-version`, `.npmrc`, `vitest.config.ts`, `scripts/boundary-rules.ts`, `scripts/files.ts`, `tests/unit/boundaries.test.ts`, `packages/*/package.json` | 그대로 복사 |

## 실행

Node 24.21.0, pnpm 10.34.6이 필요하다(studio가 `engine-strict`로 고정). nvm 기준:

```
nvm use 24.21.0
corepack enable            # pnpm 10.34.6을 package.json의 packageManager에서 받음
pnpm install
pnpm verify                # typecheck + lint + check:boundaries + test
```

## 구조

```
packages/
  domain/          # Synsory 규칙(집계, 출석 판정, payload 스키마). domain과 zod만 import
  application/     # port 인터페이스 초안. application·contracts·domain과 zod만 import
  contracts/       # 웹과 주고받는 DTO (필요할 때)
  infrastructure/  # Google·Zoom 어댑터(fetch), 외부 오류 분류
tests/
  unit/            # vitest. synsory-api pytest 케이스를 번역
  fixtures/        # synsory-api samples/*.json 사본, 가짜 port
```

`packages/domain/src/studio-stand-ins.ts`는 studio에 이미 있는 것(`AppError`)의 사본이다. 타입 검사용이고 이식할 때 복사하지 않는다. `scripts/live-*.ts`(실측)도 이식하지 않는다.

파일은 studio 관례대로 `src/` 아래 평평하게 두고 `index.ts`에서 `export *`로 내보낸다. import는 상대 경로 + `.ts` 확장자.

## 실측

`scripts/live-<service>.ts`는 실제 Google·Zoom을 호출해 어댑터를 확인한다. 만든 파일은 끝에 휴지통으로 보낸다. 토큰은 synsory-api 토큰 저장소(`../.tokens/tokens.json`, 필요하면 refresh)에서 받아 환경 변수로만 넘기고 출력하지 않는다. 먼저 synsory-api 서버로 Google 로그인이 되어 있어야 한다(`../CLAUDE.md` 실행).

```
cd ..   # synsory-api
TOKEN=$(uv run python -c 'import asyncio; from app.core.config import get_settings; from app.core.oauth import get_valid_token; from app.core.token_store import TokenStore; s=get_settings(); print(asyncio.run(get_valid_token("google", TokenStore(s.token_store_path), s)).access_token)')
cd studio-port
GOOGLE_ACCESS_TOKEN="$TOKEN" DRIVE_USER_FOLDER_ID=<앱이 못 보는 사용자 폴더 ID> DRIVE_SHARE_EMAIL=<공유 테스트 계정> pnpm exec tsx scripts/live-google-drive.ts
```

| 실측 | 날짜 | 결과 |
| --- | --- | --- |
| `live-google-drive.ts` | 2026-10-09 | 16/16 통과. Markdown 내보내기의 `_` 이스케이프를 새로 확인(`../docs/google_drive.md` 10절). CSV 변환 업로드의 학번 앞자리 0 소실은 Python 실측과 같음(`../docs/google_sheets.md` 10절 12항) |
