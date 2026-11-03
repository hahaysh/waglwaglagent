import assert from "node:assert/strict";
import test from "node:test";
import { consumeStream, errorMessage } from "../lib/api.ts";
import { boundedBody } from "../lib/request-body.ts";

function response(text, chunkSize = 1) {
  const bytes = new TextEncoder().encode(text);
  return new Response(new ReadableStream({
    start(controller) {
      for (let offset = 0; offset < bytes.length; offset += chunkSize) {
        controller.enqueue(bytes.slice(offset, offset + chunkSize));
      }
      controller.close();
    },
  }));
}

for (const newline of ["\n", "\r\n"]) {
  test(`SSE preserves split Korean UTF-8 and ${JSON.stringify(newline)}`, async () => {
    const events = [];
    const input = `event: delta${newline}data: {"text":"안녕하세요"}${newline}${newline}`
      + `event: done${newline}data: {"usage":{}}${newline}${newline}`;
    await consumeStream(response(input), (event, payload) => events.push([event, payload]));
    assert.deepEqual(events, [["delta", { text: "안녕하세요" }], ["done", { usage: {} }]]);
  });
}

test("Malformed JSON fails and releases reader", async () => {
  const input = response("event: delta\ndata: broken\n\n", 100);
  await assert.rejects(consumeStream(input, () => undefined), SyntaxError);
  assert.equal(input.body.locked, false);
});

test("Raw upstream failures are not displayed", () => {
  assert.equal(errorMessage("sk-private-provider-trace"), "요청을 완료하지 못했습니다. 연결 상태를 확인해주세요.");
});

test("Request body is byte-bounded even without Content-Length", async () => {
  const request = new Request("http://localhost", {
    method: "POST", body: response("안녕하세요", 1).body, duplex: "half",
  });
  assert.equal(await boundedBody(request, 15), "안녕하세요");
  const oversized = new Request("http://localhost", {
    method: "POST", body: response("안녕하세요", 1).body, duplex: "half",
  });
  await assert.rejects(boundedBody(oversized, 14), RangeError);
  assert.equal(oversized.body.locked, false);
});