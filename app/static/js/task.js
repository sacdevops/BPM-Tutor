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

    if (!IS_CUSTOM) {
        showTypingIndicator();
        disableChatInput();
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
});
