import { test } from "node:test";
import assert from "node:assert/strict";
import { exploreField } from "../src/api/client.ts";

test("stream decodes split UTF-8 and JSON lines, then requires a terminal result", async (t) => {
  const field = { name: "量子物理", core_papers: [], phase: "complete" };
  const bytes = new TextEncoder().encode(
    JSON.stringify({ type: "partial", stage: "papers", field }) +
      "\n" +
      JSON.stringify({ type: "complete", field }),
  );
  t.mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(
        new ReadableStream({
          start(controller) {
            for (let i = 0; i < bytes.length; i += 7)
              controller.enqueue(bytes.slice(i, i + 7));
            controller.close();
          },
        }),
      ),
  );
  const stages: string[] = [];
  const result = await exploreField("量子物理", "auto", false, (event) =>
    stages.push(event.type),
  );
  assert.equal(result.name, "量子物理");
  assert.deepEqual(stages, ["partial", "complete"]);
});

test("premature EOF and provider errors never become successful results", async (t) => {
  const mock = t.mock.method(
    globalThis,
    "fetch",
    async () => new Response('{"type":"status","stage":"search"}\n'),
  );
  await assert.rejects(exploreField("Test", "auto"), /分析未完成/);
  mock.mock.mockImplementation(
    async () =>
      new Response('{"type":"error","detail":"模型超时","status":504}\n'),
  );
  await assert.rejects(exploreField("Test", "auto"), /模型超时/);
});
