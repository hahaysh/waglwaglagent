import { createServer } from "node:http";
import { jwtVerify } from "jose";

const secret = new TextEncoder().encode("test-internal-secret-only-not-for-production");
const sessions = new Map();
const server = createServer(async (request, response) => {
  response.setHeader("Content-Type", "application/json");
  if (request.url === "/health") return response.end('{"status":"ok"}');
  if (request.url === "/fixture/session" && request.method === "POST") {
    let body = "";
    for await (const chunk of request) body += chunk;
    const fixture = JSON.parse(body);
    sessions.set(fixture.session_id, fixture);
    return response.end('{"status":"ok"}');
  }
  try {
    const { payload } = await jwtVerify((request.headers.authorization || "").slice(7), secret, {
      algorithms: ["HS256"], audience: "wagl-api", issuer: "wagl-web",
    });
    const fixture = sessions.get(payload.sid);
    if (!fixture || `user:${fixture.user_id}` !== payload.sub
      || Date.parse(fixture.expires_at) <= Date.now()) throw new Error("unknown session");
    if (fixture.unavailable) {
      response.statusCode = 503;
      return response.end('{"detail":"account_store_unavailable"}');
    }
    if (request.url === "/auth/session") return response.end(JSON.stringify(fixture));
    if (request.url === "/auth/logout" && request.method === "POST") {
      sessions.delete(payload.sid);
      return response.end('{"status":"signed_out"}');
    }
    if (request.url === "/connections/copilot/start" && request.method === "POST") {
      let body = "";
      for await (const chunk of request) body += chunk;
      const consent = JSON.parse(body);
      if (consent.approved !== true || typeof consent.binding !== "string" || consent.binding.length < 32) {
        response.statusCode = 422;
        return response.end('{"detail":"Invalid input"}');
      }
      return response.end(JSON.stringify({
        authorization_url: "https://github.com/login/oauth/authorize?state=test-state-012345678901234567890123456789",
      }));
    }
    response.statusCode = 404;
    response.end("{}");
  } catch {
    response.statusCode = 401;
    response.end('{"detail":"Session expired"}');
  }
});
server.listen(3199, "127.0.0.1");
