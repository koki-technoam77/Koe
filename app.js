/**
 * KoeGuide - Municipal FAQ Voice Agent
 * Vocal Bridge + LiveKit integration
 */

// LiveKit SDK (loaded via UMD)
const { Room, RoomEvent, Track } = LivekitClient;

// i18n
const i18n = {
  ja: {
    subtitle: 'AIコンシェルジュ',
    transcript_title: '会話履歴',
    info_title: '情報カード',
    mic_start: 'タップして開始',
    mic_stop: 'タップして終了',
    mic_connecting: '接続中...',
    status_disconnected: '未接続',
    status_connecting: '接続中...',
    status_connected: '接続済み',
    status_error: 'エラー',
    welcome: 'ようこそ！',
    welcome_desc: 'マイクボタンを押して質問してください。',
    welcome_hint: '例: 「転入届はどうすればいいですか？」',
    sample_move_in: '🏠 転入届',
    sample_resident_cert: '📄 住民票',
    sample_garbage: '🗑️ ゴミ分別',
    sample_child_allow: '👶 児童手当',
    sample_evacuation: '🏃 避難場所',
    agent_listening: '🎤 聞いています...',
    agent_thinking: '🤔 考えています...',
    agent_speaking: '💬 お答えします...',
    role_user: 'あなた',
    role_agent: 'Mado',
    sample_hint: '「{topic}について教えて」と話しかけてね',
    error_prefix: 'エラー: ',
    error_default: '接続失敗',
    label_place: '場所',
    label_hours: '受付時間',
    label_fee: '手数料',
    label_phone: '電話',
    label_docs: '📋 必要書類',
    label_info: '情報',
    label_window: '📍 窓口情報',
    label_docs_checklist: '必要書類チェックリスト',
    lang_btn: 'EN',
  },
  en: {
    subtitle: 'AI Concierge',
    transcript_title: 'Transcript',
    info_title: 'Info Cards',
    mic_start: 'Tap to start',
    mic_stop: 'Tap to stop',
    mic_connecting: 'Connecting...',
    status_disconnected: 'Disconnected',
    status_connecting: 'Connecting...',
    status_connected: 'Connected',
    status_error: 'Error',
    welcome: 'Welcome!',
    welcome_desc: 'Press the mic button and ask a question.',
    welcome_hint: 'e.g. "How do I submit a move-in notice?"',
    sample_move_in: '🏠 Move-in',
    sample_resident_cert: '📄 Resident Cert',
    sample_garbage: '🗑️ Garbage',
    sample_child_allow: '👶 Child Benefit',
    sample_evacuation: '🏃 Evacuation',
    agent_listening: '🎤 Listening...',
    agent_thinking: '🤔 Thinking...',
    agent_speaking: '💬 Responding...',
    role_user: 'You',
    role_agent: 'Mado',
    sample_hint: 'Ask "Tell me about {topic}"',
    error_prefix: 'Error: ',
    error_default: 'Connection failed',
    label_place: 'Location',
    label_hours: 'Hours',
    label_fee: 'Fee',
    label_phone: 'Phone',
    label_docs: '📋 Required Documents',
    label_info: 'Info',
    label_window: '📍 Office Info',
    label_docs_checklist: 'Required Documents Checklist',
    lang_btn: 'JA',
  }
};

let currentLang = localStorage.getItem('koeguide-lang') || 'ja';

function t(key) {
  return i18n[currentLang][key] || key;
}

function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (i18n[currentLang][key]) {
      el.textContent = i18n[currentLang][key];
    }
  });
  // Update subtitle
  document.querySelector('.subtitle').textContent = t('subtitle');
  // Update lang button
  document.getElementById('lang-toggle').textContent = t('lang_btn');
  // Update status text based on current state
  if (isConnected) {
    statusText.textContent = t('status_connected');
    micLabel.textContent = t('mic_stop');
  } else if (isConnecting) {
    statusText.textContent = t('status_connecting');
    micLabel.textContent = t('mic_connecting');
  } else {
    statusText.textContent = t('status_disconnected');
    micLabel.textContent = t('mic_start');
  }
  // Update html lang attribute
  document.documentElement.lang = currentLang;
}

function toggleLang() {
  currentLang = currentLang === 'ja' ? 'en' : 'ja';
  localStorage.setItem('koeguide-lang', currentLang);
  applyI18n();
}

// State
let room = null;
let isConnected = false;
let isConnecting = false;
let faqData = [];

// DOM Elements
const micBtn = document.getElementById('mic-btn');
const micLabel = document.getElementById('mic-label');
const statusDot = document.querySelector('.status-dot');
const statusText = document.getElementById('status-text');
const transcriptEl = document.getElementById('transcript');
const infoCards = document.getElementById('info-cards');
const agentStatus = document.getElementById('agent-status');
const pulseRing = document.getElementById('pulse-ring');

// Load FAQ data
async function loadFaqData() {
  try {
    const resp = await fetch('/api/faq');
    faqData = await resp.json();
  } catch (e) {
    console.warn('FAQ data load failed, using empty array:', e);
  }
}

// Toggle connection
async function toggleConnection() {
  if (isConnecting) return;
  if (isConnected) {
    await disconnect();
  } else {
    await connect();
  }
}

// Connect to Vocal Bridge agent
async function connect() {
  isConnecting = true;
  updateUI('connecting');

  try {
    // Get LiveKit token from our backend
    const resp = await fetch('/api/voice-token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_name: 'Resident' }),
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || 'Token request failed');
    }

    const { livekit_url, token } = await resp.json();

    // Create LiveKit room with audio settings
    room = new Room({
      audioCaptureDefaults: {
        autoGainControl: true,
        echoCancellation: true,
        noiseSuppression: true,
      },
      publishDefaults: {
        audioPreset: { maxBitrate: 64000 },
      },
    });

    // Handle agent audio
    room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
      console.log('[KoeGuide] Track subscribed:', track.kind, participant?.identity);
      if (track.kind === Track.Kind.Audio) {
        const audioEl = track.attach();
        audioEl.id = 'agent-audio';
        audioEl.autoplay = true;
        audioEl.playsInline = true;
        document.body.appendChild(audioEl);
      }
    });

    // Handle track unsubscribed
    room.on(RoomEvent.TrackUnsubscribed, (track) => {
      track.detach().forEach(el => el.remove());
    });

    // Monitor local track publish
    room.on(RoomEvent.LocalTrackPublished, (publication) => {
      console.log('[KoeGuide] Local track published:', publication.kind, publication.track?.mediaStreamTrack?.label);
    });

    // Handle data channel (Client Actions, Transcript, Heartbeat)
    room.on(RoomEvent.DataReceived, (payload, participant, kind, topic) => {
      if (topic === 'client_actions') {
        try {
          const data = JSON.parse(new TextDecoder().decode(payload));
          console.log('[KoeGuide] Client action received:', data.action, data.payload);
          if (data.type === 'client_action') {
            handleClientAction(data.action, data.payload);
          }
        } catch (e) {
          console.error('Failed to parse client action:', e);
        }
      }
    });

    // Connection events
    room.on(RoomEvent.Connected, () => {
      isConnected = true;
      isConnecting = false;
      updateUI('connected');
    });

    room.on(RoomEvent.Disconnected, () => {
      isConnected = false;
      isConnecting = false;
      updateUI('disconnected');
    });

    // Connect
    await room.connect(livekit_url, token);

    // Enable microphone
    await room.localParticipant.setMicrophoneEnabled(true);
    console.log('[KoeGuide] Mic enabled. Local tracks:',
      room.localParticipant.audioTrackPublications.size,
      'Mic track muted?', room.localParticipant.isMicrophoneEnabled ? 'NO (good)' : 'YES (problem!)');

    // Log room participants
    console.log('[KoeGuide] Room participants:', room.remoteParticipants.size);
    room.remoteParticipants.forEach((p) => {
      console.log('[KoeGuide] Remote participant:', p.identity, 'tracks:', p.trackPublications.size);
    });

  } catch (e) {
    console.error('Connection failed:', e);
    isConnecting = false;
    updateUI('error', e.message);
  }
}

// Disconnect
async function disconnect() {
  if (room) {
    await room.disconnect();
    room = null;
  }
  // Remove agent audio element
  const audioEl = document.getElementById('agent-audio');
  if (audioEl) audioEl.remove();

  isConnected = false;
  updateUI('disconnected');
}

// Handle Client Actions from agent
function handleClientAction(action, payload) {
  switch (action) {
    case 'heartbeat':
      console.log('Heartbeat received:', payload);
      // Send ack
      if (room && room.localParticipant) {
        room.localParticipant.publishData(
          new TextEncoder().encode(JSON.stringify({
            type: 'client_action',
            action: 'heartbeat_ack',
            payload: { timestamp: payload.timestamp }
          })),
          { reliable: true, topic: 'client_actions' }
        );
      }
      break;

    case 'send_transcript':
      addTranscriptEntry(payload.role, payload.text);
      // Update agent status
      if (payload.role === 'user') {
        setAgentStatus('thinking');
      } else {
        setAgentStatus('speaking');
        setTimeout(() => setAgentStatus('listening'), 3000);
      }
      break;

    case 'show_faq_card':
      renderFaqCard(payload);
      break;

    case 'show_documents_checklist':
      renderDocumentsChecklist(payload);
      break;

    case 'show_location_info':
      renderLocationInfo(payload);
      break;

    case 'clear_card':
      clearInfoCards();
      break;

    default:
      console.log('Unknown action:', action, payload);
  }
}

// Add transcript entry
function addTranscriptEntry(role, text) {
  const entry = document.createElement('div');
  entry.className = `transcript-entry ${role === 'user' ? 'user' : 'agent'}`;
  entry.innerHTML = `
    <div class="role">${role === 'user' ? t('role_user') : t('role_agent')}</div>
    <div>${text}</div>
  `;
  transcriptEl.appendChild(entry);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

// Render FAQ card
function renderFaqCard(payload) {
  // Try to match with local FAQ data for additional info
  let faq = null;
  if (payload.id) {
    faq = faqData.find(f => f.id === payload.id);
  }

  // Use payload data, fallback to matched FAQ
  const title = payload.title || payload.question || (faq && faq.question) || t('label_info');
  const category = payload.category || (faq && faq.category) || '';
  const answer = payload.answer || (faq && faq.answer) || '';
  const where = payload.where || (faq && faq.where) || '';
  const hours = payload.hours || (faq && faq.hours) || '';
  const fee = payload.fee || (faq && faq.fee) || '';
  const notes = payload.notes || (faq && faq.notes) || '';
  const docs = payload.required_documents || (faq && faq.required_documents) || [];

  const card = document.createElement('div');
  card.className = 'faq-card';
  card.innerHTML = `
    <div class="faq-card-header">
      <h3>${title}</h3>
      ${category ? `<div class="category">${category}</div>` : ''}
    </div>
    <div class="faq-card-body">
      ${answer ? `<div class="answer">${answer}</div>` : ''}
      ${where ? `
        <div class="info-row">
          <span class="icon">📍</span>
          <span class="label">${t('label_place')}</span>
          <span class="value">${where}</span>
        </div>` : ''}
      ${hours ? `
        <div class="info-row">
          <span class="icon">🕐</span>
          <span class="label">${t('label_hours')}</span>
          <span class="value">${hours}</span>
        </div>` : ''}
      ${fee ? `
        <div class="info-row">
          <span class="icon">💰</span>
          <span class="label">${t('label_fee')}</span>
          <span class="value">${fee}</span>
        </div>` : ''}
      ${docs.length > 0 ? `
        <div class="docs-checklist">
          <h4>${t('label_docs')}</h4>
          <ul>${docs.map(d => `<li>${d}</li>`).join('')}</ul>
        </div>` : ''}
      ${notes ? `<div class="notes">⚠️ ${notes}</div>` : ''}
    </div>
  `;

  // Prepend (newest on top)
  infoCards.innerHTML = '';
  infoCards.appendChild(card);
}

// Render documents checklist
function renderDocumentsChecklist(payload) {
  const docs = payload.documents || payload.required_documents || [];
  const title = payload.title || t('label_docs_checklist');

  const card = document.createElement('div');
  card.className = 'faq-card';
  card.innerHTML = `
    <div class="faq-card-header">
      <h3>📋 ${title}</h3>
    </div>
    <div class="faq-card-body">
      <div class="docs-checklist">
        <ul>${docs.map(d => `<li>${d}</li>`).join('')}</ul>
      </div>
    </div>
  `;

  infoCards.innerHTML = '';
  infoCards.appendChild(card);
}

// Render location info
function renderLocationInfo(payload) {
  const card = document.createElement('div');
  card.className = 'faq-card';
  card.innerHTML = `
    <div class="faq-card-header">
      <h3>${payload.title || t('label_window')}</h3>
    </div>
    <div class="faq-card-body">
      ${payload.where ? `
        <div class="info-row">
          <span class="icon">🏢</span>
          <span class="label">${t('label_place')}</span>
          <span class="value">${payload.where}</span>
        </div>` : ''}
      ${payload.hours ? `
        <div class="info-row">
          <span class="icon">🕐</span>
          <span class="label">${t('label_hours')}</span>
          <span class="value">${payload.hours}</span>
        </div>` : ''}
      ${payload.phone ? `
        <div class="info-row">
          <span class="icon">📞</span>
          <span class="label">${t('label_phone')}</span>
          <span class="value">${payload.phone}</span>
        </div>` : ''}
      ${payload.notes ? `<div class="notes">💡 ${payload.notes}</div>` : ''}
    </div>
  `;

  infoCards.innerHTML = '';
  infoCards.appendChild(card);
}

// Clear info cards
function clearInfoCards() {
  infoCards.innerHTML = `
    <div class="welcome-card">
      <h3>${t('welcome')}</h3>
      <p>${t('welcome_desc')}</p>
    </div>
  `;
}

// Set agent status indicator
function setAgentStatus(status) {
  switch (status) {
    case 'listening':
      agentStatus.innerHTML = t('agent_listening');
      break;
    case 'thinking':
      agentStatus.innerHTML = t('agent_thinking');
      break;
    case 'speaking':
      agentStatus.innerHTML = t('agent_speaking');
      break;
    default:
      agentStatus.innerHTML = '';
  }
}

// Update UI state
function updateUI(state, errorMsg) {
  switch (state) {
    case 'connecting':
      micBtn.className = 'mic-btn connecting';
      micLabel.textContent = t('mic_connecting');
      statusDot.className = 'status-dot connecting';
      statusText.textContent = t('status_connecting');
      pulseRing.className = 'pulse-ring';
      break;

    case 'connected':
      micBtn.className = 'mic-btn active';
      micLabel.textContent = t('mic_stop');
      statusDot.className = 'status-dot online';
      statusText.textContent = t('status_connected');
      pulseRing.className = 'pulse-ring active';
      setAgentStatus('listening');
      break;

    case 'disconnected':
      micBtn.className = 'mic-btn';
      micLabel.textContent = t('mic_start');
      statusDot.className = 'status-dot offline';
      statusText.textContent = t('status_disconnected');
      pulseRing.className = 'pulse-ring';
      setAgentStatus('');
      break;

    case 'error':
      micBtn.className = 'mic-btn';
      micLabel.textContent = `${t('error_prefix')}${errorMsg || t('error_default')}`;
      statusDot.className = 'status-dot offline';
      statusText.textContent = t('status_error');
      pulseRing.className = 'pulse-ring';
      break;
  }
}

// Sample hint (for welcome card buttons)
function showSampleHint(topic) {
  if (!isConnected) {
    micLabel.textContent = t('sample_hint').replace('{topic}', topic);
    setTimeout(() => {
      if (!isConnected) micLabel.textContent = t('mic_start');
    }, 3000);
  }
}

// STT language selector
async function changeSttLang(lang) {
  try {
    const resp = await fetch('/api/stt-language', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language: lang }),
    });
    const data = await resp.json();
    if (resp.ok) {
      console.log('[KoeGuide] STT language changed to:', lang, data.message);
      // If connected, need to reconnect for new setting to take effect
      if (isConnected) {
        await disconnect();
        await connect();
      }
    } else {
      console.error('STT language change failed:', data.error);
    }
  } catch (e) {
    console.error('STT language change failed:', e);
  }
}

async function loadSttLang() {
  try {
    const resp = await fetch('/api/stt-language');
    const data = await resp.json();
    document.getElementById('stt-lang').value = data.language;
  } catch (e) {
    // default is fine
  }
}

// Initialize
loadFaqData();
loadSttLang();
applyI18n();
