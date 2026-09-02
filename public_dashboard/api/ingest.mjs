import { put } from '@vercel/blob';
import { LATEST_PATH, json, loadLatestSnapshot, requireIngestSignature, safeImageName } from './_shared.mjs';

const MAX_REQUEST_BYTES = 4 * 1024 * 1024;
const MAX_IMAGE_BYTES = 1200 * 1024;

export async function POST(request) {
  if (request.method !== 'POST') return json({ error: 'method_not_allowed' }, 405, { allow: 'POST' });
  const rawBody = Buffer.from(await request.arrayBuffer());
  if (rawBody.length === 0 || rawBody.length > MAX_REQUEST_BYTES) return json({ error: 'invalid_body_size' }, 413);
  const authError = requireIngestSignature(request, rawBody);
  if (authError) return json({ error: 'unauthorized' }, 401);

  let payload;
  try {
    payload = JSON.parse(rawBody.toString('utf8'));
  } catch {
    return json({ error: 'invalid_json' }, 400);
  }
  if (payload?.schema_version !== 1 || !payload.snapshot || typeof payload.snapshot !== 'object') {
    return json({ error: 'invalid_snapshot' }, 400);
  }

  let previous = null;
  try {
    previous = await loadLatestSnapshot();
  } catch {
    // A first upload has no prior snapshot. A later upload can replace it.
  }
  const uploadedImages = [];
  for (const image of Array.isArray(payload.images) ? payload.images.slice(0, 3) : []) {
    const cameraId = safeImageName(image?.camera_id);
    const capturedAt = safeImageName(image?.captured_at);
    const base64 = typeof image?.base64 === 'string' ? image.base64 : '';
    if (!cameraId || !capturedAt || !base64) continue;
    let binary;
    try {
      binary = Buffer.from(base64, 'base64');
    } catch {
      continue;
    }
    if (!binary.length || binary.length > MAX_IMAGE_BYTES) continue;
    const blob = await put(`smartfarm/cameras/${cameraId}-${capturedAt}.jpg`, binary, {
      access: 'public',
      addRandomSuffix: true,
      contentType: 'image/jpeg',
      cacheControlMaxAge: 31536000,
    });
    uploadedImages.push({
      camera_id: cameraId,
      captured_at: String(image.captured_at).slice(0, 32),
      url: blob.url,
    });
  }

  const snapshot = {
    schema_version: 1,
    synced_at: new Date().toISOString(),
    ...payload.snapshot,
    images: uploadedImages.length ? uploadedImages : (Array.isArray(previous?.images) ? previous.images : []),
  };
  await put(LATEST_PATH, JSON.stringify(snapshot), {
    access: 'public',
    allowOverwrite: true,
    contentType: 'application/json',
    cacheControlMaxAge: 60,
  });
  return json({ ok: true, images_uploaded: uploadedImages.length, synced_at: snapshot.synced_at });
}
