// studio packages/domain/src/index.ts에 이미 있는 것의 사본 (studio 255dde3).
// 여기서 타입 검사를 통과시키려고 둔다. studio로 이식할 때 이 파일은 복사하지 않는다.
export class AppError extends Error {
  constructor(
    public readonly code: string,
    public readonly status: number,
    message: string,
    public readonly details?: unknown,
  ) {
    super(message);
  }
}
