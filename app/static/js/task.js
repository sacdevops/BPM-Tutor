/**
 * task.js — Page initialisation, shared settings helper, and autosave.
 * Loaded last (after bpmn.js and chat.js); all functions defined in those
 * files are already in the global scope by the time DOMContentLoaded fires.
 *
 * Globals declared by task.html inline script:
 *   TASK_ID, IS_CUSTOM, TIME_LIMIT_MINUTES, STUDY_ID
 *   modeler, socket, _overrideTimerRemaining
 */

let _bpmnDirty = false;
const MODELER_INIT_DELAY_MS = 1000;

// Cached DOM references — populated in DOMContentLoaded
let elSendBtn = null;
let elSendText = null;
let elSendSpinner = null;
let elChatInput = null;
let elChatMessages = null;

function _getSettings() {
    return {
        api_key: localStorage.getItem('bpm-tutor-api-key') || '',
        model: localStorage.getItem('bpm-tutor-model') || '',
        lang: localStorage.getItem('bpm-tutor-lang') || 'en',
        base_url: localStorage.getItem('bpm-tutor-base-url') || '',
        agent_id: (typeof AGENT_ID !== 'undefined' ? AGENT_ID : '') || '',
    };
}

// ─── Initialization ───────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    elSendBtn = document.getElementById('sendBtn');
    elSendText = document.getElementById('sendText');
    elSendSpinner = document.getElementById('sendSpinner');
    elChatInput = document.getElementById('chatInput');
    elChatMessages = document.getElementById('chatMessages');

    initBPMN();
    updateZoomLevel();
    initWebSocket();

    // Set completion button label/behavior based on agent control_mode
    const completeBtn = document.getElementById('completeTaskBtn');
    const completeText = document.getElementById('completeText');
    if (completeBtn) {
        if (CONTROL_MODE === 'agent') {
            // Supervisor — user requests a review; button visible but labelled accordingly
            if (completeText) completeText.setAttribute('data-i18n', 'task.request_review');
            if (completeText) completeText.textContent = 'Request Review';
        } else if (CONTROL_MODE === 'shared') {
            // Colleague — user can request completion; button starts enabled
            if (completeText) completeText.setAttribute('data-i18n', 'task.request_completion');
            if (completeText) completeText.textContent = 'Request Completion';
        }
    }

    // Chat is always disabled at startup.
    // For normal tasks: show dots immediately (greeting requested right after task_joined).
    // For custom tasks: dots are NOT shown — chat stays dark until the user
    // confirms their task description on the left and requestInitialGreeting() fires.
    disableChatInput();
    if (!IS_CUSTOM) {
        showTypingIndicator();
    }

    setTimeout(() => {
        if (modeler) {
            const eventBus = modeler.get('eventBus');
            eventBus.on('commandStack.changed', () => {
                if (currentIssues.length > 0) {
                    clearIssues();
                }
                _bpmnDirty = true;
            });
        }
    }, MODELER_INIT_DELAY_MS);

    // ── Periodic autosave every 5 seconds ─────────────────────────────────────
    setInterval(() => {
        if (!_bpmnDirty || !socket || !socket.connected) return;
        _bpmnDirty = false;
        getBPMNXML().then(xml => {
            fetch('/api/auto-save-bpmn', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_id: TASK_ID, bpmn_xml: xml, sid: socket.id })
            }).catch(() => { _bpmnDirty = true; }); // retry next cycle on failure
        }).catch(() => {});
    }, 5000);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && activeIssuePopup) {
            closeIssueDetailPopup();
        }
    });

    // ── Interaction Tracking ───────────────────────────────────────────────────
    if (STUDY_ID && TRACKING_CONFIG && TRACKING_CONFIG.enabled) {
        _initTracking(TRACKING_CONFIG);
    }
});

// ─── Tracking Module ──────────────────────────────────────────────────────────

let _trackBatch = [];
let _trackSessionStart = null;
let _trackBatchSeq = 0;
let _trackEnabled = {};

function _initTracking(cfg) {
    const allowed = new Set(cfg.events || []);
    _trackEnabled = allowed;
    _trackSessionStart = new Date().toISOString();

    const push = (type, extra) => {
        if (!allowed.has(type)) return;
        const now = Date.now();
        _trackBatch.push({ ts: new Date(now).toISOString(), type, ...extra });
    };

    // ── Mouse move (throttled — max 10 per second) ──────────────────────────
    if (allowed.has('mousemove')) {
        let _lastMove = 0;
        document.addEventListener('mousemove', (e) => {
            const now = Date.now();
            if (now - _lastMove < 100) return;
            _lastMove = now;
            push('mousemove', { x: e.clientX, y: e.clientY });
        }, { passive: true });
    }

    // ── Clicks ──────────────────────────────────────────────────────────────
    if (allowed.has('click')) {
        document.addEventListener('click', (e) => {
            push('click', {
                x: e.clientX, y: e.clientY,
                target: e.target ? (e.target.id || e.target.tagName.toLowerCase()) : ''
            });
        }, { passive: true });
    }

    // ── Chat focus / blur ────────────────────────────────────────────────────
    if (allowed.has('chat_focus')) {
        const chatInput = document.getElementById('chatInput');
        if (chatInput) {
            chatInput.addEventListener('focus', () => push('chat_focus', { state: 'focus' }));
            chatInput.addEventListener('blur',  () => push('chat_focus', { state: 'blur'  }));
        }
    }

    // ── BPMN events (shape.added / removed / moved) ──────────────────────────
    setTimeout(() => {
        if (!modeler) return;
        const eventBus = modeler.get('eventBus');
        if (allowed.has('bpmn_add')) {
            eventBus.on('shape.added', (event) => {
                push('bpmn_add', { element_id: event.element.id, type: event.element.type, source: 'user' });
            });
        }
        if (allowed.has('bpmn_remove')) {
            eventBus.on('shape.removed', (event) => {
                push('bpmn_remove', { element_id: event.element.id, type: event.element.type, source: 'user' });
            });
        }
        if (allowed.has('bpmn_move')) {
            eventBus.on('shape.move.end', (event) => {
                push('bpmn_move', {
                    element_id: event.shape.id, type: event.shape.type,
                    x: event.shape.x, y: event.shape.y, source: 'user'
                });
            });
        }
    }, MODELER_INIT_DELAY_MS);

    // ── Flush every 5 seconds ────────────────────────────────────────────────
    setInterval(() => {
        if (_trackBatch.length === 0) return;
        const events = _trackBatch.splice(0, _trackBatch.length);
        fetch(`/study/${STUDY_ID}/track`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _getCSRFToken() },
            body: JSON.stringify({
                task_id: TASK_ID,
                session_start: _trackSessionStart,
                batch_seq: _trackBatchSeq++,
                events,
            })
        }).then(r => {
            if (!r.ok) {
                // Server rejected (e.g. 400/403/500) — put events back for retry
                _trackBatch.unshift(...events);
            }
        }).catch(() => {
            // Network error — put events back for retry next cycle
            _trackBatch.unshift(...events);
        });
    }, 5000);
}

/** Push a tracking event from outside the module (e.g. bpmn.js or chat.js). */
function trackEvent(type, extra) {
    if (!_trackEnabled.has || !_trackEnabled.has(type)) return;
    _trackBatch.push({ ts: new Date().toISOString(), type, ...extra });
}

function _getCSRFToken() {
    const el = document.querySelector('meta[name="csrf-token"]') ||
               document.querySelector('input[name="csrf_token"]');
    return el ? (el.getAttribute('content') || el.value) : '';
}
