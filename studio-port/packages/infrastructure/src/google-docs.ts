import type { GoogleDocsPort } from '../../application/src/index.ts';
import { externalRequest, readJson, type AccessToken, type HttpOptions } from './external-http.ts';
import { batchUpdateReplies, replaceAllTextRequests, tagCounts } from './google-tags.ts';

// Google Docs v1 어댑터. synsory-api app/services/google_docs/client.py + usecases.replace_tags의 이식본.
// 함정(인덱스는 UTF-16, create는 제목만, get은 includeTabsContent 필요)은 synsory-api docs/google_docs.md 10절.

const BASE_URL = 'https://docs.googleapis.com/v1';

export function createGoogleDocs(
  accessToken: AccessToken,
  options: HttpOptions = {},
): GoogleDocsPort {
  return {
    // documents.batchUpdate (쓰기 쿼터 1회). 원자적.
    async replaceTags(documentId, variables) {
      const response = await externalRequest(
        'google',
        await accessToken(),
        {
          method: 'POST',
          url: `${BASE_URL}/documents/${documentId}:batchUpdate`,
          json: { requests: replaceAllTextRequests(variables) },
        },
        options,
      );
      const { replies } = await readJson(response, batchUpdateReplies);
      return tagCounts(variables, replies, 'replaceAllText');
    },
  };
}
