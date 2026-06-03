/**
 * chat.js — WebSocket chat, AI interaction, task completion, and custom task setup.
 * Loaded after bpmn.js and before task.js; uses globals declared in task.html and task.js.
 */

const INITIAL_GREETING_SIGNAL = '[INITIAL_GREETING]';

let lastChatSender = null;
let _customFileContent = '';
let _customTaskConfirmed = false;    // true only after confirmCustomTask() has been called
let _customTaskDescription = '';    // stores the confirmed description for piggyback on send_message

// ─── WebSocket ────────────────────────────────────────────────────────────────

function initWebSocket() {
    socket = io({
        transports: ['websocket', 'polling'],
        timeout: 300000
    });

    socket.on('connect', () => {
        socket.emit('join_task', Object.assign({ task_id: TASK_ID }, _getSettings()));
    });

    socket.on('disconnect', () => {
        hideTypingIndicator();
        addMessageToChat('ai', t('chat.connection_lost'));
    });

    socket.on('task_joined', (data) => {
        if (IS_CUSTOM) {
            // For custom tasks: if the user already confirmed their description
            // (e.g. after a socket reconnection), re-trigger the greeting so the
            // dots don't hang forever waiting for a response that was lost.
            if (_customTaskConfirmed) {
                requestInitialGreeting();
            }
            return;
        }

        // Restore in-progress BPMN draft if available
        if (data.bpmn_draft) {
            modeler.importXML(data.bpmn_draft).catch(err => {
                console.warn('Could not restore BPMN draft:', err);
            });
        }

        // Restore timer: if elapsed_seconds > 0 and we have a time limit, subtract elapsed
        if (TIME_LIMIT_MINUTES > 0 && data.elapsed_seconds > 0) {
            const totalSec = TIME_LIMIT_MINUTES * 60;
            const remainingSec = Math.max(0, totalSec - data.elapsed_seconds);
            if (remainingSec <= 0) {
                // Already expired – submit immediately
                document.getElementById('timerExpiredModal').style.display = 'flex';
            } else {
                _overrideTimerRemaining = remainingSec;
            }
        }

        // Restore previous chat messages silently (no greeting re-fired)
        // Delay slightly so agent_info fires first (AGENT_NAME is available)
        const isResuming = !!(data.chat_log && data.chat_log.length > 0);
        if (isResuming) {
            setTimeout(() => {
                hideTypingIndicator();
                data.chat_log.forEach(msg => addMessageToChat(msg.sender, msg.message));
                enableChatInput();
            }, 50);
        } else {
            requestInitialGreeting();
        }
    });

    socket.on('message_sent', (data) => {
        addMessageToChat(data.sender, data.message);
    });

    socket.on('agent_info', (data) => {
        // Update agent name in chat header and global vars
        if (data.agent_name) {
            const headerEl = document.getElementById('agentChatTitle');
            if (headerEl) headerEl.textContent = data.agent_name;
        }
        if (typeof AGENT_ID !== 'undefined') AGENT_ID = data.agent_id || '';
        if (typeof AGENT_NAME !== 'undefined') AGENT_NAME = data.agent_name || 'Mentor';
        if (typeof MODELING_MODE !== 'undefined') MODELING_MODE = data.modeling_mode || 'none';
        if (typeof CONTROL_MODE !== 'undefined') CONTROL_MODE = data.control_mode || 'human';
        // Show AI modeling indicator if applicable
        const modelingBadge = document.getElementById('agentModelingBadge');
        if (modelingBadge) {
            modelingBadge.style.display = (data.modeling_mode && data.modeling_mode !== 'none') ? '' : 'none';
        }
    });

    socket.on('ai_typing', (data) => {
        // For custom tasks: ignore server-pushed typing events until the user
        // has confirmed their task description. This prevents stray ai_typing
        // events (e.g. from a cached old client reconnecting) from showing dots.
        if (IS_CUSTOM && !_customTaskConfirmed) return;
        if (data.typing) {
            showTypingIndicator();
        } else {
            hideTypingIndicator();
        }
    });

    socket.on('ai_response', (data) => {
        // When the Delegant is mid-loop the server sets looping:true so we keep
        // the typing indicator, locked input and stop button until the loop ends.
        if (!data.looping) hideTypingIndicator();
        addMessageToChat(data.sender, data.message);

        if (!data.looping) {
            enableChatInput();
            hideStopButton();
        }

        // Tracking — AI sent a chat message
        try { if (typeof trackEvent === 'function') trackEvent('chat_message', { dir: 'ai', len: (data.message || '').length, phase: data.phase || '' }); } catch (_) {}

        // Re-enable the completion button in case it was disabled for a review request
        const _cb = document.getElementById('completeTaskBtn');
        const _ct = document.getElementById('completeText');
        const _cs = document.getElementById('completeSpinner');
        if (_cb && _cb.disabled) { _cb.disabled = false; }
        if (_ct) _ct.style.display = 'inline';
        if (_cs) _cs.style.display = 'none';

        // Handle completion signal based on control mode
        if (data.complete === true) {
            if (CONTROL_MODE === 'agent') {
                // Supervisor approved — complete automatically
                completeTask();
            } else if (CONTROL_MODE === 'shared') {
                // Colleague proposes completion — show Approve/Decline buttons
                _showColleagueCompletionPrompt();
            }
            // CONTROL_MODE === 'human': AI opinion has no effect on completion
        }
    });

    socket.on('bpmn_ops', (data) => {
        if (data.ops && (Array.isArray(data.ops) ? data.ops.length > 0 : typeof data.ops === 'object')) {
            executeBpmnOps(data.ops);
        }
    });

    socket.on('completion_result', (data) => {
        hideTypingIndicator();
        // Re-enable the review button
        const completeBtn = document.getElementById('completeTaskBtn');
        const completeText = document.getElementById('completeText');
        const completeSpinner = document.getElementById('completeSpinner');
        if (completeBtn) completeBtn.disabled = false;
        if (completeText) completeText.style.display = 'inline';
        if (completeSpinner) completeSpinner.style.display = 'none';

        if (data.approved) {
            completeTask();
        } else {
            // Show rejection message in chat
            if (data.message) addMessageToChat(data.sender || 'ai', data.message);
        }
    });

    socket.on('mentor_issues', (data) => {
        if (data.issues && data.issues.length > 0) {
            displayIssues(data.issues);
        }
    });

    socket.on('error', (data) => {
        console.error('Socket error:', data);
        const errorKeyMap = {
            auth: 'error.auth',
            timeout: 'error.timeout',
            connection: 'error.connection',
            rate_limit: 'error.rate_limit',
            service_down: 'error.service_down',
        };
        const errKey = data.error_type && errorKeyMap[data.error_type];
        const msg = errKey ? t(errKey) : (data.message || t('error.unexpected'));
        addMessageToChat('ai', `\u26A0\uFE0F ${msg}`);

        hideTypingIndicator();
        enableChatInput();
    });
}

// ─── Greeting ─────────────────────────────────────────────────────────────────

function requestInitialGreeting() {
    // For custom tasks, only proceed if the user has explicitly confirmed their description
    if (typeof IS_CUSTOM !== 'undefined' && IS_CUSTOM && !_customTaskConfirmed) return;

    showTypingIndicator();
    disableChatInput();

    const _greetPayload = Object.assign({
        task_id: TASK_ID,
        message: INITIAL_GREETING_SIGNAL,
        bpmn_xml: ''
    }, _getSettings());
    // For custom tasks: piggyback the description so the server receives it atomically
    // with the greeting request — no separate set_custom_task race condition possible.
    if (IS_CUSTOM && _customTaskDescription) {
        _greetPayload.custom_task_desc = _customTaskDescription;
    }
    socket.emit('send_message', _greetPayload);
}

// ─── Chat ─────────────────────────────────────────────────────────────────────

function sendMessage() {
    const message = elChatInput ? elChatInput.value.trim() : '';
    if (!message) return;

    addMessageToChat('user', message);
    showTypingIndicator();

    if (elChatInput) {
        elChatInput.disabled = true;
        elChatInput.value = '';
    }
    showStopButton();

    getBPMNXML().then(xml => {
        socket.emit('send_message', Object.assign({
            task_id: TASK_ID,
            message: message,
            bpmn_xml: xml
        }, _getSettings()));
    }).catch(err => console.error('[Frontend] Could not read BPMN XML:', err));

    // Tracking — user sent a chat message
    try { if (typeof trackEvent === 'function') trackEvent('chat_message', { dir: 'user', len: message.length }); } catch (_) {}
}

function handleChatKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

// ─── Stop / Send Button ───────────────────────────────────────────────────────

function stopAI() {
    hideTypingIndicator();
    hideStopButton();
    enableChatInput();
    socket.emit('stop_ai', { task_id: TASK_ID });
}

function showStopButton() {
    if (elSendBtn) {
        elSendBtn.disabled = false;
        elSendBtn.classList.add('stop-mode');
        elSendBtn.onclick = stopAI;
    }
    if (elSendText) {
        elSendText.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>';
        elSendText.style.display = 'inline-flex';
    }
    if (elSendSpinner) elSendSpinner.style.display = 'none';
}

function hideStopButton() {
    if (elSendBtn) {
        elSendBtn.classList.remove('stop-mode');
        elSendBtn.onclick = sendMessage;
    }
    if (elSendText) elSendText.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>';
}

function enableChatInput() {
    if (elChatInput) {
        elChatInput.disabled = false;
        elChatInput.placeholder = t('task.chat_placeholder');
        elChatInput.focus();
    }
    if (elSendBtn) elSendBtn.disabled = false;
    hideStopButton();
    // Only re-enable the complete button if the human fully controls completion
    if (typeof CONTROL_MODE === 'undefined' || CONTROL_MODE === 'human') {
        enableCompleteButton();
    }
}

function disableChatInput() {
    if (elChatInput) elChatInput.disabled = true;
    if (elSendBtn) elSendBtn.disabled = true;
}

// ─── Chat Messages & Markdown ─────────────────────────────────────────────────

function addMessageToChat(sender, message) {
    const chatMessages = elChatMessages;
    if (message !== null && message !== undefined && typeof message !== 'string') {
        message = String(message);
    }
    if (!message || message.trim() === '') return;

    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${sender}`;

    const showSender = lastChatSender !== sender;
    lastChatSender = sender;

    const senderDisplayName = sender === 'user'
        ? t('chat.you')
        : (sender === 'system' ? '' : ((typeof AGENT_NAME !== 'undefined' && AGENT_NAME) ? AGENT_NAME : t('chat.mentor')));

    if (showSender && senderDisplayName) {
        const senderDiv = document.createElement('div');
        senderDiv.className = 'message-sender';
        senderDiv.textContent = senderDisplayName;
        messageDiv.appendChild(senderDiv);
    } else {
        messageDiv.classList.add('consecutive');
    }

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.innerHTML = formatMarkdown(message);

    const timestampDiv = document.createElement('div');
    timestampDiv.className = 'message-timestamp';
    timestampDiv.textContent = new Date().toLocaleTimeString('en-US');

    messageDiv.appendChild(contentDiv);
    messageDiv.appendChild(timestampDiv);

    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function formatMarkdown(text) {
    if (!text) return '';

    let formatted = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    formatted = formatted.replace(/__(.+?)__/g, '<strong>$1</strong>');
    formatted = formatted.replace(/\*(.+?)\*/g, '<em>$1</em>');
    formatted = formatted.replace(/_(.+?)_/g, '<em>$1</em>');
    formatted = formatted.replace(/~~(.+?)~~/g, '<s>$1</s>');

    formatted = formatted.replace(/^[\s]*--\s+(.+)$/gm, '<li class="nested-li">$1</li>');
    formatted = formatted.replace(/^[\s]*[-*\u2022]\s+(.+)$/gm, '<li>$1</li>');
    formatted = formatted.replace(/^[\s]*\d+\)\s+(.+)$/gm, '<li>$1</li>');

    formatted = formatted.replace(/(<li[^>]*>.*?<\/li>[\n]*)+/g, (match) => {
        const cleanedMatch = match.replace(/\n/g, '');
        let processed = cleanedMatch.replace(/(<li class="nested-li">.*?<\/li>)+/g, (nestedMatch) => {
            return '<ul class="nested-ul">' + nestedMatch + '</ul>';
        });
        return '<ul>' + processed + '</ul>';
    });

    formatted = formatted.replace(/<\/ul>\n+/g, '</ul>\n');
    formatted = formatted.replace(/\n\n+/g, '<br><br>');
    formatted = formatted.replace(/\n/g, '<br>');

    return formatted;
}

function showTypingIndicator() {
    const existing = document.getElementById('typingIndicator');
    if (existing) return;
    if (!elChatMessages) return;

    const indicator = document.createElement('div');
    indicator.id = 'typingIndicator';
    indicator.className = 'chat-message ai';
    const _agentLabel = (typeof AGENT_NAME !== 'undefined' && AGENT_NAME) ? AGENT_NAME : t('chat.mentor');
    indicator.innerHTML = `
        <div class="message-sender">${_agentLabel}</div>
        <div class="message-content">
            <div class="chat-typing-indicator">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        </div>
    `;

    elChatMessages.appendChild(indicator);
    elChatMessages.scrollTop = elChatMessages.scrollHeight;
}

function hideTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) indicator.remove();
}

// ─── Completion ───────────────────────────────────────────────────────────────

async function requestCompletion() {
    // Supervisor (agent mode) or Colleague (shared mode): send to AI for review first
    if (CONTROL_MODE === 'agent' || CONTROL_MODE === 'shared') {
        const completeBtn = document.getElementById('completeTaskBtn');
        const completeText = document.getElementById('completeText');
        const completeSpinner = document.getElementById('completeSpinner');
        if (completeBtn) completeBtn.disabled = true;
        if (completeText) completeText.style.display = 'none';
        if (completeSpinner) completeSpinner.style.display = 'inline-block';

        const xml = await getBPMNXML();
        socket.emit('request_completion', Object.assign({
            task_id: TASK_ID,
            bpmn_xml: xml
        }, _getSettings()));
        showTypingIndicator();
        return;
    }

    // Human mode: check for critical issues then complete directly
    const hasCriticalIssues = currentIssues.some(issue => {
        const sev = (issue.severity || '').toLowerCase();
        return sev === 'syntax' || sev === 'semantic';
    });

    if (hasCriticalIssues) {
        document.getElementById('completionConfirmModal').style.display = 'flex';
    } else {
        completeTask();
    }
}

function cancelCompletion() {
    document.getElementById('completionConfirmModal').style.display = 'none';
}

function confirmCompletion() {
    document.getElementById('completionConfirmModal').style.display = 'none';
    completeTask();
}

function _showColleagueCompletionPrompt() {
    // Inject a special chat bubble with Approve/Decline buttons
    const chatMessages = document.getElementById('chatMessages');
    if (!chatMessages) { enableCompleteButton(); return; }
    const bubble = document.createElement('div');
    bubble.className = 'chat-message ai colleague-completion-prompt';
    bubble.innerHTML = `
        <div class="message-content">
            <p>${t('chat.colleague_proposes_completion') || 'I think we\'re done! Shall we complete the task?'}</p>
            <div style="display:flex;gap:0.5rem;margin-top:0.5rem;">
                <button class="completion-btn" style="padding:0.3rem 0.8rem;font-size:0.85rem;" onclick="_approveColleagueCompletion(this)">${t('task.approve') || 'Approve'}</button>
                <button class="completion-btn" style="padding:0.3rem 0.8rem;font-size:0.85rem;background:#888;" onclick="_declineColleagueCompletion(this)">${t('task.decline') || 'Decline'}</button>
            </div>
        </div>`;
    chatMessages.appendChild(bubble);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function _approveColleagueCompletion(btn) {
    if (btn && btn.closest('.colleague-completion-prompt')) {
        btn.closest('.colleague-completion-prompt').remove();
    }
    completeTask();
}

function _declineColleagueCompletion(btn) {
    if (btn && btn.closest('.colleague-completion-prompt')) {
        btn.closest('.colleague-completion-prompt').remove();
    }
    // Ask user for reason, then send to AI
    const reason = prompt(t('chat.decline_reason_prompt') || 'Why do you want to continue? (optional)');
    const msg = reason ? reason : (t('chat.decline_default') || 'Let\'s continue working on the model.');
    addMessageToChat('user', msg);
    showTypingIndicator();
    socket.emit('send_message', Object.assign({
        task_id: TASK_ID,
        message: msg,
        bpmn_xml: ''
    }, _getSettings()));
}

function enableCompleteButton() {
    const completeBtn = document.getElementById('completeTaskBtn');
    const completeText = document.getElementById('completeText');
    const completeSpinner = document.getElementById('completeSpinner');
    if (completeBtn) {
        completeBtn.disabled = false;
        if (completeText) completeText.style.display = 'inline';
        if (completeSpinner) completeSpinner.style.display = 'none';
    }
}

async function completeTask() {
    const completeBtn = document.getElementById('completeTaskBtn');
    const completeText = document.getElementById('completeText');
    const completeSpinner = document.getElementById('completeSpinner');

    try {
        if (completeBtn) completeBtn.disabled = true;
        if (completeText) completeText.style.display = 'none';
        if (completeSpinner) completeSpinner.style.display = 'inline-block';

        const xml = await getBPMNXML();

        const response = await fetch('/api/save-bpmn', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_id: TASK_ID, bpmn_xml: xml, sid: socket.id, study_id: typeof STUDY_ID !== 'undefined' ? STUDY_ID : null })
        });

        const data = await response.json();

        if (data.success) {
            window.location.href = data.redirect || '/';
        } else {
            alert(t('task.error_complete') + ': ' + (data.message || ''));
        }
    } catch (err) {
        console.error('Error completing task:', err);
        alert(t('task.error_complete_retry'));
    } finally {
        if (completeBtn) completeBtn.disabled = false;
        if (completeText) completeText.style.display = 'inline';
        if (completeSpinner) completeSpinner.style.display = 'none';
    }
}

async function exportBPMN() {
    const xml = await getBPMNXML();

    const blob = new Blob([xml], { type: 'application/xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${TASK_ID}.bpmn`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ─── Custom Task ──────────────────────────────────────────────────────────────

function handleCustomFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    const uploadBtn = document.getElementById('customUploadBtn');
    if (uploadBtn) uploadBtn.textContent = '📎 ' + file.name;

    const formData = new FormData();
    formData.append('file', file);

    fetch('/api/extract-file-content', { method: 'POST', body: formData })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                _customFileContent = data.content || '';
            } else {
                alert(t('custom.file_read_error') + ': ' + (data.message || ''));
                _customFileContent = '';
                if (uploadBtn) uploadBtn.textContent = t('task.upload_doc');
                const fileInput = document.getElementById('customFileInput');
                if (fileInput) fileInput.value = '';
            }
        })
        .catch(() => {
            alert(t('custom.file_error'));
            _customFileContent = '';
            if (uploadBtn) uploadBtn.textContent = t('task.upload_doc');
        });
}

function confirmCustomTask() {
    const textarea = document.getElementById('customTaskTextarea');
    const typed = textarea ? textarea.value.trim() : '';
    const parts = [];
    if (typed) parts.push(typed);
    if (_customFileContent.trim()) parts.push(_customFileContent.trim());

    const description = parts.join('\n\n');
    if (!description) {
        alert(t('custom.no_desc'));
        return;
    }

    socket.emit('set_custom_task', { task_id: TASK_ID, description: description });

    _customTaskConfirmed = true;    // unlock requestInitialGreeting for this session
    _customTaskDescription = description; // stored so requestInitialGreeting can piggyback it

    // Swap buttons
    const customUploadBtn = document.getElementById('customUploadBtn');
    const customConfirmBtn = document.getElementById('customConfirmBtn');
    if (customUploadBtn) customUploadBtn.style.display = 'none';
    if (customConfirmBtn) customConfirmBtn.style.display = 'none';

    const exportBtn = document.getElementById('exportBtn');
    const completeTaskBtn = document.getElementById('completeTaskBtn');
    if (exportBtn) exportBtn.style.display = '';
    if (completeTaskBtn) completeTaskBtn.style.display = '';

    const taskContent = document.querySelector('.task-content');
    if (taskContent) taskContent.classList.remove('custom-mode');

    const setup = document.getElementById('customTaskSetup');
    if (setup) setup.style.display = 'none';

    const titleEl = document.getElementById('taskTitle');
    if (titleEl) {
        titleEl.textContent = t('custom.title');
        titleEl.style.display = '';
    }

    const descEl = document.getElementById('taskDescription');
    if (descEl) {
        descEl.innerHTML = description.replace(/\n/g, '<br>');
        descEl.style.display = '';
    }

    requestInitialGreeting();
}
