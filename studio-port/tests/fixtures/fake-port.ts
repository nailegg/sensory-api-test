import { AppError } from '../../packages/domain/src/index.ts';

// 흐름 테스트용 port. 테스트가 넘긴 메서드만 동작하고 나머지는 부르면 실패한다.
export function fakePort<T extends object>(methods: Partial<T>): T {
  return new Proxy(methods as T, {
    get(target, name: string) {
      const method = target[name as keyof T];
      if (!method) throw new Error(`fake port의 ${name}가 준비되지 않았습니다.`);
      return method;
    },
  });
}

export const notFound = () => new AppError('EXTERNAL_NOT_FOUND', 404, '파일을 찾을 수 없습니다.');
