import { App } from "@modelcontextprotocol/ext-apps/app-with-deps";

import { audioMimeType, canBuildCurl, curlSnippet, outputFilename } from "./request.js";

const BAR_COUNT = 110;
const BAR_GAP = 2;
const FLAT_PEAK = 0.1;
const PLAY_PATH = "M9 6.5v11l9-5.5-9-5.5z";
const PAUSE_PATH = "M7 5.5h3.2v13H7v-13zm6.8 0H17v13h-3.2v-13z";

const byId = (id) => document.getElementById(id);
const els = {
  playBtn: byId("playBtn"),
  playGlyph: byId("playGlyph"),
  transcript: byId("transcript"),
  sub: byId("sub"),
  waveBlock: byId("waveBlock"),
  wave: byId("wave"),
  bars: byId("bars"),
  playhead: byId("playhead"),
  timeCurrent: byId("timeCurrent"),
  timeTotal: byId("timeTotal"),
  note: byId("note"),
  copyCurl: byId("copyCurl"),
  downloadBtn: byId("downloadBtn"),
};

/** The latest `text_to_speech` result. @type {Record<string, any>} */
let current = {};
let hostCapabilities = {};
const audio = new Audio();
audio.preload = "auto";

/** @type {number[]} */
let peaks = Array.from({ length: BAR_COUNT }, () => FLAT_PEAK);
let duration = 0;
let progress = 0;
let raf = 0;
let scrubbing = false;
let laidOutWidth = 0;

function formatTime(sec) {
  if (!Number.isFinite(sec) || sec < 0) return "0:00";
  return `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;
}

function sampleRateLabel() {
  const rate = Number(current.output_format?.sample_rate || 44100);
  return `${(rate / 1000).toFixed(1)} kHz`;
}

function renderSub() {
  const parts = [current.voice_name || "Voice"];
  if (current.voice_tagline) parts.push(current.voice_tagline);
  parts.push(sampleRateLabel());
  let line = parts.join(" - ");
  if (current.voice_featured) line += " [Featured]";
  els.sub.textContent = line;
}

function setNote(text) {
  els.note.textContent = text ?? "";
  els.note.hidden = !text;
}

function setGlyph(playing) {
  els.playGlyph.querySelector("path").setAttribute("d", playing ? PAUSE_PATH : PLAY_PATH);
  els.playBtn.classList.toggle("is-playing", playing);
  els.playBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
}

function layoutBars() {
  const width = els.wave.clientWidth || 0;
  if (!width || width === laidOutWidth || !els.bars.children.length) return;
  laidOutWidth = width;
  const barWidth = Math.max(1, (width - BAR_GAP * (BAR_COUNT - 1)) / BAR_COUNT);
  const nodes = els.bars.children;
  for (let i = 0; i < nodes.length; i++) {
    nodes[i].style.width = `${barWidth}px`;
    nodes[i].style.marginRight = i === nodes.length - 1 ? "0" : `${BAR_GAP}px`;
  }
}

function paint(p) {
  progress = Math.min(1, Math.max(0, p || 0));
  const nodes = els.bars.children;
  for (let i = 0; i < nodes.length; i++) {
    nodes[i].classList.toggle("played", (i + 0.5) / BAR_COUNT <= progress);
  }
  layoutBars();
  const width = els.wave.clientWidth || 0;
  els.playhead.style.transform = `translateX(${progress * Math.max(0, width - 2)}px)`;
  els.timeCurrent.textContent = formatTime(duration * progress);
  els.timeTotal.textContent = formatTime(duration);
  els.wave.setAttribute("aria-valuenow", String(Math.round(progress * 100)));
}

function renderBars() {
  const frag = document.createDocumentFragment();
  for (let i = 0; i < BAR_COUNT; i++) {
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.style.height = `${3 + peaks[i] * 25}px`;
    frag.appendChild(bar);
  }
  els.bars.replaceChildren(frag);
  laidOutWidth = 0;
  paint(progress);
}

function stopRaf() {
  if (raf) cancelAnimationFrame(raf);
  raf = 0;
}

function tick() {
  if (!scrubbing && duration > 0 && !audio.paused) paint(audio.currentTime / duration);
  raf = audio.paused ? 0 : requestAnimationFrame(tick);
}

function startRaf() {
  stopRaf();
  raf = requestAnimationFrame(tick);
}

async function buildPeaks(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const ctx = new AudioContext();
    const decoded = await ctx.decodeAudioData(await res.arrayBuffer());
    const channel = decoded.getChannelData(0);
    const block = Math.max(1, Math.floor(channel.length / BAR_COUNT));
    const next = [];
    for (let i = 0; i < BAR_COUNT; i++) {
      let peak = 0;
      const end = Math.min(channel.length, (i + 1) * block);
      for (let j = i * block; j < end; j++) peak = Math.max(peak, Math.abs(channel[j]));
      next.push(peak);
    }
    const max = Math.max(...next, 0.001);
    peaks = next.map((v) => v / max);
    if (Number.isFinite(decoded.duration) && decoded.duration > 0) duration = decoded.duration;
    await ctx.close();
  } catch {
    // A flat row says "no waveform", where a fake one would look real.
    peaks = Array.from({ length: BAR_COUNT }, () => FLAT_PEAK);
    setNote("Waveform unavailable");
  }
  progress = 0;
  renderBars();
}

function seekFromClientX(clientX) {
  const rect = els.wave.getBoundingClientRect();
  if (!rect.width || !duration) return;
  const p = Math.min(Math.max(0, clientX - rect.left), rect.width) / rect.width;
  audio.currentTime = p * duration;
  paint(p);
}

function flash(button, ok = true) {
  const cls = ok ? "flash" : "flash-error";
  button.classList.add(cls);
  window.setTimeout(() => button.classList.remove(cls), 450);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Some sandboxes block the async clipboard API but still allow a user-gesture copy.
    const field = document.createElement("textarea");
    field.value = text;
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    return copied;
  }
}

async function download() {
  const url = current.download_url;
  if (typeof url !== "string") return;
  try {
    let result;
    if (hostCapabilities.downloadFile) {
      result = await app.downloadFile({
        contents: [
          {
            type: "resource_link",
            uri: url,
            name: outputFilename(current),
            mimeType: audioMimeType(current.output_format?.container),
          },
        ],
      });
    } else if (hostCapabilities.openLinks) {
      result = await app.openLink({ url });
    } else {
      return;
    }
    flash(els.downloadBtn, !result?.isError);
  } catch {
    flash(els.downloadBtn, false);
  }
}

/** Show only the controls this result and host can actually serve. */
function refreshControls() {
  els.copyCurl.hidden = !canBuildCurl(current);
  els.downloadBtn.hidden =
    typeof current.download_url !== "string" ||
    !(hostCapabilities.downloadFile || hostCapabilities.openLinks);
}

async function resolveVoice(voiceId) {
  try {
    const result = await app.callServerTool({
      name: "get_voice",
      arguments: { voice_id: voiceId },
    });
    let voice = result?.structuredContent?.voice ?? result?.structuredContent;
    if (!voice?.name) {
      const text = result?.content?.find?.((c) => c.type === "text")?.text;
      voice = typeof text === "string" ? JSON.parse(text) : null;
    }
    if (typeof voice?.name === "string" && voice.name.trim()) {
      current.voice_name = voice.name.trim().split("\n")[0].slice(0, 48);
      current.voice_tagline = typeof voice.tagline === "string" ? voice.tagline.trim().slice(0, 48) : "";
      current.voice_featured = voice.is_featured === true;
      renderSub();
    }
  } catch {
    /* keep the generic label */
  }
}

function applyPayload(payload) {
  if (!payload || typeof payload !== "object") return;
  stopRaf();
  audio.pause();
  setGlyph(false);
  setNote("");
  current = { ...payload };

  const transcript = payload.transcript || "";
  els.transcript.textContent = transcript || "(no transcript)";
  els.transcript.title = transcript;
  els.transcript.classList.remove("open");
  current.voice_name = "Voice";
  renderSub();
  if (payload.voice_id) resolveVoice(payload.voice_id);

  duration = 0;
  progress = 0;
  peaks = Array.from({ length: BAR_COUNT }, () => FLAT_PEAK);
  renderBars();
  refreshControls();

  const url = payload.download_url;
  const playable = typeof url === "string" && url.startsWith("https://");
  els.waveBlock.hidden = !playable;
  els.playBtn.disabled = !playable;
  if (playable) {
    audio.src = url;
    buildPeaks(url);
  } else {
    audio.removeAttribute("src");
    setNote(payload.file_path ? `Saved to ${payload.file_path}, no preview` : "No preview available");
  }
}

function extractPayload(params) {
  if (params?.structuredContent && typeof params.structuredContent === "object") {
    return params.structuredContent;
  }
  const text = params?.content?.find?.((c) => c.type === "text")?.text;
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return null;
  }
}

els.playBtn.addEventListener("click", async () => {
  if (!audio.src) return;
  if (audio.paused) {
    try {
      await audio.play();
    } catch {
      /* needs a user gesture; the next click retries */
    }
  } else audio.pause();
});

audio.addEventListener("play", () => {
  setGlyph(true);
  startRaf();
});
audio.addEventListener("pause", () => {
  setGlyph(false);
  stopRaf();
  if (duration > 0) paint(audio.currentTime / duration);
});
audio.addEventListener("ended", () => {
  setGlyph(false);
  stopRaf();
  paint(1);
});
audio.addEventListener("loadedmetadata", () => {
  if (Number.isFinite(audio.duration) && audio.duration > 0) {
    duration = audio.duration;
    paint(audio.currentTime / duration || 0);
  }
});
audio.addEventListener("error", () => {
  if (!audio.getAttribute("src")) return;
  els.playBtn.disabled = true;
  setNote("Couldn't load the audio");
});

els.wave.addEventListener("pointerdown", (e) => {
  scrubbing = true;
  els.wave.setPointerCapture(e.pointerId);
  seekFromClientX(e.clientX);
});
els.wave.addEventListener("pointermove", (e) => {
  if (scrubbing) seekFromClientX(e.clientX);
});
els.wave.addEventListener("pointerup", (e) => {
  if (!scrubbing) return;
  seekFromClientX(e.clientX);
  scrubbing = false;
  try {
    els.wave.releasePointerCapture(e.pointerId);
  } catch {
    /* already released */
  }
});
els.wave.addEventListener("pointercancel", () => {
  scrubbing = false;
});

els.transcript.addEventListener("click", () => {
  els.transcript.classList.toggle("open");
});

els.copyCurl.addEventListener("click", async () => {
  flash(els.copyCurl, await copyText(curlSnippet(current)));
});

els.downloadBtn.addEventListener("click", download);

renderBars();
new ResizeObserver(() => {
  laidOutWidth = 0;
  paint(progress);
}).observe(els.wave);

const app = new App({ name: "Cartesia TTS Player", version: "1.0.0" });
app.ontoolresult = (params) => {
  if (!params?.isError) applyPayload(extractPayload(params));
};
await app.connect();
hostCapabilities = app.getHostCapabilities() ?? {};
refreshControls();
