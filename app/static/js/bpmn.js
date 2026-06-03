/**
 * bpmn.js — BPMN.io modeler, zoom controls, and issue overlay functions.
 * Loaded before chat.js and task.js; uses the 'modeler' global declared in task.html.
 */

// ─── BPMN Modeler ────────────────────────────────────────────────────────────

function initBPMN() {
    const isReadOnly = (typeof MODELING_MODE !== 'undefined' && MODELING_MODE === 'ai_only');
    modeler = new BpmnJS({
        container: '#bpmn-canvas',
        keyboard: isReadOnly ? {} : { bindTo: document }
    });

    if (isReadOnly) {
        _lockModelerForAiOnly();
    }

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

/**
 * Lock the modeler for AI-only mode: block all user-initiated modifications
 * while keeping programmatic (AI) operations fully functional.
 * Panning and zooming remain available for inspection.
 */
function _lockModelerForAiOnly() {
    const HIGH = 10000; // priority above all built-in handlers
    const eb = modeler.get('eventBus');

    const cancel = (e) => {
        e.stopPropagation();
        if (typeof e.preventDefault === 'function') e.preventDefault();
        return false;
    };

    [
        'shape.move.start',           // drag to move element
        'resize.start',               // drag resize handle
        'directEditing.activate',     // double-click label editing
        'contextPad.open',            // context pad (delete, connect…)
        'create.init',                // create from palette / drop
        'bendpoint.move.start',       // edit connection bend points
        'connectionSegment.move.start', // drag connection segments
        'connectionReconnect.start',  // reconnect endpoints
        'connect.start',              // drag to draw new connection
    ].forEach(evt => eb.on(evt, HIGH, cancel));

    // Hide palette, context pad and editing handles via a CSS class
    const container = document.getElementById('bpmn-canvas');
    if (container) container.classList.add('bpmn-readonly');
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

// ─── AI BPMN Operations ────────────────────────────────────────────────────────

/**
 * Execute a list of BPMN operations emitted by the AI.
 *
 * Supported ops:
 *   participate – create a Pool (Participant)
 *   draw        – create an element inside a pool/lane (with optional parentId, connectTo, eventDefinition)
 *   create      – alias for draw
 *   connect     – create a sequence or message flow
 *   delete/remove – delete a shape or connection
 *   rename/update – rename an element
 *   move        – move an element to new coordinates
 *   resize      – resize a shape (pool, lane, sub-process)
 *   replace     – change element type
 *   clear       – remove all elements from the diagram
 *
 * draw.connectTo[] is auto-expanded to separate connect ops executed after all shapes are placed.
 */
function executeBpmnOps(ops) {
    if (!modeler || !ops) return;

    // ── Normalise grouped-object format → flat array ───────────────────────
    // Supports both formats:
    //   Old (flat array):  [{op: "draw", type: "Task", ...}, ...]
    //   New (grouped obj): {draw(type, x, y, ...): [{Task, 100, 200, ...}], delete(id): [{MyId}]}
    // The grouped format is already decoded by the LION parser into:
    //   {participate: [{...}], draw: [{...}], connect: [{...}], ...}
    function normalizeOps(raw) {
        if (Array.isArray(raw)) return raw;
        if (!raw || typeof raw !== 'object') return [];
        const out = [];
        // Process ops in a safe order: pools first, then elements, then
        // renames/moves/resizes, then connections, then deletes last.
        const ORDER = [
            'clear',       // wipe canvas before building
            'participate', // create pools
            'draw',        // create elements inside pools
            'create',      // alias for draw
            'rename',      // label updates
            'update',      // alias for rename
            'resize',      // resize pools / elements
            'move',        // reposition
            'replace',     // change element type
            'connect',     // draw connections (elements must exist)
            'delete',      // remove elements last
            'remove',      // alias for delete
        ];
        for (const opName of ORDER) {
            if (!(opName in raw)) continue;
            if (opName === 'clear') {
                // clear takes no per-element arguments
                out.push({ op: 'clear' });
                continue;
            }
            const rows = raw[opName];
            if (!Array.isArray(rows)) continue;
            for (const row of rows) {
                if (row && typeof row === 'object') {
                    out.push(Object.assign({ op: opName }, row));
                }
            }
        }
        return out;
    }

    ops = normalizeOps(ops);
    if (!ops.length) return;

    const modeling        = modeler.get('modeling');
    const elementFactory  = modeler.get('elementFactory');
    const elementRegistry = modeler.get('elementRegistry');
    const bpmnFactory     = modeler.get('bpmnFactory');
    const canvas          = modeler.get('canvas');
    const root            = canvas.getRootElement();

    // ── Normalise type string → bpmn:XYZ ─────────────────────────────────
    function bpmnType(rawType) {
        if (!rawType) return 'bpmn:Task';
        if (rawType.startsWith('bpmn:')) return rawType;
        const map = {
            startevent:            'bpmn:StartEvent',
            endevent:              'bpmn:EndEvent',
            task:                  'bpmn:Task',
            usertask:              'bpmn:UserTask',
            servicetask:           'bpmn:ServiceTask',
            sendtask:              'bpmn:SendTask',
            receivetask:           'bpmn:ReceiveTask',
            scripttask:            'bpmn:ScriptTask',
            businessruletask:      'bpmn:BusinessRuleTask',
            manualtask:            'bpmn:ManualTask',
            exclusivegateway:      'bpmn:ExclusiveGateway',
            parallelgateway:       'bpmn:ParallelGateway',
            inclusivegateway:      'bpmn:InclusiveGateway',
            eventbasedgateway:     'bpmn:EventBasedGateway',
            complexgateway:        'bpmn:ComplexGateway',
            intermediatecatchevent:'bpmn:IntermediateCatchEvent',
            intermediatethrowevent:'bpmn:IntermediateThrowEvent',
            boundaryevent:         'bpmn:BoundaryEvent',
            subprocess:            'bpmn:SubProcess',
            participant:           'bpmn:Participant',
            pool:                  'bpmn:Participant',
            lane:                  'bpmn:Lane',
            sequenceflow:          'bpmn:SequenceFlow',
            messageflow:           'bpmn:MessageFlow',
            dataobject:            'bpmn:DataObjectReference',
            datastore:             'bpmn:DataStoreReference',
            textannotation:        'bpmn:TextAnnotation',
        };
        return map[rawType.toLowerCase()] ||
            ('bpmn:' + rawType.charAt(0).toUpperCase() + rawType.slice(1));
    }

    const defaultSize = {
        'bpmn:Task':                   { width: 100, height: 80 },
        'bpmn:UserTask':               { width: 100, height: 80 },
        'bpmn:ServiceTask':            { width: 100, height: 80 },
        'bpmn:SendTask':               { width: 100, height: 80 },
        'bpmn:ReceiveTask':            { width: 100, height: 80 },
        'bpmn:ScriptTask':             { width: 100, height: 80 },
        'bpmn:ManualTask':             { width: 100, height: 80 },
        'bpmn:BusinessRuleTask':       { width: 100, height: 80 },
        'bpmn:StartEvent':             { width: 36, height: 36 },
        'bpmn:EndEvent':               { width: 36, height: 36 },
        'bpmn:IntermediateCatchEvent': { width: 36, height: 36 },
        'bpmn:IntermediateThrowEvent': { width: 36, height: 36 },
        'bpmn:ExclusiveGateway':       { width: 50, height: 50 },
        'bpmn:ParallelGateway':        { width: 50, height: 50 },
        'bpmn:InclusiveGateway':       { width: 50, height: 50 },
        'bpmn:EventBasedGateway':      { width: 50, height: 50 },
        'bpmn:SubProcess':             { width: 350, height: 200 },
        'bpmn:TextAnnotation':         { width: 100, height: 50 },
    };

    // ── Resolve compound event type → { drawType, eventDefinitionType } ─────
    // Supports shorthand names like "MessageStartEvent", "TimerBoundaryEvent"
    // so the LLM does not need a separate eventDefinition field.
    // eventDefinitionType is passed directly to elementFactory.createShape—
    // the official bpmn-js API that handles everything internally.
    const _EVT_DEF_PREFIXES = [
        ['message',    'bpmn:MessageEventDefinition'],
        ['timer',      'bpmn:TimerEventDefinition'],
        ['error',      'bpmn:ErrorEventDefinition'],
        ['signal',     'bpmn:SignalEventDefinition'],
        ['escalation', 'bpmn:EscalationEventDefinition'],
        ['terminate',  'bpmn:TerminateEventDefinition'],
        ['conditional','bpmn:ConditionalEventDefinition'],
        ['compensate', 'bpmn:CompensateEventDefinition'],
        ['cancel',     'bpmn:CancelEventDefinition'],
        ['link',       'bpmn:LinkEventDefinition'],
    ];
    const _BASE_EVT_TYPES = [
        'startevent', 'endevent',
        'intermediatecatchevent', 'intermediatethrowevent', 'boundaryevent',
    ];
    function resolveDrawType(rawType, rawEventDef) {
        const lower = (rawType || '').toLowerCase().replace(/[\s_-]/g, '');
        for (const [prefix, defType] of _EVT_DEF_PREFIXES) {
            if (lower.startsWith(prefix)) {
                const remainder = lower.slice(prefix.length);
                if (_BASE_EVT_TYPES.includes(remainder)) {
                    return { drawType: bpmnType(remainder), eventDefinitionType: defType };
                }
            }
        }
        // Plain type — check for explicit eventDefinition field ("bpmn:XEventDefinition" or short "XEventDefinition")
        let evtDefType = null;
        if (rawEventDef) {
            const ed = String(rawEventDef);
            evtDefType = ed.startsWith('bpmn:') ? ed
                : 'bpmn:' + ed.charAt(0).toUpperCase() + ed.slice(1);
        }
        return { drawType: bpmnType(rawType), eventDefinitionType: evtDefType };
    }

    // ── Resolve parent element (pool / lane / root) ───────────────────────
    function resolveParent(parentId) {
        if (!parentId) return root;
        const el = elementRegistry.get(String(parentId));
        if (el) return el;
        // Fallback: search by business-object name
        const all = elementRegistry.getAll();
        for (const e of all) {
            if (e.businessObject && e.businessObject.name === parentId) return e;
        }
        return root;
    }

    // ── Expand draw.connectTo[] into separate connect ops ─────────────────
    function expandConnectTo(opList) {
        const out = [];
        for (const op of opList) {
            out.push(op);
            if ((op.op === 'draw' || op.op === 'create') &&
                    Array.isArray(op.connectTo)) {
                for (const targetId of op.connectTo) {
                    if (targetId) {
                        out.push({ op: 'connect',
                                   source: op.id,
                                   target: String(targetId) });
                    }
                }
            }
        }
        return out;
    }

    // ── Execute a single op ───────────────────────────────────────────────
    function execOne(op) {
        const normalType = bpmnType(op.type);
        try {
            // participate ──────────────────────────────────────────────────
            if (op.op === 'participate') {
                if (op.id && elementRegistry.get(op.id)) {
                    modeling.removeElements([elementRegistry.get(op.id)]);
                }
                // expanded: true (default) = white-box pool; false = black-box (collapsed) pool
                const isExpanded = op.expanded !== false && op.expanded !== 'false';

                const participant = elementFactory.createParticipantShape({ isExpanded });
                const w  = op.width  || (isExpanded ? 800 : 150);
                const h  = op.height || (isExpanded ? 200 : 60);
                const cx = (op.x || 100) + w / 2;
                const cy = (op.y || 100) + h / 2;
                const created = modeling.createShape(participant, { x: cx, y: cy }, root);
                modeling.resizeShape(created, {
                    x: op.x || 100, y: op.y || 100, width: w, height: h,
                });
                if (op.name) modeling.updateLabel(created, op.name);
                if (op.id)   modeling.updateProperties(created, { id: op.id });

                // For collapsed pools bpmn-js needs the business object flag set explicitly
                if (!isExpanded) {
                    try {
                        const bpmnReplace = modeler.get('bpmnReplace');
                        bpmnReplace.replaceElement(created, {
                            type: 'bpmn:Participant',
                            isExpanded: false,
                        });
                    } catch (_) {
                        // Fallback: set the flag directly on the business object
                        modeling.updateProperties(created, { isExpanded: false });
                    }
                }

                // lanes: ["Lane A", "Lane B"] — divided evenly across the pool height
                if (isExpanded && Array.isArray(op.lanes) && op.lanes.length > 0) {
                    const POOL_HEADER = 30; // bpmn-js label strip on the left of a pool
                    const poolEl    = elementRegistry.get(op.id) || created;
                    const laneX     = poolEl.x + POOL_HEADER;
                    const laneW     = poolEl.width - POOL_HEADER;
                    const laneCount = op.lanes.length;
                    const laneH     = Math.floor(poolEl.height / laneCount);
                    op.lanes.forEach((laneName, i) => {
                        try {
                            const laneShape   = elementFactory.createShape({ type: 'bpmn:Lane' });
                            const laneCenterX = laneX + laneW / 2;
                            const laneCenterY = poolEl.y + i * laneH + laneH / 2;
                            const laneCreated = modeling.createShape(
                                laneShape,
                                { x: laneCenterX, y: laneCenterY },
                                poolEl
                            );
                            // Resize to the exact pool-inner bounds
                            modeling.resizeShape(laneCreated, {
                                x: laneX,
                                y: poolEl.y + i * laneH,
                                width: laneW,
                                height: laneH,
                            });
                            if (laneName) modeling.updateLabel(laneCreated, String(laneName));
                        } catch (laneErr) {
                            console.warn('[AI] Lane creation error:', laneName, laneErr);
                        }
                    });
                    // After lane creation bpmn-js can silently clear di.isExpanded.
                    // Set it back directly on the DI object so saveXML exports
                    // isExpanded="true" and the pool survives a round-trip.
                    try {
                        const poolShape = elementRegistry.get(op.id) || created;
                        if (poolShape && poolShape.businessObject && poolShape.businessObject.di) {
                            poolShape.businessObject.di.isExpanded = true;
                        }
                    } catch (_) {}
                }
                console.log('[AI] Created pool:', op.name, op.id, 'lanes:', op.lanes ? op.lanes.length : 0);
                return;
            }

            // draw / create ────────────────────────────────────────────────
            if (op.op === 'draw' || op.op === 'create') {
                const isFlow = normalType === 'bpmn:SequenceFlow' ||
                               normalType === 'bpmn:MessageFlow';
                if (isFlow) {
                    const src = elementRegistry.get(String(op.source || ''));
                    const tgt = elementRegistry.get(String(op.target || ''));
                    if (src && tgt) {
                        const conn = modeling.connect(src, tgt);
                        if (op.id)              modeling.updateProperties(conn, { id: op.id });
                        if (op.name || op.label) modeling.updateLabel(conn, op.name || op.label);
                    }
                    return;
                }

                if (op.id && elementRegistry.get(op.id)) {
                    modeling.removeElements([elementRegistry.get(op.id)]);
                }

                const { drawType, eventDefinitionType } = resolveDrawType(op.type, op.eventDefinition);
                // Pass eventDefinitionType to createShape — official bpmn-js API;
                // the factory sets up the event definition on the business object.
                const shapeConfig = { type: drawType };
                if (eventDefinitionType) shapeConfig.eventDefinitionType = eventDefinitionType;
                const shape  = elementFactory.createShape(shapeConfig);
                const parent = resolveParent(op.parentId);

                const created = modeling.createShape(
                    shape,
                    { x: op.x || 200, y: op.y || 200 },
                    parent
                );

                if (op.name || op.label) modeling.updateLabel(created, op.name || op.label);
                if (op.id)              modeling.updateProperties(created, { id: op.id });
                console.log('[AI] Drew:', drawType, eventDefinitionType || '', op.id || created.id, 'in', op.parentId || 'root');
                return;
            }

            // rename / update ──────────────────────────────────────────────
            if (op.op === 'rename' || op.op === 'update') {
                const el = elementRegistry.get(String(op.id || ''));
                if (el && (op.name !== undefined || op.label !== undefined)) {
                    modeling.updateLabel(el, op.name !== undefined ? op.name : op.label);
                }
                return;
            }

            // move ─────────────────────────────────────────────────────────
            if (op.op === 'move') {
                const el = elementRegistry.get(String(op.id || ''));
                if (el) {
                    const dx = (op.x || el.x) - el.x;
                    const dy = (op.y || el.y) - el.y;
                    modeling.moveElements([el], { x: dx, y: dy });
                }
                return;
            }

            // delete / remove ──────────────────────────────────────────────
            if (op.op === 'delete' || op.op === 'remove') {
                const el = elementRegistry.get(String(op.id || ''));
                if (el) {
                    if (el.waypoints) modeling.removeConnection(el);
                    else              modeling.removeShape(el);
                }
                return;
            }

            // connect ──────────────────────────────────────────────────────
            if (op.op === 'connect') {
                const src = elementRegistry.get(String(op.source || ''));
                const tgt = elementRegistry.get(String(op.target || ''));
                if (src && tgt) {
                    const conn = modeling.connect(src, tgt);
                    if (op.id)              modeling.updateProperties(conn, { id: op.id });
                    if (op.name || op.label) modeling.updateLabel(conn, op.name || op.label);
                } else {
                    console.warn('[AI] connect: element not found —',
                        op.source, '->', op.target);
                }
                return;
            }

            // resize ───────────────────────────────────────────────────────
            if (op.op === 'resize') {
                const el = elementRegistry.get(String(op.id || ''));
                if (el && op.width && op.height) {
                    modeling.resizeShape(el, {
                        x:      op.x      !== undefined ? op.x      : el.x,
                        y:      op.y      !== undefined ? op.y      : el.y,
                        width:  op.width,
                        height: op.height,
                    });
                }
                return;
            }

            // replace ──────────────────────────────────────────────────────
            if (op.op === 'replace') {
                const el = elementRegistry.get(String(op.id || ''));
                if (el) modeling.updateProperties(el, { type: normalType });
                return;
            }

            // clear ────────────────────────────────────────────────────────
            if (op.op === 'clear') {
                const all = elementRegistry.filter(e => e !== root);
                if (all.length) modeling.removeElements(all);
                return;
            }

            console.warn('[AI Modeling] Unknown op:', op.op);

        } catch (err) {
            console.warn('[AI Modeling] op failed:', op, err);
        }

        // Emit ai_action tracking event (best-effort — trackEvent is defined in task.js)
        try {
            if (typeof trackEvent === 'function') {
                trackEvent('ai_action', { op: op.op, id: op.id || '', label: op.name || op.label || '' });
            }
        } catch (_) {}
    }

    // ── Expand connectTo, split into immediate (shapes) and deferred ──────
    const expanded  = expandConnectTo(ops);

    // Only animate cursor when the agent does modeling (colleague / delegant)
    const aiCursorEl = document.getElementById('aiCursor');
    const useAnimation = aiCursorEl &&
        typeof MODELING_MODE !== 'undefined' && MODELING_MODE !== 'none';

    if (!useAnimation) {
        // Original synchronous execution – no cursor
        const shapeOps = expanded.filter(o =>
            o.op === 'participate' || o.op === 'draw' || o.op === 'create');
        const afterOps = expanded.filter(o =>
            o.op !== 'participate' && o.op !== 'draw' && o.op !== 'create');
        for (const op of shapeOps) execOne(op);
        if (afterOps.length) {
            afterOps.forEach((op, i) => {
                setTimeout(() => execOne(op), 300 + i * 150);
            });
        }
        return;
    }

    // Animated sequential execution: cursor moves to position, then op fires
    aiCursorEl.classList.add('active');
    const ACTION_INTERVAL = 1500;  // ms between ops
    const CURSOR_SETTLE   = 800;   // ms after cursor arrives before creating element

    // Reorder: shapes first (so connections can find them), then afterOps
    const shapeOps2 = expanded.filter(o =>
        o.op === 'participate' || o.op === 'draw' || o.op === 'create');
    const afterOps2 = expanded.filter(o =>
        o.op !== 'participate' && o.op !== 'draw' && o.op !== 'create');
    const orderedOps = [...shapeOps2, ...afterOps2];

    let delay = 0;
    orderedOps.forEach((op) => {
        setTimeout(() => {
            // Move cursor to the target position in BPMN canvas coordinates
            if (op.op === 'draw' || op.op === 'create') {
                animateAICursor(op.x || 200, op.y || 200);
            } else if (op.op === 'participate') {
                animateAICursor(
                    (op.x || 100) + (op.width || 800) / 2,
                    (op.y || 100) + (op.height || 200) / 2
                );
            } else if (op.op === 'connect') {
                const src = elementRegistry.get(String(op.source || ''));
                const tgt = elementRegistry.get(String(op.target || ''));
                if (src && tgt) {
                    animateAICursor(
                        (src.x + src.width / 2 + tgt.x + tgt.width / 2) / 2,
                        (src.y + src.height / 2 + tgt.y + tgt.height / 2) / 2
                    );
                }
            } else if (op.op === 'move' || op.op === 'rename' || op.op === 'resize') {
                const el = elementRegistry.get(String(op.id || ''));
                if (el) animateAICursor(el.x + el.width / 2, el.y + el.height / 2);
            }

            // Execute op after cursor has settled
            setTimeout(() => execOne(op), CURSOR_SETTLE);
        }, delay);

        delay += ACTION_INTERVAL;
    });

    // Hide cursor after all ops complete
    setTimeout(() => aiCursorEl.classList.remove('active'), delay + 1000);
}

// ── Animate AI cursor to a BPMN canvas position ───────────────────────────────
function animateAICursor(bpmnX, bpmnY) {
    const cursor = document.getElementById('aiCursor');
    if (!cursor || !modeler) return;
    try {
        const canvas  = modeler.get('canvas');
        const viewbox  = canvas.viewbox();
        const scale    = viewbox.scale;
        // Convert BPMN coordinates → pixel offset within the canvas SVG
        const canvasX  = (bpmnX - viewbox.x) * scale;
        const canvasY  = (bpmnY - viewbox.y) * scale;
        // Cursor is position:absolute inside #bpmn-container; offset relative to container
        const container = document.getElementById('bpmn-container');
        const canvasEl  = document.getElementById('bpmn-canvas');
        if (!container || !canvasEl) return;
        const cr = container.getBoundingClientRect();
        const cv = canvasEl.getBoundingClientRect();
        cursor.style.left = (cv.left - cr.left + canvasX) + 'px';
        cursor.style.top  = (cv.top  - cr.top  + canvasY) + 'px';
    } catch (err) {
        console.warn('[AI Cursor] position error:', err);
    }
}



// ─── Zoom ─────────────────────────────────────────────────────────────────────

let currentZoom = 1.0;
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

// ─── Issue Overlays ───────────────────────────────────────────────────────────

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
