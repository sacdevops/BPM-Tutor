/* ============================================================
   BPM-Tutor — BPMN Task Editor (admin)
   Wraps bpmn-js Modeler for the task edit form
   ============================================================ */

'use strict';

let _bpmnModeler = null;

/**
 * initBpmnEditor(containerId, xmlTextareaId)
 * Loads bpmn-js Modeler into `containerId` and syncs with `xmlTextareaId`.
 */
async function initBpmnEditor(containerId, xmlTextareaId) {
  const container = document.getElementById(containerId);
  const textarea = document.getElementById(xmlTextareaId);
  if (!container || !textarea) return;

  // Lazy-load bpmn-js modeler (only available as UMD bundle via CDN)
  if (!window.BpmnJS) {
    await new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/bpmn-js@17/dist/bpmn-modeler.production.min.js';
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  _bpmnModeler = new BpmnJS({ container: `#${containerId}` });

  // Import existing XML or create blank diagram
  const xml = textarea.value.trim();
  if (xml) {
    try {
      await _bpmnModeler.importXML(xml);
    } catch (err) {
      console.warn('BPMN import warning:', err);
    }
  } else {
    await _bpmnModeler.createDiagram();
  }

  // Fit view
  _bpmnModeler.get('canvas').zoom('fit-viewport');
}

/**
 * Call before form submit to serialize current BPMN XML into the textarea.
 */
async function saveBpmnToTextarea(xmlTextareaId) {
  if (!_bpmnModeler) return;
  try {
    const { xml } = await _bpmnModeler.saveXML({ format: true });
    const textarea = document.getElementById(xmlTextareaId);
    if (textarea) textarea.value = xml;
  } catch (err) {
    console.error('BPMN save error:', err);
  }
}
