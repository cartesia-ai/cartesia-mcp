import assert from "node:assert/strict";
import test from "node:test";

import { canBuildCurl, curlSnippet } from "./request.js";

const payload = {
  file_id: "file_6XrMuLfiWNd4gDus9BbpQy",
  transcript: "I'd like a table for two.",
  voice_id: "a0e99841-438c-4a64-b679-ae501e7d6091",
  model_id: "sonic-latest",
  language: "fr",
  emotion: "calm",
  speed: 1.3,
  volume: 2,
  pronunciation_dict_id: "pd_123",
  cartesia_version: "2026-08-14",
  output_format: { container: "mp3", sample_rate: 44100, bit_rate: 128000 },
};

test("curl carries everything the request used, not defaults", () => {
  const curl = curlSnippet(payload);
  assert.match(curl, /-H "Cartesia-Version: 2026-08-14"/);
  assert.match(curl, /"model_id":"sonic-latest"/);
  assert.match(curl, /"language":"fr"/);
  assert.match(
    curl,
    /"generation_config":\{"speed":1\.3,"volume":2,"emotion":"calm"\}/,
  );
  assert.match(curl, /"pronunciation_dict_id":"pd_123"/);
  assert.match(curl, /-o cartesia-sonic-latest-9bbpqy\.mp3$/);
});

test("apostrophes in the transcript survive shell quoting", () => {
  assert.ok(curlSnippet(payload).includes(`I'\\''d like a table for two.`));
});

test("curl is unavailable when the result lacks the request fields", () => {
  assert.equal(canBuildCurl(payload), true);
  const { cartesia_version: _omitted, ...withoutVersion } = payload;
  assert.equal(canBuildCurl(withoutVersion), false);
});
