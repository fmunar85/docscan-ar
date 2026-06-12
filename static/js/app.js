/* ══════════════════════════════════════════════════════════
   DocScan AR — app.js
   ══════════════════════════════════════════════════════════ */

'use strict';

/* ── Estado global ──────────────────────────────────────────── */
let selectedFile = null;
let currentDocType = 'FACTURA';

/* ── Init ───────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  setupDragDrop();
});

/* ── Seleccionar tipo de documento ──────────────────────────── */
function selectType(btn) {
  document.querySelectorAll('.doc-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentDocType = btn.dataset.type;
  setStep(1);
}

/* ── Pasos visuales ─────────────────────────────────────────── */
function setStep(n) {
  ['stp1', 'stp2', 'stp3'].forEach((id, i) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('active', 'done');
    if (i + 1 < n)  el.classList.add('done');
    if (i + 1 === n) el.classList.add('active');
  });
}

/* ── Abrir cámara / galería ─────────────────────────────────── */
function openCamera() {
  const inp = document.getElementById('cameraInput');
  inp.value = '';
  inp.click();
}
function openGallery() {
  const inp = document.getElementById('galleryInput');
  inp.value = '';
  inp.click();
}

/* ── Drag & drop (desktop) ──────────────────────────────────── */
function setupDragDrop() {
  const zone = document.getElementById('uploadZone');
  if (!zone) return;
  zone.addEventListener('dragover',  e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
  });
}

/* ── Manejar archivo seleccionado ───────────────────────────── */
function handleFile(file) {
  if (!file) return;

  const MAX = 20 * 1024 * 1024;
  if (file.size > MAX) { showToast('❌ Archivo muy grande (máx 20 MB)', 'danger'); return; }

  const okExt = /\.(jpe?g|png|gif|webp|heic|heif|pdf)$/i;
  if (!okExt.test(file.name) && !file.type.startsWith('image/') && file.type !== 'application/pdf') {
    showToast('❌ Formato no permitido', 'danger');
    return;
  }

  selectedFile = file;
  renderPreview(file);
  document.getElementById('btnAnalizar').disabled = false;
  setStep(2);
}

function renderPreview(file) {
  const zone = document.getElementById('uploadZone');
  const ph   = document.getElementById('uploadPlaceholder');
  const prev = document.getElementById('uploadPreview');
  if (!zone || !prev) return;

  ph.classList.add('d-none');
  prev.classList.remove('d-none');

  if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
    prev.innerHTML = `
      <div class="py-3">
        <div style="font-size:3.5rem">📄</div>
        <p class="fw-600 mt-2 mb-0">${escHtml(file.name)}</p>
        <p class="text-muted small">${(file.size / 1048576).toFixed(1)} MB · PDF</p>
        <button class="btn btn-sm btn-outline-secondary" onclick="clearFile(event)">
          <i class="fas fa-times me-1"></i>Cambiar
        </button>
      </div>`;
  } else {
    const reader = new FileReader();
    reader.onload = e => {
      prev.innerHTML = `
        <img src="${e.target.result}" class="upload-preview-img mb-2" alt="preview" />
        <p class="text-muted small mb-1">${escHtml(file.name)}</p>
        <button class="btn btn-sm btn-outline-secondary" onclick="clearFile(event)">
          <i class="fas fa-times me-1"></i>Cambiar
        </button>`;
    };
    reader.readAsDataURL(file);
  }
}

function clearFile(evt) {
  if (evt) evt.stopPropagation();
  selectedFile = null;
  const ph   = document.getElementById('uploadPlaceholder');
  const prev = document.getElementById('uploadPreview');
  if (ph)   ph.classList.remove('d-none');
  if (prev) { prev.classList.add('d-none'); prev.innerHTML = ''; }
  document.getElementById('btnAnalizar').disabled = true;
  ['fileInput','cameraInput','galleryInput'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  setStep(1);
}

/* ── Enviar al backend para procesar ────────────────────────── */
async function submitDocument() {
  if (!selectedFile) { showToast('❌ Seleccioná un archivo primero', 'warning'); return; }
  setStep(3);
  showLoading('Leyendo documento…', 'Extrayendo datos 📄');

  const fd = new FormData();
  fd.append('file', selectedFile);
  fd.append('doc_type', currentDocType);

  try {
    const res  = await fetch('/process', { method: 'POST', body: fd });
    const json = await res.json();
    hideLoading();

    if (json.success) {
      // Si el tipo fue auto-detectado, actualizar el selector visual
      if (json.doc_type !== currentDocType) {
        currentDocType = json.doc_type;
        document.querySelectorAll('.doc-btn').forEach(b => {
          b.classList.toggle('active', b.dataset.type === json.doc_type);
        });
      }
      renderResultForm(json.data, json.doc_type);
    } else {
      showToast('❌ ' + (json.error || 'Error al procesar'), 'danger');
      setStep(2);
    }
  } catch (err) {
    hideLoading();
    showToast('❌ Error de conexión: ' + err.message, 'danger');
    setStep(2);
  }
}

/* ── Renderizar formulario de revisión ──────────────────────── */
function renderResultForm(data, docType) {
  document.getElementById('viewUpload').classList.add('d-none');
  const view = document.getElementById('viewResult');
  view.classList.remove('d-none');

  const docIcon  = { FACTURA: '🧾', REMITO: '📦', TICKET: '🎫' }[docType] || '📄';
  const docColor = { FACTURA: 'primary', REMITO: 'success', TICKET: 'warning' }[docType] || 'secondary';

  view.innerHTML = `
    <div class="ds-card ds-slide-up">
      <div class="ds-card-header d-flex align-items-center justify-content-between">
        <span><i class="fas fa-check-circle me-2"></i>Revisá y corregí</span>
        <span class="badge-doc badge-${docType}">${docIcon} ${docType}</span>
      </div>
      <div class="ds-card-body">
        ${data._warning ? `
        <div class="alert alert-warning py-2 px-3 small mb-3">
          <i class="fas fa-edit me-1"></i>${data._warning}
        </div>` : `
        <p class="text-muted small mb-3">
          <i class="fas fa-check-circle me-1 text-success"></i>
          Datos leídos del documento. Editá lo que haga falta.
        </p>`}
        ${buildFields(data, docType)}
        <div class="mb-3">
          <label class="form-label">Observaciones</label>
          <textarea class="form-control" id="f_observaciones" rows="2">${esc(data.observaciones || '')}</textarea>
        </div>
        <div class="d-grid gap-2 mt-4">
          <button class="btn btn-success btn-lg" onclick="saveData('${docType}')">
            <i class="fas fa-save me-2"></i>Guardar en Google Sheets
          </button>
          <button class="btn btn-outline-secondary" onclick="backToUpload()">
            <i class="fas fa-arrow-left me-2"></i>Volver
          </button>
        </div>
      </div>
    </div>`;

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* ── Constructores de campos por tipo ───────────────────────── */
function buildFields(d, docType) {
  if (docType === 'FACTURA') return buildFactura(d);
  if (docType === 'REMITO')  return buildRemito(d);
  return buildTicket(d);
}

function buildFactura(d) {
  return `
    <div class="field-row mb-3">
      <div>
        <label class="form-label">Fecha</label>
        <input class="form-control" id="f_fecha" value="${esc(d.fecha || '')}" placeholder="DD/MM/AAAA" />
      </div>
      <div>
        <label class="form-label">Tipo comprobante</label>
        <select class="form-select" id="f_tipo_comprobante">
          ${['A','B','C','M'].map(t => `<option ${d.tipo_comprobante===t?'selected':''}>${t}</option>`).join('')}
        </select>
      </div>
    </div>
    <div class="mb-3">
      <label class="form-label">Número (ej: 0001-00001234)</label>
      <input class="form-control" id="f_numero" value="${esc(d.numero || '')}" />
    </div>
    <div class="mb-3">
      <label class="form-label">Proveedor / Razón Social</label>
      <input class="form-control" id="f_proveedor" value="${esc(d.proveedor || '')}" />
    </div>
    <div class="mb-3">
      <label class="form-label">CUIT del proveedor</label>
      <input class="form-control" id="f_cuit" value="${esc(d.cuit || '')}" placeholder="XX-XXXXXXXX-X" />
    </div>
    <div class="field-row mb-3">
      <div>
        <label class="form-label">Subtotal (Neto)</label>
        <input class="form-control" id="f_subtotal" value="${esc(d.subtotal || '')}" inputmode="decimal" />
      </div>
      <div>
        <label class="form-label">IVA %</label>
        <select class="form-select" id="f_iva_porcentaje">
          ${['21','10.5','27','0'].map(p => `<option value="${p}" ${(d.iva_porcentaje||'21')===p?'selected':''}>${p}%</option>`).join('')}
        </select>
      </div>
    </div>
    <div class="field-row mb-3">
      <div>
        <label class="form-label">Monto IVA</label>
        <input class="form-control" id="f_iva_monto" value="${esc(d.iva_monto || '')}" inputmode="decimal" />
      </div>
      <div>
        <label class="form-label">Total</label>
        <input class="form-control fw-600" id="f_total" value="${esc(d.total || '')}" inputmode="decimal" />
      </div>
    </div>
    <div class="mb-3">
      <label class="form-label">CAE</label>
      <input class="form-control" id="f_cae" value="${esc(d.cae || '')}" inputmode="numeric" />
    </div>
    <div class="mb-3">
      <label class="form-label">Vencimiento CAE</label>
      <input class="form-control" id="f_vencimiento_cae" value="${esc(d.vencimiento_cae || '')}" placeholder="DD/MM/AAAA" />
    </div>`;
}

function buildRemito(d) {
  return `
    <div class="field-row mb-3">
      <div>
        <label class="form-label">Fecha</label>
        <input class="form-control" id="f_fecha" value="${esc(d.fecha || '')}" placeholder="DD/MM/AAAA" />
      </div>
      <div>
        <label class="form-label">Número / Orden</label>
        <input class="form-control" id="f_numero" value="${esc(d.numero || d.orden_salida || '')}" />
      </div>
    </div>
    <div class="field-row mb-3">
      <div>
        <label class="form-label">Orden de Salida</label>
        <input class="form-control" id="f_orden_salida" value="${esc(d.orden_salida || '')}" placeholder="DL-304" />
      </div>
      <div>
        <label class="form-label">Pack Nº</label>
        <input class="form-control" id="f_pack" value="${esc(d.pack || '')}" inputmode="numeric" />
      </div>
    </div>
    <div class="mb-3">
      <label class="form-label">Proveedor / Origen</label>
      <input class="form-control" id="f_proveedor" value="${esc(d.proveedor || '')}" />
    </div>
    <div class="mb-3">
      <label class="form-label">Destinatario</label>
      <input class="form-control" id="f_destinatario" value="${esc(d.destinatario || '')}" />
    </div>
    <div class="mb-3">
      <label class="form-label">Dirección de entrega</label>
      <input class="form-control" id="f_destino_direccion" value="${esc(d.destino_direccion || '')}" />
    </div>
    <div class="field-row mb-3">
      <div style="flex:2">
        <label class="form-label">Ciudad / Localidad</label>
        <input class="form-control" id="f_destino_localidad" value="${esc(d.destino_localidad || '')}" />
      </div>
      <div>
        <label class="form-label">Peso total (kg)</label>
        <input class="form-control" id="f_peso_total" value="${esc(d.peso_total || '')}" inputmode="decimal" />
      </div>
    </div>
    <div class="mb-3">
      <label class="form-label">Artículos</label>
      <textarea class="form-control" id="f_articulos" rows="6" style="font-family:monospace;font-size:.82rem">${esc(d.articulos || '')}</textarea>
      <div class="text-muted" style="font-size:.75rem;margin-top:4px">Formato sugerido: Código | Descripción | Cantidad | Peso</div>
    </div>`;
}

function buildTicket(d) {
  const cats = ['NAFTA/COMBUSTIBLE','PEAJE','ESTACIONAMIENTO','ALIMENTACION','HOSPEDAJE','OTRO'];
  return `
    <div class="field-row mb-3">
      <div>
        <label class="form-label">Fecha</label>
        <input class="form-control" id="f_fecha" value="${esc(d.fecha || '')}" placeholder="DD/MM/AAAA" />
      </div>
      <div>
        <label class="form-label">Monto</label>
        <input class="form-control fw-600" id="f_monto" value="${esc(d.monto || '')}" inputmode="decimal" />
      </div>
    </div>
    <div class="mb-3">
      <label class="form-label">Comercio / Lugar</label>
      <input class="form-control" id="f_comercio" value="${esc(d.comercio || '')}" />
    </div>
    <div class="mb-3">
      <label class="form-label">Concepto</label>
      <input class="form-control" id="f_concepto" value="${esc(d.concepto || '')}" />
    </div>
    <div class="mb-3">
      <label class="form-label">Categoría</label>
      <select class="form-select" id="f_categoria">
        ${cats.map(c => `<option value="${c}" ${(d.categoria||'OTRO')===c?'selected':''}>${c}</option>`).join('')}
      </select>
    </div>`;
}

/* ── Guardar en Sheets ──────────────────────────────────────── */
async function saveData(docType) {
  const data = {};
  document.querySelectorAll('[id^="f_"]').forEach(el => {
    data[el.id.slice(2)] = el.value.trim();
  });

  showLoading('Guardando en Google Sheets…', 'Enviando datos 📊');

  try {
    const res  = await fetch('/save', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ doc_type: docType, data }),
    });
    const json = await res.json();
    hideLoading();

    if (json.success) {
      showSuccess(json.message, docType);
    } else {
      showToast('❌ ' + (json.error || 'Error al guardar'), 'danger');
    }
  } catch (err) {
    hideLoading();
    showToast('❌ Error: ' + err.message, 'danger');
  }
}

/* ── Pantalla de éxito ──────────────────────────────────────── */
function showSuccess(msg, docType) {
  document.getElementById('viewResult').classList.add('d-none');
  const sv = document.getElementById('viewSuccess');
  sv.classList.remove('d-none');
  document.getElementById('successMsg').textContent = msg;
  document.getElementById('historyLink').href = `/history?type=${docType}`;
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* ── Volver al inicio ───────────────────────────────────────── */
function backToUpload() {
  document.getElementById('viewResult').classList.add('d-none');
  document.getElementById('viewResult').innerHTML = '';
  document.getElementById('viewUpload').classList.remove('d-none');
  setStep(2);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function resetApp() {
  document.getElementById('viewSuccess').classList.add('d-none');
  document.getElementById('viewResult').classList.add('d-none');
  document.getElementById('viewResult').innerHTML = '';
  document.getElementById('viewUpload').classList.remove('d-none');
  clearFile(null);
  setStep(1);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* ── Loading overlay ────────────────────────────────────────── */
function showLoading(title, subtitle) {
  const ov = document.getElementById('loadingOverlay');
  document.getElementById('loadingTitle').textContent    = title;
  document.getElementById('loadingSubtitle').textContent = subtitle;
  ov.classList.remove('d-none');
}
function hideLoading() {
  document.getElementById('loadingOverlay').classList.add('d-none');
}

/* ── Toast ──────────────────────────────────────────────────── */
function showToast(msg, type = 'secondary') {
  const toastEl = document.getElementById('mainToast');
  const icons = { success: '✅', danger: '❌', warning: '⚠️', info: 'ℹ️' };
  toastEl.className = `toast border-0 text-white bg-${type}`;
  document.getElementById('toastIcon').textContent = icons[type] || 'ℹ️';
  document.getElementById('toastMsg').textContent  = msg;
  bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 4000 }).show();
}

/* ── Helpers ────────────────────────────────────────────────── */
function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
function escHtml(str) { return esc(str); }
