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

// All voice goes through ElevenLabs via /api/v1/voice/speak
let _currentAudio = null;

async function speakText(text, lang) {
  if (!text) return;
  // Stop any currently playing audio before starting new one
  if (_currentAudio) {
    _currentAudio.pause();
    _currentAudio.src = '';
    _currentAudio = null;
  }
  try {
    const r = await fetch(API_BASE + '/api/v1/voice/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.slice(0, 500), lang: lang || 'en' }),
    });
    if (!r.ok) throw new Error('ElevenLabs returned ' + r.status);
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    _currentAudio = audio;
    audio.play();
    audio.onended = () => { URL.revokeObjectURL(url); if (_currentAudio === audio) _currentAudio = null; };
  } catch (e) {
    console.warn('ElevenLabs voice unavailable:', e.message);
  }
}

// Aliases — no longer use browser speech synthesis
function speakBrowser(text) { speakText(text, 'en'); }
function speakBrowserQueue(text) { speakText(text, 'en'); }
