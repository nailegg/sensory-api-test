import type { GoogleSlidesPort } from '../../application/src/index.ts';
import { externalRequest, readJson, type AccessToken, type HttpOptions } from './external-http.ts';
import { batchUpdateReplies, replaceAllTextRequests, tagCounts } from './google-tags.ts';

// Google Slides v1 어댑터. synsory-api app/services/google_slides/client.py + usecases.replace_tags의 이식본.
// 텍스트를 바꾸면 도형의 autofit이 꺼져 긴 치환 텍스트가 넘친다(synsory-api docs/google_slides.md 10절).

const BASE_URL = 'https://slides.googleapis.com/v1';

export function createGoogleSlides(
  accessToken: AccessToken,
  options: HttpOptions = {},
): GoogleSlidesPort {
  return {
    // presentations.batchUpdate (쓰기 쿼터 1회). 원자적.
    async replaceTags(presentationId, variables) {
      const response = await externalRequest(
        'google',
        await accessToken(),
        {
          method: 'POST',
          url: `${BASE_URL}/presentations/${presentationId}:batchUpdate`,
          json: { requests: replaceAllTextRequests(variables) },
        },
        options,
      );
      const { replies } = await readJson(response, batchUpdateReplies);
      return tagCounts(variables, replies, 'replaceAllText');
    },
  };
}
