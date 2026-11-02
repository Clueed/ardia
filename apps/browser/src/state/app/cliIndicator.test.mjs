import assert from "node:assert/strict";
import { test } from "node:test";
const { useCli, useCliIndicator, noteGatewayActive } = await import("./cliControl.ts");

const shown = () => useCliIndicator.getState().shown;
const server = (state, connections) => useCli.setState({ server: { state, connections, generation: 1, file: "" } });

test("the engine's own connections never show the pill; gateway activity does, and it lingers 3 s", async () => {
  noteGatewayActive(false);
  useCliIndicator.setState({ shown: false });
  server("on", 2);
  assert.equal(shown(), false, "the gateway's upstream and monitor sockets don't count");
  noteGatewayActive(true);
  assert.equal(shown(), true);
  noteGatewayActive(false);
  assert.equal(shown(), true, "it stays a moment after the last activity");
  await new Promise((resolve) => setTimeout(resolve, 3200));
  assert.equal(shown(), false);
});

test("turning control off hides the pill at once", () => {
  server("on", 1);
  noteGatewayActive(true);
  assert.equal(shown(), true);
  server("off", 0);
  assert.equal(shown(), false);
  noteGatewayActive(false);
});
