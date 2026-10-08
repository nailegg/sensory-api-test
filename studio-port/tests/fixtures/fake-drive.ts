import type { GoogleDrivePort } from '../../packages/application/src/index.ts';
import { AppError } from '../../packages/domain/src/index.ts';

// 흐름 테스트용 GoogleDrivePort. 테스트가 넘긴 메서드만 동작하고 나머지는 부르면 실패한다.
export function fakeDrive(methods: Partial<GoogleDrivePort>): GoogleDrivePort {
  return new Proxy(methods as GoogleDrivePort, {
    get(target, name: string) {
      const method = target[name as keyof GoogleDrivePort];
      if (!method) throw new Error(`fakeDrive.${name}가 준비되지 않았습니다.`);
      return method;
    },
  });
}

export const notFound = () => new AppError('EXTERNAL_NOT_FOUND', 404, '파일을 찾을 수 없습니다.');
