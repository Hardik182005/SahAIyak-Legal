/* SahAIyak — shared API client */
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:8000'
  : '';  // same origin in production (Cloud Run serves both)

async function apiPost(path, body) {
  const r = await fetch(API_BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`API ${path} failed: ${r.status}`);
  return r.json();
}

async function apiGet(path) {
  const r = await fetch(API_BASE + path);
  if (!r.ok) throw new Error(`API GET ${path} failed: ${r.status}`);
  return r.json();
}

function getCaseId() {
  const params = new URLSearchParams(window.location.search);
  return params.get('case') || localStorage.getItem('sahayak_case_id');
}

function setCaseId(id) {
  localStorage.setItem('sahayak_case_id', id);
}

async function speakText(text, lang) {
  if (!text) return;
  try {
    const r = await fetch(API_BASE + '/api/v1/voice/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.slice(0, 500), lang: lang || 'en' }),
    });
    if (!r.ok) { speakBrowser(text); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.play();
    audio.onended = () => URL.revokeObjectURL(url);
  } catch (e) {
    console.warn('ElevenLabs unavailable, using browser TTS:', e);
    speakBrowser(text);
  }
}

function speakBrowser(text, rate, pitch) {
  if (!text || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utt = new SpeechSynthesisUtterance(text);
  utt.lang = 'en-IN';
  utt.rate = rate || 1.05;
  utt.pitch = pitch || 1.0;
  utt.volume = 1.0;
  window.speechSynthesis.speak(utt);
}

function speakBrowserQueue(text, rate) {
  if (!text || !window.speechSynthesis) return;
  const utt = new SpeechSynthesisUtterance(text);
  utt.lang = 'en-IN';
  utt.rate = rate || 1.05;
  utt.pitch = 1.0;
  utt.volume = 1.0;
  window.speechSynthesis.speak(utt);
}
