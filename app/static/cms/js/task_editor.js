/* ============================================================
   BPM-Tutor — BPMN Task Editor (admin)
   Wraps bpmn-js Modeler for the task edit form
   ============================================================ */

'use strict';

window._bpmnModeler = null;

/**
 * initBpmnEditor(containerId, xmlTextareaId)
 * Loads bpmn-js Modeler into `containerId` and syncs with `xmlTextareaId`.
 */
async function initBpmnEditor(containerId, xmlTextareaId) {
  const container = document.getElementById(containerId);
  const textarea = document.getElementById(xmlTextareaId);
  if (!container || !textarea) return;

  // Lazy-load bpmn-js modeler
  if (!window.BpmnJS) {
    await new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/bpmn-js@17/dist/bpmn-modeler.production.min.js';
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  window._bpmnModeler = new BpmnJS({ container: `#${containerId}` });

  // Import existing XML or create blank diagram
  const xml = textarea.value.trim();
  if (xml) {
    try {
      await window._bpmnModeler.importXML(xml);
    } catch (err) {
      console.warn('BPMN import warning:', err);
    }
  } else {
    await window._bpmnModeler.createDiagram();
  }

  window._bpmnModeler.get('canvas').zoom('fit-viewport');

  // Sync canvas → XML textarea on every change
  window._bpmnModeler.on('commandStack.changed', async () => {
    try {
      const { xml: updatedXml } = await window._bpmnModeler.saveXML({ format: true });
      if (textarea) textarea.value = updatedXml;
    } catch (e) { /* ignore */ }
  });
}

/**
 * Call before form submit to serialize current BPMN XML into the textarea.
 */
async function saveBpmnToTextarea(xmlTextareaId) {
  if (!window._bpmnModeler) return;
  try {
    const { xml } = await window._bpmnModeler.saveXML({ format: true });
    const textarea = document.getElementById(xmlTextareaId);
    if (textarea) textarea.value = xml;
  } catch (err) {
    console.error('BPMN save error:', err);
  }
}
