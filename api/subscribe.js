// Vercel serverless function: stores email signups in Upstash Redis.
//
// Setup (one-time, in the Vercel dashboard):
//   Storage → Marketplace → Upstash Redis → Add Integration → connect to this project
//   This auto-injects UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN env vars
//   on the next deploy. No code changes needed.
//
// Reading the list later:
//   curl -H "Authorization: Bearer $UPSTASH_REDIS_REST_TOKEN" \
//        $UPSTASH_REDIS_REST_URL/smembers/alienlist:emails
//
// Cost: free up to 10k commands/day on Upstash free tier — easily covers
// any realistic launch wave.

export const config = { runtime: 'edge' };

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

// Naive in-memory rate limit (per edge instance). Good enough for pre-spam
// scenarios; for serious abuse switch to Upstash Ratelimit.
const recentByIp = new Map();
const RATE_WINDOW_MS = 60_000;
const MAX_PER_WINDOW = 5;

function rateLimited(ip) {
  const now = Date.now();
  const arr = (recentByIp.get(ip) || []).filter(t => now - t < RATE_WINDOW_MS);
  if (arr.length >= MAX_PER_WINDOW) return true;
  arr.push(now);
  recentByIp.set(ip, arr);
  return false;
}

async function upstash(path, body) {
  // Accepts either Upstash-native env vars or Vercel KV's (same Upstash Redis
  // under the hood, just renamed). Whichever the integration injected.
  const url = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;
  if (!url || !token) throw new Error('Redis env vars not configured');
  const res = await fetch(`${url}/${path}`, {
    method: body ? 'POST' : 'GET',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: body ? JSON.stringify(body) : undefined
  });
  if (!res.ok) throw new Error(`Upstash ${path} → ${res.status}`);
  return res.json();
}

export default async function handler(req) {
  if (req.method !== 'POST') {
    return new Response('Method not allowed', { status: 405 });
  }
  const ip = req.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || 'unknown';
  if (rateLimited(ip)) {
    return new Response(JSON.stringify({ error: 'rate_limited' }), {
      status: 429, headers: { 'Content-Type': 'application/json' }
    });
  }

  let body;
  try { body = await req.json(); } catch { return badRequest('invalid_json'); }
  const email = String(body?.email || '').trim().toLowerCase();
  if (!email || !EMAIL_RE.test(email) || email.length > 254) return badRequest('invalid_email');

  // SADD into a deduped set; ZADD timestamp for analytics
  try {
    await upstash(`sadd/alienlist:emails/${encodeURIComponent(email)}`);
    const ts = Date.now();
    await upstash(`zadd/alienlist:emails:by_time/${ts}/${encodeURIComponent(email)}`);
    const sizeRes = await upstash('scard/alienlist:emails');
    const total = sizeRes.result || 0;
    return new Response(JSON.stringify({ ok: true, total }), {
      status: 200, headers: { 'Content-Type': 'application/json' }
    });
  } catch (e) {
    console.error('subscribe error', e);
    return new Response(JSON.stringify({ error: 'storage_unavailable' }), {
      status: 500, headers: { 'Content-Type': 'application/json' }
    });
  }
}

function badRequest(code) {
  return new Response(JSON.stringify({ error: code }), {
    status: 400, headers: { 'Content-Type': 'application/json' }
  });
}
