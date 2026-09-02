import { list } from '@vercel/blob';
import { createHmac, timingSafeEqual } from 'node:crypto';

export const LATEST_PATH = 'smartfarm/latest.json';

export function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store, max-age=0',
      ...headers,
    },
  });
}

export function requireIngestSignature(request, rawBody) {
  const secret = process.env.SMARTFARM_PUBLIC_SYNC_SECRET;
  const timestamp = request.headers.get('x-smartfarm-timestamp') || '';
  const signature = request.headers.get('x-smartfarm-signature') || '';
  if (!secret) return 'server sync secret is not configured';
  if (!/^\d{10,13}$/.test(timestamp)) return 'invalid timestamp';
  const timestampMs = Number(timestamp.length === 10 ? `${timestamp}000` : timestamp);
  if (Math.abs(Date.now() - timestampMs) > 5 * 60 * 1000) return 'expired timestamp';
  const expected = createHmac('sha256', secret)
    .update(`${timestamp}.`)
    .update(rawBody)
    .digest('hex');
  const provided = Buffer.from(signature, 'hex');
  const expectedBuffer = Buffer.from(expected, 'hex');
  if (provided.length !== expectedBuffer.length || !timingSafeEqual(provided, expectedBuffer)) {
    return 'invalid signature';
  }
  return null;
}

export async function loadLatestSnapshot() {
  const { blobs } = await list({ prefix: LATEST_PATH, limit: 10 });
  const blob = blobs.find((item) => item.pathname === LATEST_PATH);
  if (!blob) return null;
  const response = await fetch(blob.url, { cache: 'no-store' });
  if (!response.ok) throw new Error('latest snapshot could not be read');
  return response.json();
}

export function safeImageName(value) {
  return String(value || '').replace(/[^A-Za-z0-9_-]/g, '').slice(0, 32);
}
