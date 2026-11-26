/**
 * Rebuilds the `POST /tts/bytes` request from the fields `text_to_speech`
 * returns to MCP Apps clients, so the copied curl reproduces the clip.
 */

const MIME_TYPES = { mp3: "audio/mpeg", wav: "audio/wav" };

/** @param {string} container */
export function audioMimeType(container) {
  return MIME_TYPES[container] ?? "application/octet-stream";
}

/** @param {unknown} value */
export function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'\\''`)}'`;
}

/**
 * True when the result carries every field the request needs. Without them
 * the snippet would silently diverge from the real clip, so the button hides.
 * @param {Record<string, any>} payload
 */
export function canBuildCurl(payload) {
  const format = payload.output_format;
  return Boolean(
    payload.transcript &&
      payload.voice_id &&
      payload.model_id &&
      payload.cartesia_version &&
      format?.container &&
      format?.sample_rate,
  );
}

/** @param {Record<string, any>} payload */
export function outputFilename(payload) {
  const slug = String(payload.file_id || "clip")
    .replace(/^file_/, "")
    .slice(-6)
    .toLowerCase();
  const ext = String(payload.output_format?.container || "wav").replace(/[^a-z0-9]/gi, "");
  return `cartesia-${payload.model_id || "sonic"}-${slug}.${ext || "wav"}`;
}

/** @param {Record<string, any>} payload */
export function curlSnippet(payload) {
  const fmt = payload.output_format;
  const output_format = { container: fmt.container };
  if (fmt.encoding) output_format.encoding = fmt.encoding;
  output_format.sample_rate = fmt.sample_rate;
  if (fmt.bit_rate) output_format.bit_rate = fmt.bit_rate;

  const body = {
    model_id: payload.model_id,
    transcript: payload.transcript,
    voice: payload.voice_id,
  };
  if (payload.language) body.language = payload.language;
  body.output_format = output_format;

  const generation_config = {};
  for (const key of ["speed", "volume", "emotion"]) {
    if (payload[key] != null) generation_config[key] = payload[key];
  }
  if (Object.keys(generation_config).length) body.generation_config = generation_config;
  if (payload.pronunciation_dict_id) body.pronunciation_dict_id = payload.pronunciation_dict_id;
  if (payload.duration != null) body.duration = payload.duration;

  return [
    "curl -s -X POST https://api.cartesia.ai/tts/bytes \\",
    `-H "Cartesia-Version: ${payload.cartesia_version}" \\`,
    '-H "X-API-Key: $CARTESIA_API_KEY" \\',
    '-H "Content-Type: application/json" \\',
    `-d ${shellQuote(JSON.stringify(body))} \\`,
    `-o ${outputFilename(payload)}`,
  ].join("\n");
}
