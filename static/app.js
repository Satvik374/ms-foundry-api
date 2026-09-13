const state = {
  config: null,
  providerKey: "",
  keyVisible: false,
  language: "python",
  lastCode: "",
  attachedImage: null,
  playgroundMode: "chat",
  chatDraft: "Tell me what you can help with.",
  ttsDraft: "Hello, welcome to Azure AI Foundry! Text to speech is fast, expressive, and natural.",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 1800);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    showToast("Copied to clipboard");
  } catch {
    showToast("Clipboard access was blocked");
  }
}

function compactEndpoint(endpoint) {
  try {
    const url = new URL(endpoint);
    return `${url.host}${url.pathname}`;
  } catch {
    return endpoint;
  }
}

function maskedKey() {
  if (!state.providerKey) return "frly_••••••••••••••••••••••••";
  const prefix = state.providerKey.slice(0, Math.min(7, state.providerKey.length));
  return `${prefix}${"•".repeat(Math.max(18, state.providerKey.length - prefix.length))}`;
}

function renderKey() {
  $("#api-key").textContent = state.keyVisible ? state.providerKey : maskedKey();
  $("#visibility-button").textContent = state.keyVisible ? "◉" : "◎";
  $("#visibility-button").setAttribute("aria-label", state.keyVisible ? "Hide API key" : "Show API key");
}

function codeSamples() {
  const baseUrl = state.config?.baseUrl || `${window.location.origin}/v1`;
  const model = state.config?.modelId || "jarvis-2";
  const key = state.providerKey || "YOUR_PROVIDER_API_KEY";

  return {
    python: `from openai import OpenAI

client = OpenAI(
    api_key="${key}",
    base_url="${baseUrl}",
)

stream = client.responses.create(
    model="${model}",
    input="Tell me what you can help with.",
    stream=True,
)

for event in stream:
    if event.type == "response.output_text.delta":
        print(event.delta, end="", flush=True)`,
    javascript: `import OpenAI from "openai";

const client = new OpenAI({
  apiKey: "${key}",
  baseURL: "${baseUrl}",
});

const stream = await client.responses.create({
  model: "${model}",
  input: "Tell me what you can help with.",
  stream: true,
});

for await (const event of stream) {
  if (event.type === "response.output_text.delta") {
    process.stdout.write(event.delta);
  }
}`,
    curl: `curl -N "${baseUrl}/responses" \\
  -H "Authorization: Bearer ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${model}",
    "input": "Tell me what you can help with.",
    "stream": true
  }'`,
    speech: `from openai import OpenAI

client = OpenAI(
    api_key="${key}",
    base_url="${baseUrl}",
)

# Synthesize speech using OpenAI-compatible audio API
response = client.audio.speech.create(
    model="tts-1",
    voice="onyx",  # onyx, alloy, echo, fable, nova, shimmer
    input="Hello! Welcome to Azure AI Foundry.",
)

# Save the speech output
response.stream_to_file("speech.mp3")`,
    voice: `import asyncio
import json
import websockets

async def real_time_voice_demo():
    # Connect directly to Foundry Relay OpenAI-compatible Realtime WebSocket endpoint
    uri = "ws://localhost:8000/v1/realtime?api_key=${key}&voice=en-US-Ava:DragonHDLatestNeural"

    async with websockets.connect(uri) as ws:
        # 1. Update session configuration (optional)
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "voice": "en-US-Ava:DragonHDLatestNeural",
                "instructions": "You are a fast, engaging voice assistant."
            }
        }))

        # 2. Receive and handle server audio events
        async for raw_message in ws:
            event = json.loads(raw_message)
            event_type = event.get("type")

            if event_type == "response.audio.delta":
                # Raw PCM16 24kHz audio chunk (base64 encoded)
                audio_chunk_b64 = event["delta"]
            elif event_type == "input_audio_buffer.speech_started":
                print("🎤 User spoke: barge-in detected, interrupting agent audio")
            elif event_type == "response.audio_transcript.delta":
                print(event.get("delta", ""), end="", flush=True)

asyncio.run(real_time_voice_demo())`,
  };
}

function renderCode() {
  state.lastCode = codeSamples()[state.language];
  $("#code-sample").textContent = state.lastCode;
  $$(".code-tab").forEach((tab) => {
    const active = tab.dataset.language === state.language;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
}

function setProviderStatus(ready) {
  const chip = $("#status-chip");
  chip.classList.toggle("ready", ready);
  chip.classList.toggle("warning", !ready);
  $("#status-label").textContent = ready ? "Provider ready" : "Setup required";
  $("#footer-status").lastChild.textContent = ready ? " Provider ready" : " Setup required";
  $(".verified-badge").textContent = ready ? "✓ Configured" : "! Setup required";
}

async function loadConfig() {
  try {
    const response = await fetch("/api/config", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("Configuration request failed");
    state.config = await response.json();

    $("#model-id").textContent = state.config.modelId;
    $("#prompt-model").textContent = state.config.modelId;
    $("#base-url").textContent = state.config.baseUrl;
    $("#project-endpoint").textContent = compactEndpoint(state.config.projectEndpoint);
    $("#project-endpoint").title = state.config.projectEndpoint;
    $("#agent-name").textContent = state.config.agentName;
    $("#agent-version").textContent = state.config.agentVersion;
    $("#auth-mode").textContent = state.config.authMode;
    $("#route-agent").textContent = `${state.config.agentName} · v${state.config.agentVersion}`;
    $("#environment-chip").textContent = state.config.environment;
    setProviderStatus(state.config.providerReady);

    if (state.config.voiceliveVoice && $("#realtime-voice-select")) {
      $("#realtime-voice-select").value = state.config.voiceliveVoice;
    }

    if (!state.config.adminUnlockEnabled) {
      $("#key-help").textContent = "Set ADMIN_API_KEY to enable secure reveal.";
      $("#unlock-button").disabled = true;
    }
    renderCode();
  } catch {
    $("#status-label").textContent = "Provider unavailable";
    $("#status-chip").classList.add("warning");
    showToast("Could not load provider configuration");
  }
}

function openUnlockModal() {
  if (state.providerKey) {
    state.keyVisible = true;
    renderKey();
    $("#api-key").scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  $("#unlock-modal").classList.remove("hidden");
  document.body.style.overflow = "hidden";
  setTimeout(() => $("#admin-key").focus(), 0);
}

function closeUnlockModal() {
  $("#unlock-modal").classList.add("hidden");
  document.body.style.overflow = "";
  $("#unlock-error").classList.add("hidden");
  $("#unlock-form").reset();
}

async function unlockProviderKey(adminKey) {
  const response = await fetch("/api/admin/provider-key", {
    headers: { "x-admin-key": adminKey, Accept: "application/json" },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error?.message || "Unable to unlock the provider key.");
  }
  state.providerKey = payload.apiKey;
  state.keyVisible = false;
  renderKey();
  renderCode();
  $("#visibility-button").disabled = false;
  $("#copy-key-button").disabled = false;
  $("#copy-key-button").childNodes[0].textContent = "Copy API key ";
  $("#key-help").textContent = "Unlocked for this page session only.";
  $("#unlock-button").innerHTML = '<span aria-hidden="true">✓</span> Key unlocked';
}

function extractResponseText(payload) {
  if (typeof payload.output_text === "string") return payload.output_text;
  const parts = [];
  for (const item of payload.output || []) {
    if (item.type !== "message") continue;
    for (const content of item.content || []) {
      if (["output_text", "text"].includes(content.type) && typeof content.text === "string") {
        parts.push(content.text);
      }
    }
  }
  return parts.join("") || "The agent returned a response without text output.";
}

const voiceState = {
  isActive: false,
  isMuted: false,
  mode: "idle",
  ws: null,
  captureCtx: null,
  micStream: null,
  micProcessor: null,
  playbackCtx: null,
  activeSources: [],
  nextPlaybackTime: 0,
  currentAssistantBubble: null,
  responseDone: true,
};

function setVoiceVisualState(mode, title, subtitle) {
  voiceState.mode = mode;
  const panel = $(".voice-panel");
  const orb = $("#voice-orb");
  const statusBadge = $("#voice-connection-status");
  const titleEl = $("#voice-state-title");
  const subtitleEl = $("#voice-state-subtitle");
  const iconEl = $("#voice-orb-icon");

  if (panel) {
    panel.classList.remove("listening", "speaking", "connecting", "idle", "error");
    panel.classList.add(mode);
  }
  if (orb) {
    orb.className = `voice-orb ${mode}`;
  }
  if (statusBadge) {
    statusBadge.className = `voice-status-badge ${mode}`;
    statusBadge.textContent = mode.toUpperCase();
  }
  if (titleEl && title) titleEl.textContent = title;
  if (subtitleEl && subtitle) subtitleEl.textContent = subtitle;

  if (iconEl) {
    if (mode === "listening") iconEl.textContent = "👂";
    else if (mode === "speaking") iconEl.textContent = "🗣️";
    else if (mode === "connecting") iconEl.textContent = "⏳";
    else if (mode === "error") iconEl.textContent = "⚠️";
    else iconEl.textContent = "🎙️";
  }
}

function renderAudioWavebars(level) {
  const spans = $$("#voice-wave-bars span");
  if (!spans.length) return;
  const clamped = Math.min(1, Math.max(0, level));
  spans.forEach((span, i) => {
    const mid = 7;
    const dist = Math.abs(i - mid) / mid;
    const height = Math.max(4, Math.round(clamped * 28 * (1 - dist * 0.4) * (0.6 + Math.random() * 0.6)));
    span.style.height = `${height}px`;
  });
}

function clearVoiceTranscript() {
  const list = $("#voice-transcript-list");
  if (!list) return;
  list.innerHTML = `
    <div class="empty-response" id="voice-empty-transcript">
      <span class="response-orb" aria-hidden="true"><i></i></span>
      <strong>No conversation yet</strong>
      <p>Click "Start voice call" to speak and listen in real time.</p>
    </div>
  `;
  voiceState.currentAssistantBubble = null;
}

function appendVoiceTranscript(role, text, isDelta = false) {
  const list = $("#voice-transcript-list");
  if (!list) return;
  const empty = $("#voice-empty-transcript");
  if (empty) empty.classList.add("hidden");

  if (role === "assistant" && isDelta && voiceState.currentAssistantBubble) {
    const content = voiceState.currentAssistantBubble.querySelector(".transcript-text");
    if (content) {
      content.textContent += text;
      list.scrollTop = list.scrollHeight;
      return;
    }
  }

  const bubble = document.createElement("div");
  bubble.className = `transcript-bubble ${role}`;
  const sender = document.createElement("span");
  sender.className = "transcript-sender";
  sender.textContent = role === "user" ? "You" : "Voice Agent";
  const content = document.createElement("span");
  content.className = "transcript-text";
  content.textContent = text;
  bubble.appendChild(sender);
  bubble.appendChild(content);

  list.appendChild(bubble);
  list.scrollTop = list.scrollHeight;

  if (role === "assistant") {
    voiceState.currentAssistantBubble = bubble;
  }
}

function downsampleBuffer(buffer, inSampleRate, outSampleRate = 24000) {
  if (inSampleRate === outSampleRate) return buffer;
  const ratio = inSampleRate / outSampleRate;
  const newLen = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLen);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let accum = 0, count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
      accum += buffer[i];
      count++;
    }
    result[offsetResult] = count > 0 ? accum / count : 0;
    offsetResult++;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

function floatTo16BitPCM(float32Array) {
  const buffer = new ArrayBuffer(float32Array.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }
  return new Uint8Array(buffer);
}

function uint8ToBase64(bytes) {
  let binary = "";
  const len = bytes.byteLength;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return window.btoa(binary);
}

function base64ToPCM16(base64) {
  const binary = window.atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  const int16 = new Int16Array(bytes.buffer);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    float32[i] = int16[i] / 32768.0;
  }
  return float32;
}

function stopVoicePlayback() {
  voiceState.activeSources.forEach((source) => {
    try { source.stop(); } catch (_) {}
  });
  voiceState.activeSources = [];
  if (voiceState.playbackCtx) {
    voiceState.nextPlaybackTime = voiceState.playbackCtx.currentTime;
  }
  renderAudioWavebars(0);
}

function playAudioDelta(base64Delta) {
  if (!voiceState.isActive || !voiceState.playbackCtx) return;
  const samples = base64ToPCM16(base64Delta);
  if (samples.length === 0) return;

  const buffer = voiceState.playbackCtx.createBuffer(1, samples.length, 24000);
  buffer.copyToChannel(samples, 0);

  const source = voiceState.playbackCtx.createBufferSource();
  source.buffer = buffer;
  source.connect(voiceState.playbackCtx.destination);

  const now = voiceState.playbackCtx.currentTime;
  if (voiceState.nextPlaybackTime < now) {
    voiceState.nextPlaybackTime = now + 0.03;
  }

  source.start(voiceState.nextPlaybackTime);
  voiceState.nextPlaybackTime += buffer.duration;

  voiceState.activeSources.push(source);
  source.onended = () => {
    const idx = voiceState.activeSources.indexOf(source);
    if (idx !== -1) voiceState.activeSources.splice(idx, 1);
    if (voiceState.activeSources.length === 0 && voiceState.responseDone) {
      setVoiceVisualState("listening", "Listening…", "Start speaking anytime");
      renderAudioWavebars(0);
    }
  };

  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += Math.abs(samples[i]);
  const avg = sum / samples.length;
  renderAudioWavebars(avg * 3.5);
}

async function startVoiceSession() {
  if (!state.providerKey) {
    openUnlockModal();
    showToast("Unlock provider key before starting voice session");
    return;
  }

  const toggleBtn = $("#voice-toggle-btn");
  const toggleLabel = $("#voice-toggle-label");
  const muteBtn = $("#voice-mute-btn");
  const voiceSelect = $("#realtime-voice-select");

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    const msg = "Microphone capture is not supported by this browser environment or requires HTTPS/localhost.";
    showToast(msg);
    setVoiceVisualState("error", "Unsupported Browser", msg);
    return;
  }

  setVoiceVisualState("connecting", "Connecting to VoiceLive…", "Establishing WebSocket session with Azure AI");
  toggleBtn.disabled = true;

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        sampleRate: 24000,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    voiceState.micStream = stream;

    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    voiceState.captureCtx = new AudioContextClass({ sampleRate: 24000 });
    voiceState.playbackCtx = new AudioContextClass({ sampleRate: 24000 });

    if (voiceState.captureCtx.state === "suspended") await voiceState.captureCtx.resume();
    if (voiceState.playbackCtx.state === "suspended") await voiceState.playbackCtx.resume();

    const selectedVoice = voiceSelect?.value || "en-US-Ava:DragonHDLatestNeural";
    const loc = window.location;
    const protocol = loc.protocol === "https:" ? "wss:" : "ws:";
    const host = loc.host || "localhost:8000";
    const wsUrl = `${protocol}//${host}/v1/realtime?api_key=${encodeURIComponent(state.providerKey)}&voice=${encodeURIComponent(selectedVoice)}`;

    const ws = new WebSocket(wsUrl);
    voiceState.ws = ws;

    ws.onopen = () => {
      voiceState.isActive = true;
      voiceState.nextPlaybackTime = voiceState.playbackCtx.currentTime;
      setVoiceVisualState("listening", "Listening…", "Microphone active. Start speaking to the assistant.");
      toggleBtn.disabled = false;
      toggleBtn.classList.add("active");
      if (toggleLabel) toggleLabel.textContent = "End voice call";
      if (muteBtn) muteBtn.disabled = false;

      // Start audio capture loop
      const micSource = voiceState.captureCtx.createMediaStreamSource(stream);
      const processor = voiceState.captureCtx.createScriptProcessor(2048, 1, 1);
      voiceState.micProcessor = processor;

      const muteGain = voiceState.captureCtx.createGain();
      muteGain.gain.value = 0;

      processor.onaudioprocess = (e) => {
        if (!voiceState.isActive || voiceState.isMuted) return;
        const input = e.inputBuffer.getChannelData(0);
        const downsampled = downsampleBuffer(input, voiceState.captureCtx.sampleRate, 24000);
        const pcmBytes = floatTo16BitPCM(downsampled);
        const base64Audio = uint8ToBase64(pcmBytes);

        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: "input_audio_buffer.append",
            audio: base64Audio,
          }));
        }

        let sum = 0;
        for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
        const rms = Math.sqrt(sum / input.length);
        if (voiceState.mode === "listening" && !voiceState.isMuted) {
          renderAudioWavebars(rms * 4);
        }
      };

      micSource.connect(processor);
      processor.connect(muteGain);
      muteGain.connect(voiceState.captureCtx.destination);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const type = data.type;

        if (type === "session.created" || type === "session.updated") {
          setVoiceVisualState("listening", "Listening…", "Session ready. Speak anytime.");
        } else if (type === "input_audio_buffer.speech_started") {
          // Barge-in interruption
          stopVoicePlayback();
          setVoiceVisualState("listening", "Listening…", "Interruption detected. Speaking to agent…");
        } else if (type === "input_audio_buffer.speech_stopped") {
          setVoiceVisualState("connecting", "Processing…", "Agent is generating response…");
        } else if (type === "response.created") {
          voiceState.responseDone = false;
          voiceState.currentAssistantBubble = null;
          setVoiceVisualState("speaking", "Agent speaking…", "Streaming real-time voice response");
        } else if (type === "response.audio.delta" && data.delta) {
          setVoiceVisualState("speaking", "Agent speaking…", "Streaming real-time voice response");
          playAudioDelta(data.delta);
        } else if (type === "response.audio_transcript.delta" && data.delta) {
          if (!voiceState.currentAssistantBubble) {
            appendVoiceTranscript("assistant", data.delta);
          } else {
            appendVoiceTranscript("assistant", data.delta, true);
          }
        } else if (type === "response.audio.done") {
          // Audio generation completed
        } else if (type === "response.done") {
          voiceState.responseDone = true;
          if (voiceState.activeSources.length === 0) {
            setVoiceVisualState("listening", "Listening…", "Ready for your next question.");
          }
        } else if (type === "conversation.item.input_audio_transcription.completed" && data.transcript) {
          appendVoiceTranscript("user", data.transcript);
        } else if (type === "error") {
          const msg = data.error?.message || "Unknown voice session error";
          if (!msg.toLowerCase().includes("no active response")) {
            showToast(`VoiceLive error: ${msg}`);
          }
        }
      } catch (err) {
        console.warn("Real-time message parse error:", err);
      }
    };

    ws.onclose = () => {
      stopVoiceSession();
    };

    ws.onerror = (err) => {
      console.error("Voice WebSocket error:", err);
      showToast("Voice session connection error");
      stopVoiceSession();
    };
  } catch (err) {
    console.error("Failed to start voice session:", err);
    let userMsg = err.message || "Could not access microphone or connect to voice endpoint";
    if (err.name === "NotAllowedError" || (err.message && err.message.includes("Permission denied"))) {
      userMsg = "Microphone access blocked. Please allow microphone permissions in your browser address bar or site settings.";
    } else if (err.name === "NotFoundError" || (err.message && err.message.includes("device not found"))) {
      userMsg = "No microphone found. Please connect an audio input device and try again.";
    }
    showToast(userMsg);
    setVoiceVisualState("error", "Microphone Denied", userMsg);
    stopVoiceSession();
  } finally {
    toggleBtn.disabled = false;
  }
}

function stopVoiceSession() {
  voiceState.isActive = false;
  const toggleBtn = $("#voice-toggle-btn");
  const toggleLabel = $("#voice-toggle-label");
  const muteBtn = $("#voice-mute-btn");

  if (voiceState.ws) {
    try { voiceState.ws.close(); } catch (_) {}
    voiceState.ws = null;
  }

  if (voiceState.micProcessor) {
    try { voiceState.micProcessor.disconnect(); } catch (_) {}
    voiceState.micProcessor = null;
  }

  if (voiceState.micStream) {
    voiceState.micStream.getTracks().forEach((track) => track.stop());
    voiceState.micStream = null;
  }

  if (voiceState.captureCtx) {
    try { voiceState.captureCtx.close(); } catch (_) {}
    voiceState.captureCtx = null;
  }

  stopVoicePlayback();

  if (voiceState.playbackCtx) {
    try { voiceState.playbackCtx.close(); } catch (_) {}
    voiceState.playbackCtx = null;
  }

  setVoiceVisualState("idle", "Ready to Connect", "Start a real-time conversation with Azure VoiceLive AI.");
  renderAudioWavebars(0);

  if (toggleBtn) {
    toggleBtn.classList.remove("active");
    toggleBtn.disabled = false;
  }
  if (toggleLabel) toggleLabel.textContent = "Start voice call";
  if (muteBtn) {
    muteBtn.disabled = true;
    voiceState.isMuted = false;
    $("#voice-mute-icon").textContent = "🎤";
    $("#voice-mute-label").textContent = "Mute";
  }
}

function toggleVoiceMute() {
  if (!voiceState.isActive) return;
  voiceState.isMuted = !voiceState.isMuted;
  const icon = $("#voice-mute-icon");
  const label = $("#voice-mute-label");
  if (voiceState.isMuted) {
    if (icon) icon.textContent = "🔇";
    if (label) label.textContent = "Unmute";
    showToast("Microphone muted");
  } else {
    if (icon) icon.textContent = "🎤";
    if (label) label.textContent = "Mute";
    showToast("Microphone unmuted");
  }
}

function setPlaygroundMode(mode) {
  state.playgroundMode = mode;
  const promptInput = $("#prompt-input");
  const isChat = mode === "chat";
  const isTTS = mode === "tts";
  const isVoice = mode === "voice";

  $("#switch-chat-btn")?.classList.toggle("active", isChat);
  $("#switch-chat-btn")?.setAttribute("aria-selected", String(isChat));
  $("#switch-tts-btn")?.classList.toggle("active", isTTS);
  $("#switch-tts-btn")?.setAttribute("aria-selected", String(isTTS));
  $("#switch-voice-btn")?.classList.toggle("active", isVoice);
  $("#switch-voice-btn")?.setAttribute("aria-selected", String(isVoice));

  const standardGrid = $(".playground-grid:not(.voice-playground-grid)");
  const voiceGrid = $("#voice-playground-grid");

  const kicker = $("#playground-kicker");
  const title = $("#playground-title");
  const modelTag = $("#prompt-model");
  const voiceGroup = $("#voice-select-group");
  const attachBtn = $("#attach-image-button");
  const imagePreview = $("#image-preview-container");
  const sendLabel = $("#send-button-label");
  const barTitle = $("#prompt-bar-title");
  const respBarTitle = $("#response-bar-title");
  const emptyTitle = $("#empty-response-title");
  const emptyDesc = $("#empty-response-desc");
  const chatWrap = $("#chat-response-wrap");
  const ttsWrap = $("#tts-response-wrap");

  if (isVoice) {
    if (standardGrid) standardGrid.classList.add("hidden");
    if (voiceGrid) voiceGrid.classList.remove("hidden");
    if (kicker) kicker.textContent = "Real-time Voice AI";
    if (title) title.textContent = "Talk with your agent.";
    return;
  }

  if (standardGrid) standardGrid.classList.remove("hidden");
  if (voiceGrid) voiceGrid.classList.add("hidden");
  if (voiceState.isActive) {
    stopVoiceSession();
  }

  if (isChat) {
    if (kicker) kicker.textContent = "Live playground";
    if (title) title.textContent = "Ask your agent.";
    if (barTitle) barTitle.textContent = "REQUEST";
    if (respBarTitle) respBarTitle.textContent = "RESPONSE";
    if (modelTag) modelTag.textContent = state.config?.modelId || "gpt-6";
    if (voiceGroup) voiceGroup.style.display = "none";
    if (attachBtn) attachBtn.style.display = "inline-flex";
    if (imagePreview) imagePreview.style.display = state.attachedImage ? "inline-flex" : "none";
    if (sendLabel) sendLabel.textContent = "Stream response";
    if (emptyTitle) emptyTitle.textContent = "Your agent’s response appears here";
    if (emptyDesc) emptyDesc.textContent = "Unlock your key, then watch the answer stream in live.";
    promptInput.placeholder = "Ask anything or attach an image…";
    promptInput.value = state.chatDraft;
    if (chatWrap) chatWrap.style.display = "block";
    if (ttsWrap) ttsWrap.style.display = "none";
  } else {
    if (kicker) kicker.textContent = "Text to speech";
    if (title) title.textContent = "Synthesize speech.";
    if (barTitle) barTitle.textContent = "SPEECH INPUT";
    if (respBarTitle) respBarTitle.textContent = "AUDIO SYNTHESIS";
    if (modelTag) modelTag.textContent = "tts-1";
    if (voiceGroup) voiceGroup.style.display = "inline-flex";
    if (attachBtn) attachBtn.style.display = "none";
    if (imagePreview) imagePreview.style.display = "none";
    if (sendLabel) sendLabel.textContent = "Synthesize audio";
    if (emptyTitle) emptyTitle.textContent = "Your synthesized speech will appear here";
    if (emptyDesc) emptyDesc.textContent = "Enter text, choose a voice, and click Synthesize audio.";
    promptInput.placeholder = "Enter text to convert to natural speech with Azure Speech…";
    promptInput.value = state.ttsDraft;
    if (chatWrap) chatWrap.style.display = "none";
    if (ttsWrap) ttsWrap.style.display = "block";
  }

  const count = $("#prompt-count");
  if (count) count.textContent = `${promptInput.value.length.toLocaleString()} / 4,000`;
}

async function runPlaygroundTTS(text) {
  if (!state.providerKey) {
    openUnlockModal();
    throw new Error("Unlock the provider key before synthesizing speech.");
  }

  const voice = $("#voice-select")?.value || "onyx";
  const button = $("#send-button");
  const label = $("#send-button-label");
  const startedAt = performance.now();

  button.disabled = true;
  if (label) label.textContent = "Synthesizing…";
  $("#request-meta").textContent = "Synthesizing audio…";

  try {
    const targetUrl = "/v1/audio/speech";

    const response = await fetch(targetUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${state.providerKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "tts-1",
        input: text,
        voice: voice,
        response_format: "mp3",
      }),
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error?.message || `TTS request failed (${response.status})`);
    }

    const arrayBuffer = await response.arrayBuffer();
    const audioBlob = new Blob([arrayBuffer], { type: "audio/mpeg" });
    const audioUrl = URL.createObjectURL(audioBlob);
    const elapsed = Math.round(performance.now() - startedAt);
    const sizeKb = (audioBlob.size / 1024).toFixed(1);

    const playback = $("#tts-audio-playback");
    const playBtn = $("#tts-play-btn");
    if (playback) {
      playback.src = audioUrl;
      playback.load();
      try {
        await playback.play();
        if (playBtn) playBtn.innerHTML = "<span>⏸</span> Pause";
      } catch (playErr) {
        console.warn("Autoplay deferred until user clicks play:", playErr);
        if (playBtn) playBtn.innerHTML = "<span>▶</span> Play audio";
      }
    }

    const downloadLink = $("#tts-download-link");
    if (downloadLink) {
      downloadLink.href = audioUrl;
      downloadLink.download = `speech_${voice}_${Date.now()}.mp3`;
    }

    $("#tts-pill-model").textContent = "tts-1";
    $("#tts-pill-voice").textContent = voice;
    $("#tts-pill-size").textContent = `${sizeKb} KB`;
    $("#tts-pill-time").textContent = `${elapsed} ms`;

    $("#raw-response").textContent = JSON.stringify(
      {
        status: response.status,
        model: "tts-1",
        voice: voice,
        format: "mp3",
        sizeBytes: audioBlob.size,
        latencyMs: elapsed,
        inputLength: text.length,
      },
      null,
      2
    );

    $("#request-meta").textContent = `200 synthesized · ${elapsed} ms · ${sizeKb} KB`;
    $("#empty-response").classList.add("hidden");
    $("#response-content").classList.remove("hidden");
    if ($("#tts-response-wrap")) $("#tts-response-wrap").style.display = "block";
    if ($("#chat-response-wrap")) $("#chat-response-wrap").style.display = "none";
  } catch (error) {
    $("#request-meta").textContent = "Synthesis failed";
    $("#response-text").textContent = error.message;
    $("#raw-response").textContent = JSON.stringify({ error: error.message }, null, 2);
    $("#empty-response").classList.add("hidden");
    $("#response-content").classList.remove("hidden");
    if ($("#tts-response-wrap")) $("#tts-response-wrap").style.display = "none";
    if ($("#chat-response-wrap")) $("#chat-response-wrap").style.display = "block";
    throw error;
  } finally {
    button.disabled = false;
    if (label) label.textContent = "Synthesize audio";
  }
}

async function runPlayground(prompt) {
  if (!state.providerKey) {
    openUnlockModal();
    throw new Error("Unlock the provider key before sending a request.");
  }

  const button = $("#send-button");
  button.disabled = true;
  $(".button-label").textContent = "Connecting…";
  $("#request-meta").textContent = "Opening stream";
  const startedAt = performance.now();
  let firstTokenAt = null;
  let streamedText = "";
  const rawEvents = [];

  $("#response-text").textContent = "";
  $("#raw-response").textContent = "[]";
  $("#empty-response").classList.add("hidden");
  $("#response-content").classList.remove("hidden");
  if ($("#chat-response-wrap")) $("#chat-response-wrap").style.display = "block";
  if ($("#tts-response-wrap")) $("#tts-response-wrap").style.display = "none";

  try {
    const targetUrl = "/v1/responses";
    const requestInput = state.attachedImage
      ? [
          {
            role: "user",
            content: [
              { type: "input_text", text: prompt },
              { type: "input_image", image_url: state.attachedImage },
            ],
          },
        ]
      : [{ role: "user", content: prompt }];

    const response = await fetch(targetUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${state.providerKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: state.config.modelId,
        input: requestInput,
        stream: true,
      }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error?.message || `Request failed (${response.status})`);
    }
    if (!response.body) throw new Error("This browser does not expose streaming response bodies.");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finished = false;
    $(".button-label").textContent = "Streaming…";

    const processEventBlock = (block) => {
      const data = block
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (!data) return;
      if (data === "[DONE]") {
        finished = true;
        return;
      }

      const event = JSON.parse(data);
      rawEvents.push(event);
      $("#raw-response").textContent = JSON.stringify(rawEvents, null, 2);
      if (event.error) throw new Error(event.error.message || "The response stream failed.");

      if (event.type === "response.output_text.delta" && typeof event.delta === "string") {
        if (firstTokenAt === null) firstTokenAt = performance.now();
        streamedText += event.delta;
        $("#response-text").textContent = streamedText;
        $("#request-meta").textContent = `Streaming · ${streamedText.length.toLocaleString()} chars`;
      } else if (!streamedText && event.type === "response.completed" && event.response) {
        streamedText = extractResponseText(event.response);
        $("#response-text").textContent = streamedText;
      }
    };

    while (!finished) {
      const { value, done } = await reader.read();
      buffer = (buffer + decoder.decode(value || new Uint8Array(), { stream: !done })).replace(/\r\n/g, "\n");
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() || "";
      for (const block of blocks) processEventBlock(block);
      if (done) {
        if (buffer.trim()) processEventBlock(buffer.trim());
        break;
      }
    }

    const elapsed = Math.round(performance.now() - startedAt);
    const firstToken = firstTokenAt === null ? "no text delta" : `${Math.round(firstTokenAt - startedAt)} ms first token`;
    $("#request-meta").textContent = `${response.status} streamed · ${elapsed} ms · ${firstToken}`;
    if (!streamedText) $("#response-text").textContent = "The stream completed without text output.";
  } catch (error) {
    $("#request-meta").textContent = "Request failed";
    $("#response-text").textContent = error.message;
    $("#raw-response").textContent = JSON.stringify({ error: error.message }, null, 2);
    $("#empty-response").classList.add("hidden");
    $("#response-content").classList.remove("hidden");
    throw error;
  } finally {
    button.disabled = false;
    $(".button-label").textContent = "Stream response";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadConfig();
  renderKey();

  $$("[data-copy-target]").forEach((button) => {
    button.addEventListener("click", () => copyText($(`#${button.dataset.copyTarget}`).textContent));
  });

  $("#copy-key-button").addEventListener("click", () => state.providerKey && copyText(state.providerKey));
  $("#visibility-button").addEventListener("click", () => {
    state.keyVisible = !state.keyVisible;
    renderKey();
  });

  $("#unlock-button").addEventListener("click", openUnlockModal);
  $("#modal-close").addEventListener("click", closeUnlockModal);
  $("#unlock-modal").addEventListener("click", (event) => {
    if (event.target === $("#unlock-modal")) closeUnlockModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#unlock-modal").classList.contains("hidden")) closeUnlockModal();
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") $("#prompt-form").requestSubmit();
  });

  $("#admin-visibility").addEventListener("click", () => {
    const input = $("#admin-key");
    input.type = input.type === "password" ? "text" : "password";
  });

  $("#unlock-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = $("#unlock-submit");
    const error = $("#unlock-error");
    submit.disabled = true;
    submit.textContent = "Checking…";
    error.classList.add("hidden");
    try {
      await unlockProviderKey($("#admin-key").value);
      closeUnlockModal();
      showToast("Provider key unlocked");
    } catch (exception) {
      error.textContent = exception.message;
      error.classList.remove("hidden");
    } finally {
      submit.disabled = false;
      submit.textContent = "Unlock dashboard";
    }
  });

  const prompt = $("#prompt-input");
  const updateCount = () => { $("#prompt-count").textContent = `${prompt.value.length.toLocaleString()} / 4,000`; };
  prompt.addEventListener("input", () => {
    updateCount();
    if (state.playgroundMode === "tts") {
      state.ttsDraft = prompt.value;
    } else {
      state.chatDraft = prompt.value;
    }
  });
  updateCount();

  $("#switch-chat-btn")?.addEventListener("click", () => setPlaygroundMode("chat"));
  $("#switch-tts-btn")?.addEventListener("click", () => setPlaygroundMode("tts"));
  $("#switch-voice-btn")?.addEventListener("click", () => setPlaygroundMode("voice"));

  $("#voice-toggle-btn")?.addEventListener("click", () => {
    if (voiceState.isActive) {
      stopVoiceSession();
    } else {
      startVoiceSession();
    }
  });

  $("#voice-mute-btn")?.addEventListener("click", toggleVoiceMute);
  $("#voice-clear-transcript")?.addEventListener("click", clearVoiceTranscript);

  $("#prompt-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = prompt.value.trim();
    if (!value) return;
    try {
      if (state.playgroundMode === "tts") {
        await runPlaygroundTTS(value);
      } else {
        await runPlayground(value);
      }
    } catch (error) {
      showToast(error.message);
    }
  });

  const fileInput = $("#image-file-input");
  const attachButton = $("#attach-image-button");
  const previewContainer = $("#image-preview-container");
  const previewImg = $("#image-preview");
  const removeButton = $("#remove-image-button");

  if (attachButton && fileInput) {
    attachButton.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => {
      const file = fileInput.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (e) => {
        state.attachedImage = e.target?.result;
        previewImg.src = state.attachedImage;
        previewContainer.style.display = "inline-flex";
      };
      reader.readAsDataURL(file);
    });
  }

  if (removeButton) {
    removeButton.addEventListener("click", () => {
      state.attachedImage = null;
      if (fileInput) fileInput.value = "";
      previewContainer.style.display = "none";
    });
  }

  $$(".code-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.language = tab.dataset.language;
      renderCode();
    });
  });
  $("#code-copy").addEventListener("click", () => copyText(state.lastCode));

  const speakButton = $("#speak-button");
  const audioPlayer = $("#audio-player");
  if (speakButton && audioPlayer) {
    speakButton.addEventListener("click", async () => {
      const text = ($("#response-text")?.textContent || "").trim();
      if (!text) {
        showToast("No response text to read aloud");
        return;
      }
      if (!state.providerKey) {
        showToast("Unlock provider key first");
        openUnlockModal();
        return;
      }
      speakButton.disabled = true;
      const originalText = speakButton.textContent;
      speakButton.textContent = "🔊 Generating…";
      try {
        const targetUrl = "/v1/audio/speech";
        const response = await fetch(targetUrl, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${state.providerKey}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            model: "tts-1",
            input: text.slice(0, 4000),
            voice: state.config?.speechVoice || "onyx",
          }),
        });
        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          throw new Error(err.error?.message || `TTS failed (${response.status})`);
        }
        const arrayBuffer = await response.arrayBuffer();
        const audioBlob = new Blob([arrayBuffer], { type: "audio/mpeg" });
        const url = URL.createObjectURL(audioBlob);
        audioPlayer.src = url;
        audioPlayer.load();
        speakButton.textContent = "🔊 Playing…";
        audioPlayer.onended = () => {
          speakButton.disabled = false;
          speakButton.textContent = originalText;
          URL.revokeObjectURL(url);
        };
        audioPlayer.onerror = (e) => {
          console.error("Audio playback error:", e);
          speakButton.disabled = false;
          speakButton.textContent = originalText;
          URL.revokeObjectURL(url);
        };
        try {
          await audioPlayer.play();
        } catch (playErr) {
          console.warn("Autoplay was blocked by browser:", playErr);
          speakButton.disabled = false;
          speakButton.textContent = originalText;
        }
      } catch (err) {
        showToast(err.message || "Failed to generate speech");
        speakButton.disabled = false;
        speakButton.textContent = originalText;
      }
    });
  }

  const ttsPlayBtn = $("#tts-play-btn");
  const ttsPlayback = $("#tts-audio-playback");
  if (ttsPlayBtn && ttsPlayback) {
    ttsPlayBtn.addEventListener("click", async () => {
      if (!ttsPlayback.src) {
        showToast("No synthesized audio yet");
        return;
      }
      if (ttsPlayback.paused) {
        try {
          await ttsPlayback.play();
          ttsPlayBtn.innerHTML = "<span>⏸</span> Pause";
        } catch (err) {
          showToast(err.message || "Playback failed");
        }
      } else {
        ttsPlayback.pause();
        ttsPlayBtn.innerHTML = "<span>▶</span> Play audio";
      }
    });

    ttsPlayback.addEventListener("play", () => {
      if (ttsPlayBtn) ttsPlayBtn.innerHTML = "<span>⏸</span> Pause";
    });
    ttsPlayback.addEventListener("pause", () => {
      if (ttsPlayBtn) ttsPlayBtn.innerHTML = "<span>▶</span> Play audio";
    });
    ttsPlayback.addEventListener("ended", () => {
      if (ttsPlayBtn) ttsPlayBtn.innerHTML = "<span>▶</span> Play audio";
    });
  }

  const sections = ["overview", "playground", "integration"];
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      $$(".nav-item").forEach((item) => item.classList.toggle("active", item.getAttribute("href") === `#${entry.target.id}`));
    }
  }, { rootMargin: "-35% 0px -55%" });
  sections.forEach((id) => observer.observe($(`#${id}`)));
});
