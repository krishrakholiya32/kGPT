/* ===== kGPT Documents Logic ===== */

async function loadDocuments() {
  try {
    const res = await fetch('/api/documents', { headers: authHeaders() });
    if (!res.ok) return;
    const docs = await res.json();
    renderDocuments(docs);
  } catch (e) {}
}

function renderDocuments(docs) {
  const list = document.getElementById('doc-list');
  if (!docs.length) {
    list.innerHTML = '<p style="color:var(--text-muted);font-size:14px;text-align:center;padding:20px">No documents uploaded yet</p>';
    return;
  }
  const icons = { pdf: '📕', docx: '📘', doc: '📘', csv: '📊', txt: '📝', md: '📝', json: '📋', html: '🌐' };
  list.innerHTML = docs.map(doc => {
    const ext = doc.filename.split('.').pop().toLowerCase();
    const icon = icons[ext] || '📄';
    const size = doc.size_bytes < 1024 ? `${doc.size_bytes} B` : doc.size_bytes < 1048576 ? `${(doc.size_bytes/1024).toFixed(1)} KB` : `${(doc.size_bytes/1048576).toFixed(1)} MB`;
    return `
      <div class="doc-item">
        <div class="doc-icon">${icon}</div>
        <div class="doc-info">
          <div class="doc-name">${doc.filename}</div>
          <div class="doc-size">${size}</div>
        </div>
        <div class="doc-status">Ingested ✓</div>
      </div>
    `;
  }).join('');
}

async function uploadFile(file) {
  const formData = new FormData();
  formData.append('file', file);
  showToast(`Uploading ${file.name}...`, 'warning');
  try {
    const res = await fetch('/api/documents/upload', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token()}` },
      body: formData
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`✓ ${file.name} ingested (${data.chunks} chunks)`, 'success');
      loadDocuments();
    } else {
      showToast(data.detail || 'Upload failed', 'error');
    }
  } catch (e) {
    showToast('Upload error: ' + e.message, 'error');
  }
}

async function ingestUrl() {
  const input = document.getElementById('url-input');
  const url = input.value.trim();
  if (!url) return showToast('Enter a URL first', 'warning');
  input.value = '';
  showToast('Ingesting URL...', 'warning');
  try {
    const res = await fetch('/api/documents/url', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ url })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`✓ URL ingested (${data.chunks} chunks)`, 'success');
      loadDocuments();
    } else {
      showToast(data.detail || 'URL ingestion failed', 'error');
    }
  } catch (e) {
    showToast('Error: ' + e.message, 'error');
  }
}

function initDropZone() {
  const zone = document.getElementById('upload-zone');
  const fileInput = document.getElementById('file-input');

  zone.onclick = () => fileInput.click();
  fileInput.onchange = e => {
    Array.from(e.target.files).forEach(uploadFile);
    fileInput.value = '';
  };

  zone.ondragover = e => { e.preventDefault(); zone.classList.add('drag-over'); };
  zone.ondragleave = () => zone.classList.remove('drag-over');
  zone.ondrop = e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    Array.from(e.dataTransfer.files).forEach(uploadFile);
  };
}
