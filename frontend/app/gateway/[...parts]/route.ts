import { createHmac, timingSafeEqual } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

const root = "/api/v1/sessions";
const sessionCookie = "claimassist_session";
const developerCookie = "claimassist_operator";
type Segment = { params: Promise<{ parts: string[] }> };

function same(left: string, right: string) {
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}

function parseSession(request: NextRequest) {
  const [id, token] = (request.cookies.get(sessionCookie)?.value || "").split(".");
  return /^[a-f0-9]{32}$/.test(id) && /^[\w-]{32,128}$/.test(token || "") ? { id, token } : null;
}

function error(status: number, code: string) {
  return NextResponse.json({ code }, { status, headers: { "Cache-Control": "no-store" } });
}

async function readJsonBody(request: NextRequest) {
  const reader = request.body?.getReader();
  if (!reader) return "";
  const decoder = new TextDecoder();
  let bytes = 0;
  let text = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) return text + decoder.decode();
      bytes += value.byteLength;
      if (bytes > 128 * 1024) {
        await reader.cancel();
        return null;
      }
      text += decoder.decode(value, { stream: true });
    }
  } finally {
    reader.releaseLock();
  }
}

async function handle(request: NextRequest, context: Segment) {
  const { parts } = await context.params;
  if (parts.length !== 1) return error(404, "not_found");
  const action = parts[0];
  const write = request.method === "POST";
  const host = request.headers.get("host");
  const origin = host ? request.nextUrl.protocol + "//" + host : request.nextUrl.origin;
  if (write && request.headers.get("origin") !== origin) {
    return error(403, "request_origin_invalid");
  }
  const hasBody = write && action !== "session";
  if (hasBody && request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") {
    return error(415, "unsupported_media_type");
  }
  const session = parseSession(request);
  const secure = request.nextUrl.protocol === "https:";
  const cookie = { httpOnly: true, sameSite: "strict" as const, secure, path: "/" };
  const key = process.env.DEMO_DIAGNOSTICS_KEY || "";
  const proof = key && session ? createHmac("sha256", key).update(session.token).digest("hex") : "";
  const authorizedDeveloper = proof && same(proof, request.cookies.get(developerCookie)?.value || "");

  if (action === "unlock" && write) {
    if (!session || !key) return error(404, "diagnostics_unavailable");
    const body = await readJsonBody(request);
    if (body === null) return error(413, "request_too_large");
    let data;
    try { data = JSON.parse(body); } catch { return error(422, "invalid_request"); }
    if (typeof data?.key !== "string" || !same(key, data.key)) return error(403, "diagnostics_unavailable");
    const result = NextResponse.json({ unlocked: true }, { headers: { "Cache-Control": "no-store" } });
    result.cookies.set(developerCookie, proof, cookie);
    return result;
  }

  const allowed = write ? ["session", "messages", "summary", "consent-demo"] : ["workspace", "events"];
  if (!allowed.includes(action)) return error(404, "not_found");
  if (action !== "session" && !session) return error(404, "session_unavailable");
  const diagnosticAction = ["events", "consent-demo"].includes(action);
  if (diagnosticAction && !authorizedDeveloper) return error(404, "diagnostics_unavailable");

  const path = action === "session" ? root : root + "/" + session!.id + "/" + action;
  const headers = new Headers({ Accept: "application/json" });
  if (session && action !== "session") headers.set("Authorization", "Bearer " + session.token);
  if (diagnosticAction) headers.set("X-Demo-Key", key);
  if (hasBody) headers.set("Content-Type", "application/json");

  try {
    const body = hasBody ? await readJsonBody(request) : undefined;
    if (body === null) return error(413, "request_too_large");
    const upstream = await fetch((process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "") + path, {
      method: request.method, headers, body,
      cache: "no-store", signal: AbortSignal.timeout(36000),
    });
    if (!upstream.ok) {
      const data = await upstream.json().catch(() => null);
      return error(upstream.status, typeof data?.code === "string" ? data.code : "backend_request_failed");
    }
    const data = await upstream.json();
    if (action === "session") {
      const { credential, ...safe } = data;
      if (!/^[a-f0-9]{32}$/.test(safe.session_id) || !/^[\w-]{32,128}$/.test(credential)) {
        return error(502, "invalid_response");
      }
      const result = NextResponse.json(safe, { status: 201, headers: { "Cache-Control": "no-store" } });
      result.cookies.set(sessionCookie, safe.session_id + "." + credential, cookie);
      result.cookies.delete(developerCookie);
      return result;
    }
    return NextResponse.json(data, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return error(503, "backend_unavailable");
  }
}

export const GET = handle;
export const POST = handle;
