/**
 * Task Page JavaScript — BPM-Tutor (Mentor Teaching Environment)
 * Handles BPMN.io modeler, WebSocket chat with Mentor, issue overlays, zoom, export
 */

function initBPMN() {
    modeler = new BpmnJS({
        container: '#bpmn-canvas',
        keyboard: {
            bindTo: document
        }
    });

    const initialBPMN = `<?xml version="1.0" encoding="UTF-8"?>
    <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                      xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                      xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                      id="Definitions_1"
                      targetNamespace="http://bpmn.io/schema/bpmn">
      <bpmn:process id="Process_1" isExecutable="false">
      </bpmn:process>
      <bpmndi:BPMNDiagram id="BPMNDiagram_1">
        <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_1">
        </bpmndi:BPMNPlane>
      </bpmndi:BPMNDiagram>
    </bpmn:definitions>`;

    modeler.importXML(initialBPMN).catch(err => {
        console.error('Failed to load BPMN diagram', err);
    });
}

function getBPMNXML() {
    return new Promise((resolve, reject) => {
        modeler.saveXML({ format: true }).then(result => {
            resolve(result.xml);
        }).catch(err => {
            reject(err);
        });
    });
}

let lastChatSender = null;

const MODELER_INIT_DELAY_MS = 1000;
const INITIAL_GREETING_SIGNAL = '[INITIAL_GREETING]';

function _getSettings() {
    return {
        api_key: localStorage.getItem('bpm-tutor-api-key') || '',
        model: localStorage.getItem('bpm-tutor-model') || '',
        lang: localStorage.getItem('bpm-tutor-lang') || 'en',
    };
}

// Cached DOM references
let elSendBtn = null;
let elSendText = null;
let elSendSpinner = null;
let elChatInput = null;
let elChatMessages = null;

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
        if (IS_CUSTOM) return;
        requestInitialGreeting();
    });

    socket.on('message_sent', (data) => {
        addMessageToChat(data.sender, data.message);
    });

    socket.on('ai_typing', (data) => {
        if (data.typing) {
            showTypingIndicator();
        } else {
            hideTypingIndicator();
        }
    });

    socket.on('ai_response', (data) => {
        hideTypingIndicator();
        addMessageToChat(data.sender, data.message);
        enableChatInput();
        hideStopButton();
    });

    socket.on('mentor_issues', (data) => {
        if (data.issues && data.issues.length > 0) {
            displayIssues(data.issues);
        }
    });

    socket.on('error', (data) => {
        console.error('Socket error:', data);
        const errorMessages = {
            auth: { en: 'Invalid or expired API key. Please check your settings.', de: 'Ungültiger oder abgelaufener API-Schlüssel. Bitte überprüfe deine Einstellungen.' },
            timeout: { en: 'Request timed out. The AI service may be overloaded.', de: 'Zeitüberschreitung. Der KI-Dienst ist möglicherweise überlastet.' },
            connection: { en: 'Cannot connect to the AI service. Please check your internet connection.', de: 'Verbindung zum KI-Dienst nicht möglich. Bitte überprüfe deine Internetverbindung.' },
            rate_limit: { en: 'Rate limit exceeded. Please wait a moment and try again.', de: 'Rate-Limit überschritten. Bitte warte einen Moment und versuche es erneut.' },
            service_down: { en: 'The AI service is temporarily unavailable. Please try again later.', de: 'Der KI-Dienst ist vorübergehend nicht verfügbar. Bitte versuche es später erneut.' },
        };
        const lang = localStorage.getItem('bpm-tutor-lang') || 'en';
        const errType = data.error_type;
        let msg;
        if (errType && errorMessages[errType]) {
            msg = errorMessages[errType][lang] || errorMessages[errType]['en'];
        } else {
            msg = data.message || 'An unexpected error occurred.';
        }
        addMessageToChat('ai', `\u26a0\ufe0f ${msg}`);

        hideTypingIndicator();
        enableChatInput();
    });
}

// ─── Greeting ─────────────────────────────────────────────────────────────

function requestInitialGreeting() {
    showTypingIndicator();
    disableChatInput();

    socket.emit('send_message', Object.assign({
        task_id: TASK_ID,
        message: INITIAL_GREETING_SIGNAL,
        bpmn_xml: ''
    }, _getSettings()));
}

// ─── Chat ─────────────────────────────────────────────────────────────────

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
}

function handleChatKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

// ─── Stop / Send Button ──────────────────────────────────────────────────

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
    enableCompleteButton();
}

function disableChatInput() {
    if (elChatInput) elChatInput.disabled = true;
    if (elSendBtn) elSendBtn.disabled = true;
}

// ─── Chat Messages & Markdown ─────────────────────────────────────────────

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

    const senderDisplayName = sender === 'user' ? t('chat.you') : t('chat.mentor');

    if (showSender) {
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
    indicator.innerHTML = `
        <div class="message-sender">${t('chat.mentor')}</div>
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

// ─── Completion ───────────────────────────────────────────────────────────

function requestCompletion() {
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
            body: JSON.stringify({ task_id: TASK_ID, bpmn_xml: xml, sid: socket.id })
        });

        const data = await response.json();

        if (data.success) {
            window.location.href = data.redirect || '/';
        } else {
            alert('Error completing task: ' + (data.message || 'Unknown error'));
        }
    } catch (err) {
        console.error('Error completing task:', err);
        alert('Error completing task. Please try again.');
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

// ─── Zoom ─────────────────────────────────────────────────────────────────

let currentZoom = 0.9;
const ZOOM_STEP = 0.1;
const MIN_ZOOM = 0.3;
const MAX_ZOOM = 3.0;

function updateZoomLevel() {
    const zoomPercent = Math.round(currentZoom * 100);
    document.getElementById('zoomLevel').textContent = zoomPercent + '%';
    const zoomInBtn = document.getElementById('zoomInBtn');
    const zoomOutBtn = document.getElementById('zoomOutBtn');
    if (zoomInBtn && zoomOutBtn) {
        zoomInBtn.disabled = currentZoom >= MAX_ZOOM;
        zoomOutBtn.disabled = currentZoom <= MIN_ZOOM;
    }
}

function zoomIn() {
    if (currentZoom < MAX_ZOOM) {
        currentZoom = Math.min(currentZoom + ZOOM_STEP, MAX_ZOOM);
        applyZoom();
    }
}

function zoomOut() {
    if (currentZoom > MIN_ZOOM) {
        currentZoom = Math.max(currentZoom - ZOOM_STEP, MIN_ZOOM);
        applyZoom();
    }
}

function applyZoom() {
    if (modeler) {
        const canvas = modeler.get('canvas');
        canvas.zoom(currentZoom, 'auto');
        updateZoomLevel();
    }
}

// ─── Issue Overlays ───────────────────────────────────────────────────────

let currentIssues = [];
let issueOverlays = [];
let activeIssuePopup = null;

function displayIssues(issues) {
    clearIssues();
    currentIssues = issues;
    if (!modeler) return;

    const overlays = modeler.get('overlays');
    const elementRegistry = modeler.get('elementRegistry');

    createIssueSummary(issues);

    issues.forEach((issue, index) => {
        addIssueOverlay(issue, index, overlays, elementRegistry);
    });
}

function addIssueOverlay(issue, index, overlays, elementRegistry) {
    const element = elementRegistry.get(issue.elementId);
    if (!element) return;

    const severity = issue.severity.toLowerCase();
    const isConnection = element.waypoints && element.waypoints.length > 0;

    const overlayHtml = document.createElement('div');

    if (isConnection) {
        overlayHtml.className = 'issue-overlay-flow';
    } else {
        overlayHtml.className = 'issue-overlay-box';
        overlayHtml.style.width = `${element.width + 10}px`;
        overlayHtml.style.height = `${element.height + 10}px`;
    }

    const badge = document.createElement('div');
    badge.className = `issue-badge ${severity}`;
    badge.innerHTML = '!';
    badge.dataset.issueIndex = index;

    badge.addEventListener('mouseenter', (e) => showIssueHoverTooltip(issue, e));
    badge.addEventListener('mouseleave', hideIssueHoverTooltip);
    badge.addEventListener('click', (e) => {
        e.stopPropagation();
        showIssueDetailPopup(issue, index, e);
    });

    overlayHtml.appendChild(badge);

    let overlayPosition;
    if (isConnection) {
        const wp = element.waypoints;
        const midIdx = Math.floor(wp.length / 2);
        const midPoint = wp[midIdx];
        const sourceX = wp[0].x;
        const sourceY = wp[0].y;
        overlayPosition = {
            top: midPoint.y - sourceY - 12,
            left: midPoint.x - sourceX - 12
        };
    } else {
        overlayPosition = { top: -5, left: -5 };
    }

    try {
        const overlayId = overlays.add(issue.elementId, `issue-${severity}`, {
            position: overlayPosition,
            html: overlayHtml
        });
        issueOverlays.push({ id: overlayId, elementId: issue.elementId });
    } catch (err) {
        console.error(`[Issues] Failed to add overlay to ${issue.elementId}:`, err);
    }
}

function showIssueHoverTooltip(issue, event) {
    hideIssueHoverTooltip();

    const tooltip = document.createElement('div');
    tooltip.id = 'issueHoverTooltip';
    tooltip.className = `issue-hover-tooltip ${issue.severity.toLowerCase()}`;
    tooltip.textContent = issue.shortDesc || issue.message || t('issues.detected');

    const bpmnContainer = document.getElementById('bpmn-container');
    if (!bpmnContainer) return;

    bpmnContainer.appendChild(tooltip);

    const rect = event.target.getBoundingClientRect();
    const containerRect = bpmnContainer.getBoundingClientRect();

    let tooltipX = rect.right - containerRect.left + 10;
    let tooltipY = rect.top - containerRect.top;

    tooltip.style.left = `${tooltipX}px`;
    tooltip.style.top = `${tooltipY}px`;

    requestAnimationFrame(() => {
        const tooltipRect = tooltip.getBoundingClientRect();
        if (tooltipRect.right > containerRect.right) {
            tooltipX = rect.left - containerRect.left - tooltipRect.width - 10;
            tooltip.style.left = `${tooltipX}px`;
        }
        tooltip.classList.add('visible');
    });
}

function hideIssueHoverTooltip() {
    const existing = document.getElementById('issueHoverTooltip');
    if (existing) existing.remove();
}

function showIssueDetailPopup(issue, issueIndex, event) {
    closeIssueDetailPopup();

    const backdrop = document.createElement('div');
    backdrop.className = 'issue-popup-backdrop';
    backdrop.id = 'issuePopupBackdrop';
    backdrop.addEventListener('click', closeIssueDetailPopup);
    document.body.appendChild(backdrop);

    const popup = document.createElement('div');
    popup.className = 'issue-detail-popup';
    popup.id = 'issueDetailPopup';

    const severity = issue.severity.toLowerCase();
    const severityIcons = {
        syntax: '\u26d4',
        semantic: '\u26a0\ufe0f',
        info: '\u2139\ufe0f'
    };
    const severityLabels = {
        syntax: t('issues.syntax_error'),
        semantic: t('issues.semantic_issue'),
        info: t('issues.best_practice')
    };

    popup.innerHTML = `
        <div class="issue-detail-popup-header ${severity}">
            <div class="issue-detail-popup-title">
                <span class="severity-icon">${severityIcons[severity] || '!'}</span>
                <span class="severity-label">${severityLabels[severity] || 'Issue'}</span>
            </div>
            <button class="issue-detail-popup-close" onclick="closeIssueDetailPopup()">\u00d7</button>
        </div>
        <div class="issue-detail-popup-body">
            <div class="issue-detail-short">${formatMarkdown(issue.shortDesc || t('issues.detected'))}</div>
            <div class="issue-detail-long">${formatMarkdown(issue.longDesc || issue.message || t('issues.no_details'))}</div>
            <div class="issue-detail-meta">
                <div class="issue-detail-meta-item">
                    <span class="meta-label">${t('issues.element')}</span>
                    <span>${issue.elementId}</span>
                </div>
                <div class="issue-detail-meta-item">
                    <span class="meta-label">${t('issues.category')}</span>
                    <span>${issue.category || 'General'}</span>
                </div>
            </div>
        </div>
        <div class="issue-popup-footer">
            <button class="issue-action-btn dismiss" id="issueDismissBtn">${t('issues.dismiss')}</button>
        </div>
    `;

    document.body.appendChild(popup);

    document.getElementById('issueDismissBtn').addEventListener('click', (e) => {
        e.stopPropagation();
        dismissIssue(issueIndex);
    });

    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const popupRect = popup.getBoundingClientRect();

    let left = event.clientX + 20;
    let top = event.clientY - 20;

    if (left + popupRect.width > viewportWidth - 20) {
        left = event.clientX - popupRect.width - 20;
    }
    if (top + popupRect.height > viewportHeight - 20) {
        top = viewportHeight - popupRect.height - 20;
    }
    if (top < 20) top = 20;

    popup.style.left = `${left}px`;
    popup.style.top = `${top}px`;

    activeIssuePopup = popup;
    highlightElement(issue.elementId);
}

function closeIssueDetailPopup() {
    const popup = document.getElementById('issueDetailPopup');
    const backdrop = document.getElementById('issuePopupBackdrop');
    if (popup) popup.remove();
    if (backdrop) backdrop.remove();
    activeIssuePopup = null;
    document.querySelectorAll('.bpmn-element-highlighted').forEach(el => {
        el.classList.remove('bpmn-element-highlighted');
    });
}

function dismissIssue(issueIndex) {
    const issue = currentIssues[issueIndex];
    if (!issue) return;
    closeIssueDetailPopup();

    socket.emit('dismiss_issue', { task_id: TASK_ID, issue_index: issueIndex });

    // Re-render all remaining overlays with correct indices
    const remaining = [...currentIssues];
    remaining.splice(issueIndex, 1);
    clearIssues();
    if (remaining.length > 0) {
        displayIssues(remaining);
    }
}

function createIssueSummary(issues) {
    const bpmnContainer = document.getElementById('bpmn-container');
    if (!bpmnContainer) return;

    const existing = document.getElementById('issueSummary');
    if (existing) existing.remove();

    if (issues.length === 0) return;

    const counts = { syntax: 0, semantic: 0, info: 0 };

    issues.forEach(issue => {
        const severity = issue.severity.toLowerCase();
        if (counts.hasOwnProperty(severity)) counts[severity]++;
    });

    const summary = document.createElement('div');
    summary.className = 'annotation-summary';
    summary.id = 'issueSummary';
    summary.innerHTML = `
        <div class="annotation-summary-title">${t('issues.title')}</div>
        <div class="annotation-summary-counts">
            ${counts.syntax > 0 ? `
            <div class="annotation-count-row">
                <span class="annotation-count-label">
                    <span class="annotation-count-dot syntax"></span>
                    ${t('issues.syntax')}
                </span>
                <span class="annotation-count-number">${counts.syntax}</span>
            </div>` : ''}
            ${counts.semantic > 0 ? `
            <div class="annotation-count-row">
                <span class="annotation-count-label">
                    <span class="annotation-count-dot semantic"></span>
                    ${t('issues.semantic')}
                </span>
                <span class="annotation-count-number">${counts.semantic}</span>
            </div>` : ''}
            ${counts.info > 0 ? `
            <div class="annotation-count-row">
                <span class="annotation-count-label">
                    <span class="annotation-count-dot info"></span>
                    ${t('issues.best_practice')}
                </span>
                <span class="annotation-count-number">${counts.info}</span>
            </div>` : ''}
        </div>
    `;

    bpmnContainer.appendChild(summary);
}

function clearIssues() {
    closeIssueDetailPopup();
    hideIssueHoverTooltip();

    if (modeler) {
        try {
            const overlays = modeler.get('overlays');
            issueOverlays.forEach(overlay => {
                try { overlays.remove(overlay.id); } catch (e) {}
            });
        } catch (e) {}
    }

    issueOverlays = [];
    currentIssues = [];

    const summary = document.getElementById('issueSummary');
    if (summary) summary.remove();
}

function highlightElement(elementId) {
    if (!modeler) return;

    const elementRegistry = modeler.get('elementRegistry');
    const canvas = modeler.get('canvas');
    const element = elementRegistry.get(elementId);
    if (!element) return;

    document.querySelectorAll('.bpmn-element-highlighted').forEach(el => {
        el.classList.remove('bpmn-element-highlighted');
    });

    const gfx = elementRegistry.getGraphics(element);
    if (gfx) {
        gfx.classList.add('bpmn-element-highlighted');
        setTimeout(() => gfx.classList.remove('bpmn-element-highlighted'), 3000);
    }

    canvas.scrollToElement(element);
}

// ── Custom Task ───────────────────────────────────────────────────────────

var _customFileContent = '';

function handleCustomFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    const uploadBtn = document.getElementById('customUploadBtn');
    if (uploadBtn) uploadBtn.textContent = '\ud83d\udcce ' + file.name;

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

// ─── Initialization ───────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    elSendBtn = document.getElementById('sendBtn');
    elSendText = document.getElementById('sendText');
    elSendSpinner = document.getElementById('sendSpinner');
    elChatInput = document.getElementById('chatInput');
    elChatMessages = document.getElementById('chatMessages');

    initBPMN();
    updateZoomLevel();
    initWebSocket();

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
            });
        }
    }, MODELER_INIT_DELAY_MS);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && activeIssuePopup) {
            closeIssueDetailPopup();
        }
    });
});
