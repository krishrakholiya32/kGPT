/* ===== kGPT Dashboard Logic ===== */

async function loadDashboard() {
  try {
    const res = await fetch('/api/dashboard/stats', { headers: authHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    renderDashboard(data);
  } catch (e) {}
}

function renderDashboard(data) {
  // Stats cards
  document.getElementById('stat-messages').textContent = data.total_messages || 0;

  const modes = data.messages_by_mode || {};

  // Mode bars
  const total = Object.values(modes).reduce((a, b) => a + b, 0) || 1;
  const modeColors = { general: '#6c63ff', rag: '#00d4aa', web: '#ffb347', sql: '#ff6b6b', code: '#4ecdc4' };
  const modeIcons = { general: '🤖', rag: '📄', web: '🌐', sql: '🗄️', code: '💻' };

  const barsEl = document.getElementById('mode-bars');
  barsEl.innerHTML = Object.entries(modes).length
    ? Object.entries(modes).sort((a, b) => b[1] - a[1]).map(([mode, count]) => `
        <div class="mode-bar-item">
          <div class="mode-bar-label">${modeIcons[mode] || '💬'} ${mode}</div>
          <div class="mode-bar-track">
            <div class="mode-bar-fill" style="width:${(count/total*100).toFixed(1)}%;background:${modeColors[mode] || '#6c63ff'}"></div>
          </div>
          <div class="mode-bar-count">${count}</div>
        </div>
      `).join('')
    : '<p style="color:var(--text-muted);font-size:13px">No data yet</p>';

  // Activity chart (last 7 days)
  const chartEl = document.getElementById('activity-chart');
  const days = data.messages_per_day || [];
  if (!days.length) {
    chartEl.innerHTML = '<p style="color:var(--text-muted);font-size:13px;text-align:center;padding:20px">No activity yet</p>';
    return;
  }
  const maxCount = Math.max(...days.map(d => d.count), 1);
  chartEl.innerHTML = `
    <div style="display:flex;align-items:flex-end;gap:8px;height:100px;padding-bottom:24px;position:relative">
      ${days.map(d => {
        const pct = (d.count / maxCount * 100).toFixed(0);
        const label = d.date.slice(5);
        return `
          <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;height:100%">
            <div style="flex:1;display:flex;align-items:flex-end;width:100%">
              <div style="width:100%;height:${pct}%;background:var(--accent);border-radius:4px 4px 0 0;min-height:3px;opacity:0.85;transition:height 0.4s" title="${d.count} messages"></div>
            </div>
            <div style="font-size:10px;color:var(--text-muted);white-space:nowrap">${label}</div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}