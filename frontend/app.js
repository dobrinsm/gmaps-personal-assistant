// GMaps Personal Assistant - Collaborative Partner Agent Frontend
const API_BASE = window.location.origin.includes('localhost') || window.location.origin.includes('127.0.0.1') 
  ? 'http://127.0.0.1:8000' 
  : window.location.origin;

let currentUserId = localStorage.getItem('gpa_user_id') || 'user_' + Math.random().toString(36).substring(2, 9);
let currentSessionId = localStorage.getItem('gpa_session_id') || 'sess_' + Math.random().toString(36).substring(2, 9);

localStorage.setItem('gpa_user_id', currentUserId);
localStorage.setItem('gpa_session_id', currentSessionId);

// DOM Elements
const chatContainer = document.getElementById('chatContainer');
const chatForm = document.getElementById('chatForm');
const chatInput = document.getElementById('chatInput');
const clarificationBar = document.getElementById('clarificationBar');
const clarificationItems = document.getElementById('clarificationItems');

// Notebook Elements
const nbDestination = document.getElementById('nbDestination');
const nbPreferences = document.getElementById('nbPreferences');
const nbNotes = document.getElementById('nbNotes');
const nbShortlist = document.getElementById('nbShortlist');
const nbShortlistCount = document.getElementById('nbShortlistCount');

// Profile Elements
const profileSummary = document.getElementById('profileSummary');
const profileVibes = document.getElementById('profileVibes');
const profileCuisines = document.getElementById('profileCuisines');
const profileAvoids = document.getElementById('profileAvoids');
const weightAuth = document.getElementById('weightAuth');
const valAuth = document.getElementById('valAuth');
const weightCulinary = document.getElementById('weightCulinary');
const valCulinary = document.getElementById('valCulinary');
const weightAmbiance = document.getElementById('weightAmbiance');
const valAmbiance = document.getElementById('valAmbiance');
const weightValue = document.getElementById('weightValue');
const valValue = document.getElementById('valValue');

// Modal Elements
const uploadModal = document.getElementById('uploadModal');
const btnUploadModal = document.getElementById('btnUploadModal');
const fileInput = document.getElementById('fileInput');
const uploadStatus = document.getElementById('uploadStatus');
const btnResetSession = document.getElementById('btnResetSession');

// Itinerary Map & Export Elements 
const btnOpenInMaps = document.getElementById('btnOpenInMaps');
const btnDownloadKML = document.getElementById('btnDownloadKML');
const btnDownloadCSV = document.getElementById('btnDownloadCSV');
const itineraryHint = document.getElementById('itineraryHint');
const mapEmptyState = document.getElementById('mapEmptyState');
const itineraryStops = document.getElementById('itineraryStops');

const MAPS_DIR_MAX_STOPS = 10; // Google Maps directions stop limit
const CHAT_INPUT_MAX = 5000; // F-20: guard against runaway prompts/costs

// Tab Switching
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    const tabName = btn.getAttribute('data-tab');
    const tabId = tabName === 'notebook' ? 'tabNotebook' : tabName === 'profile' ? 'tabProfile' : 'tabMap';
    document.getElementById(tabId).classList.add('active');
    if (tabName === 'map') {
      // Leaflet needs a re-layout when its container becomes visible
      renderItineraryMap();
      if (itineraryMapInstance) {
        setTimeout(() => itineraryMapInstance.invalidateSize(), 100);
      }
    }
  });
});

// Load Initial Data
window.addEventListener('DOMContentLoaded', () => {
  loadUserProfile();
  loadSessionData();
  replayChatHistory();
});

// ─── Honest wait feedback (F-04 interim, F-08) ───────────────────────
// First responses can take ~30s while Places + Gemini run server-side.
// The static "Thinking…" card read as a frozen app; rotating stages keep
// the wait legible without promising model-specific internals.
const CHAT_WAIT_STAGES = [
  'Understanding your request…',
  'Searching Google Places…',
  'Scoring candidates against your taste profile…',
  'Curating the shortlist…',
];
function startWaitStageRotation(card) {
  const el = card.querySelector('.sender-name span');
  if (!el) return () => {};
  let stage = 0;
  el.textContent = CHAT_WAIT_STAGES[0];
  const timer = setInterval(() => {
    stage = (stage + 1) % CHAT_WAIT_STAGES.length;
    el.textContent = CHAT_WAIT_STAGES[stage];
  }, 6000);
  return () => clearInterval(timer);
}

// ─── Chat history replay (F-03) ─────────────────────────────────────
// The backend already persists every turn (see agent.py save_session_message)
// but the UI never replayed it, so a refresh wiped the conversation while the
// notebook survived — a contradictory, data-loss-looking state. Rebuild the
// visible transcript from the session document on load.
async function replayChatHistory() {
  try {
    const res = await fetch(`${API_BASE}/api/session/${currentSessionId}?user_id=${currentUserId}`);
    if (!res.ok) return;
    const data = await res.json();
    const messages = Array.isArray(data.messages) ? data.messages : [];
    const chatTurns = messages.filter(m =>
      m && (m.role === 'user' || m.role === 'assistant') &&
      (m.content || (Array.isArray(m.recommended_places) && m.recommended_places.length))
    );
    if (!chatTurns.length) return;

    const divider = document.createElement('div');
    divider.className = 'history-divider';
    divider.setAttribute('role', 'separator');
    divider.innerHTML = '<span>Restored conversation from your last visit</span>';
    chatContainer.appendChild(divider);

    chatTurns.forEach(m => {
      if (m.role === 'user') {
        appendUserMessage(m.content || '');
      } else {
        appendAgentResponse({
          message: m.content || '',
          // Stale clarifying questions are not re-asked on replay — the live
          // agent re-issues them when relevant in the next turn.
          clarifying_questions: [],
          places: Array.isArray(m.recommended_places) ? m.recommended_places : []
        }, { isReplay: true });
      }
    });
  } catch (err) {
    // Replay is best-effort: a fresh session must keep working offline.
    console.error('History replay failed:', err);
  }
}

async function loadUserProfile() {
  try {
    const res = await fetch(`${API_BASE}/api/profile/${currentUserId}`);
    if (res.ok) {
      const data = await res.json();
      renderUserProfile(data);
    }
  } catch (err) {
    console.error('Failed to load user profile:', err);
  }
}

async function loadSessionData() {
  try {
    const res = await fetch(`${API_BASE}/api/session/${currentSessionId}?user_id=${currentUserId}`);
    if (res.ok) {
      const data = await res.json();
      if (data.notebook) {
        renderNotebook(data.notebook);
      }
    }
  } catch (err) {
    console.error('Failed to load session:', err);
  }
}

function renderUserProfile(data) {
  const tp = data && data.taste_profile;
  if (!tp) return;
  // F-07: distinguish a not-yet-built profile (backend default) from one the
  // user actually earned by chatting or importing their Takeout.
  if (data.is_default) {
    profileSummary.textContent = 'No taste profile yet. Chat with the agent or import your Google Takeout to build one — the defaults below are starting points, not learned preferences.';
    profileSummary.classList.add('profile-default');
  } else {
    profileSummary.textContent = tp.summary || 'Custom Taste Profile active.';
    profileSummary.classList.remove('profile-default');
  }
  
  // Weights
  const w = tp.weights || {};
  const auth = w.authenticity || 0.85;
  const cul = w.culinary_quality || 0.90;
  const amb = w.scenic_ambiance || 0.80;
  const val = w.value_for_money || 0.75;

  weightAuth.style.width = `${auth * 100}%`;
  valAuth.textContent = auth.toFixed(2);

  weightCulinary.style.width = `${cul * 100}%`;
  valCulinary.textContent = cul.toFixed(2);

  weightAmbiance.style.width = `${amb * 100}%`;
  valAmbiance.textContent = amb.toFixed(2);

  weightValue.style.width = `${val * 100}%`;
  valValue.textContent = val.toFixed(2);

  // Tags
  renderTagList(profileVibes, tp.vibes || []);
  renderTagList(profileCuisines, tp.cuisines || []);
  renderTagList(profileAvoids, tp.avoid || []);
}

function renderTagList(container, tags) {
  container.innerHTML = '';
  tags.forEach(t => {
    const span = document.createElement('span');
    span.className = 'tag-pill';
    span.textContent = t;
    container.appendChild(span);
  });
}

// ─── Display helpers (F-09/F-17) ────────────────────────────────────
// Humanize raw Google price-level enums; keep exports and cards readable.
function humanizePriceLevel(raw) {
  if (!raw) return '';
  const key = String(raw).toUpperCase().replace(/^PRICE_LEVEL_/, '');
  const map = {
    FREE: 'Free',
    INEXPENSIVE: 'Inexpensive ($)',
    MODERATE: 'Moderate ($$)',
    EXPENSIVE: 'Expensive ($$$)',
    VERY_EXPENSIVE: 'Very expensive ($$$$)',
  };
  return map[key] || String(raw).toLowerCase().replace(/_/g, ' ');
}

// Internal notebook keys → human labels (F-17). Unknown keys pass through.
function humanizePrefKey(key) {
  const map = {
    fancy_level: 'Fancy level',
    occasion_vibe: 'Occasion & vibe',
    vibe: 'Vibe',
    occasion: 'Occasion',
    budget: 'Budget',
    dietary: 'Dietary',
    pace: 'Pace',
    group_type: 'Group type',
    transport: 'Transport',
    cuisine: 'Cuisine',
    neighborhood: 'Neighborhood',
  };
  const k = String(key);
  return map[k] || k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function renderNotebook(nb) {
  if (!nb) return;
  currentNotebook = nb; // keep the latest notebook for map/export layer
  nbDestination.textContent = nb.destination || 'Not set';
  
  // Preferences
  const prefs = nb.clarified_preferences || {};
  nbPreferences.innerHTML = '';
  const prefKeys = Object.keys(prefs);
  if (prefKeys.length === 0) {
    nbPreferences.innerHTML = '<span class="empty-hint">Agent will record your preferences here as we converse.</span>';
  } else {
    prefKeys.forEach(k => {
      const span = document.createElement('span');
      span.className = 'tag-pill';
      // F-17: show human labels for internal notebook keys.
      span.textContent = `${humanizePrefKey(k)}: ${prefs[k]}`;
      nbPreferences.appendChild(span);
    });
  }

  // "Learned from your feedback" chips (memory loop made visible)
  renderLearnedChips();
  // F-21: don't render an empty bordered section before feedback exists.
  const learnedSection = document.getElementById('nbLearned');
  if (learnedSection && !learnedSection.innerHTML.trim()) learnedSection.classList.add('empty');

  // Notes
  const notes = nb.itinerary_notes || [];
  nbNotes.innerHTML = '';
  if (notes.length === 0) {
    nbNotes.innerHTML = '<li class="empty-hint">No notes logged yet.</li>';
  } else {
    notes.forEach(n => {
      const li = document.createElement('li');
      li.textContent = n;
      nbNotes.appendChild(li);
    });
  }

  // Shortlist
  const shortlist = nb.shortlist || [];
  nbShortlistCount.textContent = shortlist.length;
  nbShortlist.innerHTML = '';
  if (shortlist.length === 0) {
    nbShortlist.innerHTML = '<div class="empty-hint">Saved recommendations appear here.</div>';
  } else {
    shortlist.forEach(p => {
      const card = document.createElement('div');
      card.className = 'place-card';
      const dualScore = (p.intent_score != null && p.taste_score != null)
        ? `I ${Math.round(p.intent_score)} · T ${Math.round(p.taste_score)} → ${Math.round((p.combined_score ?? 0) * 10) / 10}`
        : (p.taste_match_score != null ? `Match: ${p.taste_match_score}%` : '');
      // F-01 hardening: shortlist names/reasons are external data — escape them.
      card.innerHTML = `
        <div class="place-header">
          <div class="place-name">${escapeHtml(p.name)}</div>
          <div class="place-score">★ ${escapeHtml(p.rating || '4.5')}</div>
        </div>
        ${dualScore ? `<div class="place-scores">${escapeHtml(dualScore)}${p.scored_by === 'heuristic' ? ' <span class="heuristic-tag">heuristic shortlist</span>' : ''}</div>` : ''}
        <div class="place-reason">${escapeHtml(p.match_reason || '')}</div>
      `;
      nbShortlist.appendChild(card);
    });
  }

  // refresh itinerary map layer (no-op until the map tab is opened)
  if (typeof renderItineraryMap === 'function') {
    renderItineraryMap();
  }
}

// Chat Submission
let chatRequestInFlight = false; // F-04a: serialize chat submissions
chatForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (chatRequestInFlight) return; // drop double-submits while a turn is pending
  let text = chatInput.value.trim();
  if (!text) return;
  // F-20: soft input cap — overlong prompts risk timeouts and wasted spend.
  if (text.length > CHAT_INPUT_MAX) {
    text = text.slice(0, CHAT_INPUT_MAX);
    showToast(`Message trimmed to the first ${CHAT_INPUT_MAX} characters.`, 5000);
  }

  chatRequestInFlight = true;
  btnSend.disabled = true;
  chatInput.disabled = true;
  chatInput.value = '';
  chatInput.placeholder = 'Waiting for the agent…';
  appendUserMessage(text);
  clarificationBar.classList.add('hidden');

  // Loading indicator
  const loadingCard = appendLoadingMessage();
  const stopWaitStages = startWaitStageRotation(loadingCard);

  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: currentUserId,
        session_id: currentSessionId,
        message: text
      })
    });

    loadingCard.remove();

    if (res.ok) {
      const data = await res.json();
      appendAgentResponse(data);
      if (data.notebook) {
        renderNotebook(data.notebook);
      }
    } else {
      // F-10: name the failure, restore the user's text so the turn is not lost.
      appendErrorMessage(`The agent couldn't process that (server error ${res.status}). Your message is back in the input box — try sending it again.`);
      chatInput.value = text;
    }
  } catch (err) {
    loadingCard.remove();
    console.error('Chat error:', err);
    // F-10: distinguish offline from server errors; keep the user's text.
    appendErrorMessage('You appear to be offline or the connection dropped. Your message is back in the input box — try again once you\'re connected.');
    chatInput.value = text;
  } finally {
    stopWaitStages();
    chatRequestInFlight = false;
    btnSend.disabled = false;
    chatInput.disabled = false;
    chatInput.placeholder = 'Type your destination, mood, or reply to clarifying questions...';
    chatInput.focus();
  }
});

function appendUserMessage(text) {
  const card = document.createElement('div');
  card.className = 'message-card user';
  card.innerHTML = `
    <div class="avatar">👤</div>
    <div class="content">
      <div class="sender-name">You</div>
      <div class="text"><p>${escapeHtml(text)}</p></div>
    </div>
  `;
  chatContainer.appendChild(card);
  chatContainer.scrollTop = chatContainer.scrollHeight;
}

function appendLoadingMessage() {
  const card = document.createElement('div');
  card.className = 'message-card agent';
  card.innerHTML = `
    <div class="avatar">🤖</div>
    <div class="content">
      <div class="sender-name">Trip Partner <span>Thinking...</span></div>
      <div class="text"><p>This can take 10–30 seconds for a new destination — live Places results are being retrieved and scored.</p></div>
    </div>
  `;
  card.setAttribute('aria-live', 'polite');
  chatContainer.appendChild(card);
  chatContainer.scrollTop = chatContainer.scrollHeight;
  return card;
}

function appendAgentResponse(data, opts = {}) {
  const card = document.createElement('div');
  card.className = 'message-card agent';

  let placesHtml = '';
  if (data.places && data.places.length > 0) {
    placesHtml = '<div class="places-grid">';
    data.places.forEach(p => {
      const isHeuristic = p.scored_by === 'heuristic';
      const scoreDisplay = (p.intent_score != null && p.taste_score != null)
        ? `I ${Math.round(p.intent_score)} · T ${Math.round(p.taste_score)} → ${Math.round((p.combined_score ?? 0) * 10) / 10}`
        : `Match: ${p.taste_match_score || 0}%`;
      // F-02 fix: data-* attributes + delegated listener instead of inline JS.
      // Place context is registered once per place and referenced by token.
      const placeToken = registerFeedbackPlace(p);
      placesHtml += `
        <div class="place-card">
          <div class="place-header">
            <div>
              <div class="place-name">${escapeHtml(p.name)}</div>
              <div class="place-meta">
                <span>⭐ ${p.rating || 'N/A'} (${p.review_count || 0} reviews)</span>
                <span>• ${escapeHtml(p.address || '')}</span>
              </div>
            </div>
            <div class="place-score">${escapeHtml(scoreDisplay)}${isHeuristic ? '<div class="heuristic-tag">heuristic shortlist</div>' : ''}</div>
          </div>
          <div class="place-reason">💡 ${escapeHtml(p.match_reason || '')}</div>
          ${p.price_level ? `<div class="place-price">💵 ${escapeHtml(humanizePriceLevel(p.price_level))}</div>` : ''}
          <div class="place-actions">
            <div class="feedback-buttons">
              <button type="button" class="btn-thumb" data-place-id="${escapeHtml(p.id)}" data-place-name="${escapeHtml(p.name)}" data-feedback-type="like" data-place-token="${placeToken}">👍 Love it</button>
              <button type="button" class="btn-thumb" data-place-id="${escapeHtml(p.id)}" data-place-name="${escapeHtml(p.name)}" data-feedback-type="too_touristy" data-place-token="${placeToken}">🚩 Touristy</button>
              <button type="button" class="btn-thumb" data-place-id="${escapeHtml(p.id)}" data-place-name="${escapeHtml(p.name)}" data-feedback-type="wrong_vibe" data-place-token="${placeToken}">🎭 Wrong Vibe</button>
            </div>
            <a href="${escapeHtml(p.maps_url || '')}" target="_blank" rel="noopener" class="maps-link">Open in Maps ↗</a>
          </div>
        </div>
      `;
    });
    placesHtml += '</div>';
  }

  card.innerHTML = `
    <div class="avatar">🤖</div>
    <div class="content">
      <div class="sender-name">Trip Partner</div>
      <div class="text">${markedParse(data.message || '')}</div>
      ${placesHtml}
    </div>
  `;
  chatContainer.appendChild(card);
  chatContainer.scrollTop = chatContainer.scrollHeight;

  // Handle Clarifying Questions (suppressed on history replay — stale
  // questions must not re-open the dock for a turn that already happened).
  if (!opts.isReplay && data.clarifying_questions && data.clarifying_questions.length > 0) {
    clarificationItems.innerHTML = '';
    data.clarifying_questions.forEach(q => {
      const qDiv = document.createElement('div');
      qDiv.className = 'clarification-item';
      // F-16: clarifying questions are interactive — make them keyboard
      // operable (button role + focus + Enter/Space activation).
      qDiv.setAttribute('role', 'button');
      qDiv.setAttribute('tabindex', '0');
      qDiv.setAttribute('aria-label', `Use this question in your reply: ${q}`);
      qDiv.innerHTML = `<strong>❓ ${escapeHtml(q)}</strong>`;
      const applyPrefill = () => {
        // F-14: don't clobber what the user is typing — append instead.
        const prefix = `Regarding "${q}": `;
        chatInput.value = chatInput.value.trim()
          ? `${chatInput.value.trim()} ${prefix}`
          : prefix;
        chatInput.focus();
        chatInput.setSelectionRange(chatInput.value.length, chatInput.value.length);
      };
      qDiv.onclick = applyPrefill;
      qDiv.onkeydown = (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') {
          ev.preventDefault();
          applyPrefill();
        }
      };
      clarificationItems.appendChild(qDiv);
    });
    clarificationBar.classList.remove('hidden');
  }
}

function appendErrorMessage(msg) {
  const card = document.createElement('div');
  card.className = 'message-card agent';
  card.innerHTML = `
    <div class="avatar">⚠️</div>
    <div class="content" style="border-color: #ef4444;">
      <div class="sender-name">System</div>
      <div class="text"><p style="color: #fca5a5;">${escapeHtml(msg)}</p></div>
    </div>
  `;
  chatContainer.appendChild(card);
  chatContainer.scrollTop = chatContainer.scrollHeight;
}

// Interactive Feedback Loop
// F-02 fix: place context lives in a registry keyed by a token; buttons carry
// data-* attributes. The previous inline-JS handler template produced
// malformed HTML (the embedded JSON's opening quote terminated the HTML
// attribute), so every feedback button threw a SyntaxError and the loop
// never fired. Guards in tests/test_frontend_security.js keep inline
// feedback handlers from returning.
const feedbackPlaceRegistry = new Map();
let feedbackPlaceTokenCounter = 0;
function registerFeedbackPlace(place) {
  const token = 'fbp_' + (++feedbackPlaceTokenCounter);
  feedbackPlaceRegistry.set(token, {
    types: (place && Array.isArray(place.types)) ? place.types.slice(0, 10) : [],
    price_level: (place && place.price_level) || null,
    location: (place && place.location) || null,
  });
  return token;
}

// Single delegated listener: covers all current and future feedback buttons.
document.addEventListener('click', (e) => {
  const target = e.target;
  const btn = target && target.closest ? target.closest('.btn-thumb') : null;
  if (!btn || !btn.dataset || !btn.dataset.placeId) return;
  sendFeedback(
    btn.dataset.placeId,
    btn.dataset.placeName || '',
    btn.dataset.feedbackType || 'like',
    feedbackPlaceRegistry.get(btn.dataset.placeToken) || null
  );
});
async function sendFeedback(placeId, placeName, feedbackType, place) {
  try {
    const res = await fetch(`${API_BASE}/api/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: currentUserId,
        session_id: currentSessionId,
        place_id: placeId,
        place_name: placeName,
        feedback_type: feedbackType,
        // place context lets the memory loop generalize the signal
        place_types: (place && Array.isArray(place.types)) ? place.types.slice(0, 10) : null,
        price_level: (place && place.price_level) ? place.price_level : null,
        location: (place && place.location) ? place.location : null
      })
    });
    if (res.ok) {
      showToast(`Feedback recorded: "${feedbackType}". Taste profile adapted — future picks will reflect it.`);
      loadUserProfile();
      loadSessionData();
      // show the learned-preferences chips immediately
      renderLearnedChips();
    } else {
      showToast('⚠️ Feedback failed to save. Please try again.');
    }
  } catch (err) {
    console.error('Feedback failed:', err);
    showToast('⚠️ Feedback failed: network error.');
  }
}

function sendPrompt(text) {
  chatInput.value = text;
  chatForm.dispatchEvent(new Event('submit'));
}

// Modal Handling
let lastFocusedBeforeModal = null;
btnUploadModal.onclick = () => {
  // F-16: remember focus, mark the dialog, focus the first control, and
  // restore focus on close (Escape or button) — previously the dialog was
  // unreachable/unescapable by keyboard.
  lastFocusedBeforeModal = document.activeElement;
  uploadModal.classList.remove('hidden');
  uploadStatus.classList.add('hidden');
  fileInput.value = '';
  const closeBtn = uploadModal.querySelector('.btn-close');
  if (closeBtn) closeBtn.focus();
};
function closeModal() {
  uploadModal.classList.add('hidden');
  if (lastFocusedBeforeModal && lastFocusedBeforeModal.focus) lastFocusedBeforeModal.focus();
}
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !uploadModal.classList.contains('hidden')) {
    closeModal();
  }
});

// Handle Drag & Drop on drop-zone
const dropZone = document.getElementById('dropZone');
if (dropZone) {
  ['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.style.borderColor = 'var(--accent-blue)';
    }, false);
  });

  ['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.style.borderColor = 'var(--border-color)';
    }, false);
  });

  dropZone.addEventListener('drop', (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files && files.length > 0) {
      handleFileUpload(files[0]);
    }
  });
}

fileInput.addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (file) handleFileUpload(file);
});

async function handleFileUpload(file) {
  uploadStatus.classList.remove('hidden');
  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch(`${API_BASE}/api/upload-takeout?user_id=${currentUserId}`, {
      method: 'POST',
      body: formData
    });
    uploadStatus.classList.add('hidden');
    if (res.ok) {
      const data = await res.json();
      closeModal();
      loadUserProfile();
      // F-06: blocking alert() froze the whole page; the result is now a
      // non-blocking toast plus a jump to the Profile tab so the freshly
      // built profile is actually visible where it happened.
      showToast(`✅ Analyzed ${data.count} saved place${data.count === 1 ? '' : 's'} — taste profile updated.`, 6000);
      const profileTabBtn = document.querySelector('.tab-btn[data-tab="profile"]');
      if (profileTabBtn) profileTabBtn.click();
    } else {
      const errData = await res.json().catch(() => ({}));
      showToast(`⚠️ ${friendlyUploadError(res.status, errData.detail)}`, 8000);
    }
  } catch (err) {
    uploadStatus.classList.add('hidden');
    console.error('Upload network error:', err);
    showToast('⚠️ Upload failed — network error. Check your connection and try again.', 8000);
  }
}

// F-06 companion: translate backend/JSON internals into user-actionable copy.
function friendlyUploadError(status, detail) {
  const d = String(detail || '');
  if (d.includes('No saved places found')) {
    return 'No saved places found in that file. Export "Saved places" from Google Takeout, then upload the .zip or the Saved Places.json inside it.';
  }
  if (d.includes('Expecting value') || d.includes('Failed to process takeout export')) {
    return 'That file doesn\'t look like a Google Takeout export. Upload the Takeout .zip (or Saved Places.json / Want to go.csv from inside it).';
  }
  if (status === 413) {
    return 'That file is too large. Try uploading the Saved Places.json from inside your Takeout archive instead of the full .zip.';
  }
  return `Upload failed (${status}). Please check the file and try again.`;
}

btnResetSession.onclick = () => {
  // F-06: native confirm() blocks the page and is inconsistent across
  // platforms; a lightweight in-page confirmation keeps the flow visible.
  if (!btnResetSession.dataset.confirming) {
    btnResetSession.dataset.confirming = '1';
    btnResetSession.classList.add('confirming');
    const label = btnResetSession.querySelector('span:last-child') || btnResetSession;
    btnResetSession.dataset.originalLabel = label.textContent;
    label.textContent = 'Sure? Click again';
    showToast('Click Reset again to start a fresh session. This clears the conversation view (your notebook data for this session stays in history).', 6000);
    setTimeout(() => {
      delete btnResetSession.dataset.confirming;
      btnResetSession.classList.remove('confirming');
      if (btnResetSession.dataset.originalLabel && label) label.textContent = btnResetSession.dataset.originalLabel;
    }, 6000);
    return;
  }
  delete btnResetSession.dataset.confirming;
  btnResetSession.classList.remove('confirming');
  currentSessionId = 'sess_' + Math.random().toString(36).substring(2, 9);
  localStorage.setItem('gpa_session_id', currentSessionId);
  window.location.reload();
};

// Utilities
function escapeHtml(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return String(text).replace(/[&<>"']/g, m => map[m]);
}

// ─── Safe, minimal markdown → HTML for trusted-length agent text. ───
// SECURITY (F-01): text is HTML-escaped FIRST, so any markup in model output
// renders inert. Only the three markdown constructs the agent actually emits
// are then translated: **bold**, *italic*, line breaks. Links/bullets are
// intentionally left as plain text rather than parsed into live elements.
function markedParse(text) {
  const escaped = escapeHtml(String(text ?? ''));
  return escaped
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>');
}

// ════════════════════════════════════════════════════════════════════
// ══ Itinerary: Map + Export ══
// Itinerary map + export layer (client-side generation).
// Shortlist order = itinerary order; all generation is client-side.
// ════════════════════════════════════════════════════════════════════

let currentNotebook = null;
let itineraryMapInstance = null; // Leaflet map instance
const itineraryMarkers = [];    // { key, marker, place }

function scoreColor(score) {
  const s = Number(score) || 0;
  if (s >= 8) return "#22c55e";
  if (s >= 6.5) return "#84cc16";
  if (s >= 5) return "#f97316";
  if (s >= 3) return "#eab308";
  return "#71717a";
}

function placeKey(p) {
  if (p.lat != null && p.lng != null) return `geo:${p.lat},${p.lng}`;
  return `name:${(p.name || "").toLowerCase()}`;
}

function shortlistPlaces(nb) {
  return (nb && Array.isArray(nb.shortlist)) ? nb.shortlist : [];
}

function hasCoords(p) {
  return p != null && p.lat != null && p.lng != null && !Number.isNaN(Number(p.lat)) && !Number.isNaN(Number(p.lng));
}

function mapsHrefFor(p) {
  if (p.maps_url) return p.maps_url;
  if (hasCoords(p)) return `https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lng}`;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(p.name || "")}`;
}

function updateExportButtons() {
  const places = shortlistPlaces(currentNotebook);
  const any = places.length > 0;
  if (btnOpenInMaps) btnOpenInMaps.disabled = !any;
  if (btnDownloadKML) btnDownloadKML.disabled = !any;
  if (btnDownloadCSV) btnDownloadCSV.disabled = !any;
}

// ─── Google Maps multi-stop directions (cap 10 stops) ───────────────
function buildMapsDirUrl(places, maxStops = MAPS_DIR_MAX_STOPS) {
  const stops = places.slice(0, maxStops);
  const parts = stops.map((p) => {
    if (hasCoords(p)) return `${p.lat},${p.lng}`;
    return encodeURIComponent(`${p.name || ""} ${p.address || ""}`.trim());
  });
  return `https://www.google.com/maps/dir/${parts.join("/")}`;
}

function openSelectedInMaps() {
  const places = shortlistPlaces(currentNotebook);
  if (!places.length) return;
  const overflow = places.length > MAPS_DIR_MAX_STOPS;
  if (overflow) {
    showToast(`⚠️ Directions limited to ~${MAPS_DIR_MAX_STOPS} stops. Opening first ${MAPS_DIR_MAX_STOPS} of ${places.length}. Use KML for the full set.`);
  }
  window.open(buildMapsDirUrl(places), "_blank", "noopener");
}

// ─── KML (full set, skips places without coordinates) ───────────────
function buildKML(places) {
  const sorted = [...places].sort((a, b) => (b.combined_score || b.taste_match_score || 0) - (a.combined_score || a.taste_match_score || 0));
  let kml = `<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n<name>Itinerary — GMaps Personal Assistant</name>\n`;
  let skipped = 0;
  for (const p of sorted) {
    if (!hasCoords(p)) { skipped++; continue; } // skip blank pins — cleaner My Maps import
    const score = Math.round(p.combined_score || p.taste_match_score || 0);
    const title = `(${score}) ${p.name || "Place"}`;
    kml += `<Placemark>\n<name><![CDATA[${title}]]></name>\n`;
    const desc = [
      p.match_reason || "",
      p.intent_score != null ? `Intent: ${p.intent_score}/10` : "",
      p.taste_score != null ? `Taste: ${p.taste_score}/10` : "",
      p.rating != null ? `Google: ${p.rating}` : "",
      humanizePriceLevel(p.price_level), // F-09: no raw enums in KML
      p.address || "",
      p.maps_url || "",
    ].filter(Boolean).join("\n");
    if (desc) kml += `<description><![CDATA[${desc}]]></description>\n`;
    kml += `<Point><coordinates>${p.lng},${p.lat},0</coordinates></Point>\n</Placemark>\n`;
  }
  kml += `</Document>\n</kml>`;
  return { kml, skipped };
}

function downloadKML() {
  const places = shortlistPlaces(currentNotebook);
  if (!places.length) return;
  const { kml, skipped } = buildKML(places);
  downloadFile(kml, "itinerary-places.kml", "application/vnd.google-earth.kml+xml");
  if (skipped > 0) {
    showToast(`⚠️ Skipped ${skipped} place(s) with no coordinates in KML.`);
  }
}

// ─── CSV (RFC4180 quoting incl. dual scores) ─────
function csvEscape(value) {
  return `"${String(value ?? "").replace(/"/g, '""').replace(/\r?\n/g, " ")}"`;
}

function buildCSV(places) {
  const sorted = [...places].sort((a, b) => (b.combined_score || b.taste_match_score || 0) - (a.combined_score || a.taste_match_score || 0));
  let csv = "Name,Score,IntentScore,TasteScore,ScoredBy,Rating,Price,Address,GoogleMaps,Lat,Lng,Id\n";
  for (const p of sorted) {
    const fields = [
      p.name || "",
      p.combined_score ?? p.taste_match_score ?? "",
      p.intent_score ?? "",
      p.taste_score ?? "",
      p.scored_by || "llm",
      p.rating ?? "",
      // F-09: human-readable price in exports instead of raw enums.
      humanizePriceLevel(p.price_level),
      p.address || "",
      p.maps_url || mapsHrefFor(p),
      p.lat ?? "",
      p.lng ?? "",
      p.id || "",
    ];
    csv += fields.map(csvEscape).join(",") + "\n";
  }
  return csv;
}

function downloadCSV() {
  const places = shortlistPlaces(currentNotebook);
  if (!places.length) return;
  downloadFile(buildCSV(places), "itinerary-places.csv", "text/csv");
}

function downloadFile(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ─── Map rendering ──────────────────────────────────────────────────
function renderItineraryMap() {
  const mapEl = document.getElementById('itineraryMap');
  if (!mapEl || typeof L === 'undefined') return;

  const places = shortlistPlaces(currentNotebook).filter(hasCoords);

  if (itineraryMapInstance) {
    itineraryMapInstance.remove();
    itineraryMapInstance = null;
    itineraryMarkers.length = 0;
  }

  if (!places.length) {
    mapEl.innerHTML = '';
    if (mapEmptyState) mapEmptyState.classList.remove('hidden');
    renderItineraryStops();
    updateExportButtons();
    return;
  }
  if (mapEmptyState) mapEmptyState.classList.add('hidden');

  itineraryMapInstance = L.map(mapEl, { scrollWheelZoom: false });
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    maxZoom: 19,
  }).addTo(itineraryMapInstance);

  const bounds = [];
  places.forEach((p, idx) => {
    const key = placeKey(p);
    const order = idx + 1;
    const score = Math.round(p.combined_score || p.taste_match_score || 0);
    const color = scoreColor(p.combined_score || p.taste_match_score || 0);
    const icon = L.divIcon({
      className: "custom-marker-wrap",
      html: `<div class="custom-marker" style="background:${color}" title="${escapeHtml(p.name || "")}"><span>${order}</span></div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 28],
      popupAnchor: [0, -24],
    });
    const marker = L.marker([Number(p.lat), Number(p.lng)], { icon }).addTo(itineraryMapInstance);
    const popupHtml = `
      <strong>${escapeHtml(p.name || "")}</strong><br>
      <span style="color:${color}">★ ${score}/10</span>
      ${p.intent_score != null ? ` · I ${Math.round(p.intent_score)}` : ""}
      ${p.taste_score != null ? ` · T ${Math.round(p.taste_score)}` : ""}
      ${p.rating != null ? `<br>⭐ ${p.rating}` : ""}
      ${p.match_reason ? `<br>${escapeHtml(p.match_reason)}` : ""}
      <br><a href="${escapeHtml(mapsHrefFor(p))}" target="_blank" rel="noopener">Open in Maps →</a>
    `;
    marker.bindPopup(popupHtml);
    marker.on("click", () => highlightStop(key, { openPopup: true, scrollCard: true }));
    itineraryMarkers.push({ key, marker, place: p });
    bounds.push([Number(p.lat), Number(p.lng)]);
  });

  if (bounds.length === 1) itineraryMapInstance.setView(bounds[0], 14);
  else itineraryMapInstance.fitBounds(bounds, { padding: [40, 40] });

  renderItineraryStops();
  updateExportButtons();
}

function renderItineraryStops() {
  if (!itineraryStops) return;
  const places = shortlistPlaces(currentNotebook);
  itineraryStops.innerHTML = '';
  if (!places.length) return;
  places.forEach((p, idx) => {
    const key = placeKey(p);
    const card = document.createElement('div');
    card.className = 'stop-card';
    card.setAttribute('data-place-key', key);
    card.innerHTML = `
      <span class="stop-order">${idx + 1}</span>
      <div class="stop-body">
        <div class="stop-name">${escapeHtml(p.name || "Place")}</div>
        <div class="stop-meta">
          ${p.intent_score != null ? `<span class="score-chip">I ${Math.round(p.intent_score)}</span>` : ""}
          ${p.taste_score != null ? `<span class="score-chip">T ${Math.round(p.taste_score)}</span>` : ""}
          ${p.rating != null ? `<span>⭐ ${p.rating}</span>` : ""}
          ${!hasCoords(p) ? `<span class="no-coords">no coords — not on map</span>` : ""}
        </div>
      </div>
      <a class="maps-link" href="${escapeHtml(mapsHrefFor(p))}" target="_blank" rel="noopener">Maps ↗</a>
    `;
    card.addEventListener('click', () => highlightStop(key, { openPopup: true, scrollCard: false }));
    itineraryStops.appendChild(card);
  });
}

function highlightStop(key, { openPopup = true, scrollCard = true } = {}) {
  itineraryStops.querySelectorAll('.stop-card').forEach((el) => {
    el.classList.toggle('highlighted', el.getAttribute('data-place-key') === key);
    if (scrollCard && el.getAttribute('data-place-key') === key) {
      el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  });
  const entry = itineraryMarkers.find((m) => m.key === key);
  if (entry && openPopup && itineraryMapInstance) {
    itineraryMapInstance.panTo([Number(entry.place.lat), Number(entry.place.lng)]);
    entry.marker.openPopup();
  }
}

// ─── Export button wiring ───────────────────────────────────────────
if (btnOpenInMaps) btnOpenInMaps.addEventListener('click', openSelectedInMaps);
if (btnDownloadKML) btnDownloadKML.addEventListener('click', downloadKML);
if (btnDownloadCSV) btnDownloadCSV.addEventListener('click', downloadCSV);

// Non-blocking toast (replaces blocking alert() for feedback/export notices)
function showToast(message, durationMs = 4000) {
  let toastHost = document.getElementById('toastHost');
  if (!toastHost) {
    toastHost = document.createElement('div');
    toastHost.id = 'toastHost';
    // F-16 companion: toasts are status changes — announce them politely.
    toastHost.setAttribute('role', 'status');
    toastHost.setAttribute('aria-live', 'polite');
    document.body.appendChild(toastHost);
  }
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  toastHost.appendChild(toast);
  setTimeout(() => toast.classList.add('visible'), 10);
  setTimeout(() => {
    toast.classList.remove('visible');
    setTimeout(() => toast.remove(), 300);
  }, durationMs);
}

// ─── "Learned from your feedback" chips ─────────────────────────
// The memory loop made visible: renders deterministic chips from the
// backend-computed avoid/like patterns — never invents data.
async function renderLearnedChips() {
  const container = document.getElementById('nbLearned');
  if (!container) return;
  try {
    const res = await fetch(`${API_BASE}/api/feedback-summary?user_id=${encodeURIComponent(currentUserId)}&session_id=${encodeURIComponent(currentSessionId)}`);
    if (!res.ok) { container.innerHTML = ''; return; }
    const data = await res.json();
    const chips = [];
    (data.avoid_patterns || []).forEach(p => chips.push({ text: p, cls: 'learned-avoid' }));
    (data.like_patterns || []).forEach(p => chips.push({ text: p, cls: 'learned-like' }));
    if (!chips.length) { container.innerHTML = ''; return; }
    container.innerHTML = '<div class="learned-title">🧠 Learned from your feedback</div>';
    const wrap = document.createElement('div');
    wrap.className = 'tags-container';
    chips.forEach(c => {
      const span = document.createElement('span');
      span.className = `tag-pill ${c.cls}`;
      span.textContent = c.text;
      wrap.appendChild(span);
    });
    container.appendChild(wrap);
  } catch (err) {
    console.error('Learned chips failed:', err);
  }
}
