/* ============================================================
   BPM-Tutor — Survey Builder
   Manages pages/questions for the admin survey editor
   ============================================================ */

'use strict';

const SurveyBuilder = (() => {
  let pages = [];
  let activePage = 0;
  let containerId = null;

  // ---- Public API ---- //

  function init(cId, surveyData) {
    containerId = cId;
    if (surveyData && Array.isArray(surveyData.pages)) {
      pages = JSON.parse(JSON.stringify(surveyData.pages)); // deep clone
    } else {
      pages = [{ title: '', questions: [] }];
    }
    activePage = 0;
    render();
  }

  function addPage() {
    pages.push({ title: '', questions: [] });
    activePage = pages.length - 1;
    render();
  }

  function addQuestion(type) {
    if (!pages[activePage]) return;
    const q = {
      id: `q_${Date.now()}`,
      type,
      label: '',
      description: '',
      required: false,
      options: [],
      config: {}
    };
    pages[activePage].questions.push(q);
    render();
  }

  function getPages() {
    return pages;
  }

  // ---- Internal Rendering ---- //

  function render() {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';

    pages.forEach((page, pi) => {
      const isActive = pi === activePage;
      const pageDiv = document.createElement('div');
      pageDiv.className = 'card shadow-sm mb-3' + (isActive ? '' : ' opacity-75');
      pageDiv.innerHTML = `
        <div class="card-header d-flex align-items-center gap-2">
          <button type="button" class="btn btn-sm btn-link p-0 text-muted"
                  onclick="SurveyBuilder._setActive(${pi})">
            <i class="bi bi-chevron-${isActive ? 'up' : 'down'}"></i>
          </button>
          <span class="fw-semibold">Seite ${pi + 1}</span>
          <input type="text" class="form-control form-control-sm ms-2"
                 placeholder="Seitentitel (optional)"
                 value="${escHtml(page.title || '')}"
                 oninput="SurveyBuilder._setPageTitle(${pi}, this.value)"
                 style="max-width:220px">
          <div class="ms-auto d-flex gap-1">
            ${pi > 0 ? `<button type="button" class="btn btn-sm btn-outline-secondary"
                onclick="SurveyBuilder._movePage(${pi}, -1)">↑</button>` : ''}
            ${pi < pages.length - 1 ? `<button type="button" class="btn btn-sm btn-outline-secondary"
                onclick="SurveyBuilder._movePage(${pi}, 1)">↓</button>` : ''}
            <button type="button" class="btn btn-sm btn-outline-danger"
                    onclick="SurveyBuilder._removePage(${pi})">
              <i class="bi bi-trash"></i>
            </button>
          </div>
        </div>
        <div class="card-body" id="page_body_${pi}" style="${isActive ? '' : 'display:none'}">
          <div id="questions_${pi}">
            ${page.questions.map((q, qi) => renderQuestion(pi, qi, q)).join('')}
          </div>
          ${isActive ? `<div class="text-muted text-center small mt-2">
            Fragetypen aus der Leiste links hinzufügen ↑
          </div>` : ''}
        </div>`;
      container.appendChild(pageDiv);
    });
  }

  function renderQuestion(pi, qi, q) {
    const needsOptions = ['select', 'radio', 'checkbox'].includes(q.type);
    const isScale = q.type === 'scale' || q.type === 'likert';
    const isImage = q.type === 'image';
    return `
      <div class="border rounded p-3 mb-2 bg-white question-item" id="question_${pi}_${qi}">
        <div class="d-flex align-items-center gap-2 mb-2">
          <span class="badge bg-secondary">${escHtml(q.type)}</span>
          <input type="text" class="form-control form-control-sm flex-grow-1"
                 placeholder="${isImage ? 'Bildunterschrift (optional)' : 'Frage / Label *'}"
                 value="${escHtml(q.label)}"
                 oninput="SurveyBuilder._setQField(${pi},${qi},'label',this.value)">
          ${!isImage ? `<div class="form-check mb-0">
            <input type="checkbox" class="form-check-input" id="req_${pi}_${qi}"
                   ${q.required ? 'checked' : ''}
                   onchange="SurveyBuilder._setQField(${pi},${qi},'required',this.checked)">
            <label class="form-check-label small" for="req_${pi}_${qi}">Pflicht</label>
          </div>` : ''}
          <div class="d-flex gap-1">
            ${qi > 0 ? `<button type="button" class="btn btn-xs btn-outline-secondary py-0 px-1"
                onclick="SurveyBuilder._moveQ(${pi},${qi},-1)">↑</button>` : ''}
            ${qi < (pages[pi]?.questions.length - 1) ? `<button type="button"
                class="btn btn-xs btn-outline-secondary py-0 px-1"
                onclick="SurveyBuilder._moveQ(${pi},${qi},1)">↓</button>` : ''}
            <button type="button" class="btn btn-xs btn-outline-danger py-0 px-1"
                    onclick="SurveyBuilder._removeQ(${pi},${qi})">×</button>
          </div>
        </div>
        ${isImage ? `
          <div class="d-flex align-items-center gap-2 mb-2">
            <input type="file" class="form-control form-control-sm" accept="image/*"
                   id="imgUpload_${pi}_${qi}"
                   onchange="SurveyBuilder._uploadQuestionImage(${pi},${qi},this)">
            <span class="text-muted small">oder</span>
            <input type="url" class="form-control form-control-sm"
                   placeholder="Bild-URL (https://...)"
                   value="${escHtml(q.config?.image_url || '')}"
                   oninput="SurveyBuilder._setCfg(${pi},${qi},'image_url',this.value)">
          </div>
          ${q.config?.image_url ? `<img src="${escHtml(q.config.image_url)}" style="max-height:120px;border-radius:6px;margin-top:4px;" onerror="this.style.display='none'" id="imgPreview_${pi}_${qi}">` : `<img id="imgPreview_${pi}_${qi}" style="max-height:120px;border-radius:6px;display:none;">`}
        ` : `
          <input type="text" class="form-control form-control-sm mb-2"
                 placeholder="Beschreibung / Hilfetext (optional)"
                 value="${escHtml(q.description || '')}"
                 oninput="SurveyBuilder._setQField(${pi},${qi},'description',this.value)">
        `}
        ${needsOptions ? `
          <label class="form-label small">Optionen (eine pro Zeile: wert=Label)</label>
          <textarea class="form-control form-control-sm" rows="3"
                    oninput="SurveyBuilder._setQOptions(${pi},${qi},this.value)"
                    >${(q.options||[]).map(o => `${o.value}=${o.label}`).join('\n')}</textarea>` : ''}
        ${isScale ? `
          <div class="row g-2 mt-1">
            <div class="col-md-3">
              <input type="number" class="form-control form-control-sm"
                     placeholder="Schritte (z.B. 5)"
                     value="${q.config?.steps || ''}"
                     oninput="SurveyBuilder._setCfg(${pi},${qi},'steps',+this.value)">
            </div>
            <div class="col-md-4">
              <input type="text" class="form-control form-control-sm"
                     placeholder="Min-Label (z.B. Gar nicht)"
                     value="${escHtml(q.config?.min_label || '')}"
                     oninput="SurveyBuilder._setCfg(${pi},${qi},'min_label',this.value)">
            </div>
            <div class="col-md-4">
              <input type="text" class="form-control form-control-sm"
                     placeholder="Max-Label (z.B. Sehr stark)"
                     value="${escHtml(q.config?.max_label || '')}"
                     oninput="SurveyBuilder._setCfg(${pi},${qi},'max_label',this.value)">
            </div>
          </div>` : ''}
      </div>`;
  }

  // ---- Helpers ---- //

  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  // ---- Internal Mutation Methods (exposed via _ prefix) ---- //

  function _setActive(i) { activePage = i; render(); }
  function _setPageTitle(i, v) { pages[i].title = v; }
  function _movePage(i, dir) {
    const j = i + dir;
    if (j < 0 || j >= pages.length) return;
    [pages[i], pages[j]] = [pages[j], pages[i]];
    activePage = j;
    render();
  }
  function _removePage(i) {
    if (pages.length === 1) { alert('Mindestens eine Seite erforderlich.'); return; }
    pages.splice(i, 1);
    if (activePage >= pages.length) activePage = pages.length - 1;
    render();
  }
  function _setQField(pi, qi, field, value) { pages[pi].questions[qi][field] = value; }
  function _setQOptions(pi, qi, text) {
    pages[pi].questions[qi].options = text.split('\n').filter(l => l.trim()).map(l => {
      const [val, ...rest] = l.split('=');
      return { value: val.trim(), label: rest.join('=').trim() || val.trim() };
    });
  }
  function _setCfg(pi, qi, key, val) {
    pages[pi].questions[qi].config = pages[pi].questions[qi].config || {};
    pages[pi].questions[qi].config[key] = val;
  }
  function _moveQ(pi, qi, dir) {
    const qs = pages[pi].questions;
    const j = qi + dir;
    if (j < 0 || j >= qs.length) return;
    [qs[qi], qs[j]] = [qs[j], qs[qi]];
    render();
  }
  function _removeQ(pi, qi) { pages[pi].questions.splice(qi, 1); render(); }

  function _uploadQuestionImage(pi, qi, input) {
    const file = input.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    fetch('/survey/upload-image', { method: 'POST', body: formData })
      .then(r => r.json())
      .then(data => {
        if (data.url) {
          _setCfg(pi, qi, 'image_url', data.url);
          const preview = document.getElementById(`imgPreview_${pi}_${qi}`);
          if (preview) { preview.src = data.url; preview.style.display = ''; }
        } else {
          alert('Bild-Upload fehlgeschlagen: ' + (data.error || 'Unbekannter Fehler'));
        }
      })
      .catch(() => alert('Bild-Upload fehlgeschlagen.'));
  }

  return {
    init, addPage, addQuestion, getPages,
    _setActive, _setPageTitle, _movePage, _removePage,
    _setQField, _setQOptions, _setCfg, _moveQ, _removeQ, _uploadQuestionImage
  };
})();

// Global convenience wrapper called from survey_edit.html
function initSurveyBuilder(containerId, surveyData) {
  document.addEventListener('DOMContentLoaded', () => {
    SurveyBuilder.init(containerId, surveyData);
  });
}
