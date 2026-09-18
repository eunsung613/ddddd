import { json, loadLatestSnapshot } from './_shared.mjs';

export async function GET(request) {
  if (request.method !== 'GET') return json({ error: 'method_not_allowed' }, 405, { allow: 'GET' });
  try {
    const snapshot = await loadLatestSnapshot();
    if (!snapshot) return json({ status: 'waiting_for_school_server' }, 404);
    return json(snapshot);
  } catch {
    return json({ error: 'overview_unavailable' }, 503);
  }
}
