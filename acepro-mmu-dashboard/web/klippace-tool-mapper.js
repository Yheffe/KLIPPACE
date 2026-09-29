/**
 * KLIPPACE Tool Mapper
 * Ultra-intuitive, 1-click slot selector and Auto-Match for ACE Pro in Fluidd.
 */

(function () {
  'use strict';

  console.log('[KLIPPACE] Tool Mapper module initializing...');

  let modalEl = null;
  let currentFilename = null;
  let currentMapping = [0, 1, 2, 3];
  let toolsData = [];
  let gatesData = [];
  let referencedTools = [];
  let showAllTools = false;
  let isPrintingAction = false;

  // --- Color Utilities ---
  function hexToRgb(hex) {
    if (!hex) return [128, 128, 128];
    hex = hex.replace('#', '').trim();
    if (hex.length === 3) {
      hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
    }
    const num = parseInt(hex, 16);
    if (isNaN(num)) return [128, 128, 128];
    return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
  }

  function colorDistance(rgb1, rgb2) {
    const dr = rgb1[0] - rgb2[0];
    const dg = rgb1[1] - rgb2[1];
    const db = rgb1[2] - rgb2[2];
    return 0.3 * (dr * dr) + 0.59 * (dg * dg) + 0.11 * (db * db);
  }

  // --- API Fetchers ---
  async function fetchMmuState() {
    try {
      const res = await fetch('/printer/objects/query?mmu');
      if (!res.ok) return null;
      const data = await res.json();
      return data?.result?.status?.mmu || null;
    } catch (e) {
      console.warn('[KLIPPACE] Failed to fetch MMU state:', e);
      return null;
    }
  }

  async function fetchFileMetadata(filename) {
    if (!filename) return null;
    try {
      const res = await fetch(`/server/files/metadata?filename=${encodeURIComponent(filename)}`);
      if (!res.ok) return null;
      const data = await res.json();
      return data?.result || null;
    } catch (e) {
      console.warn('[KLIPPACE] Failed to fetch file metadata:', e);
      return null;
    }
  }

  async function sendGcode(gcode) {
    try {
      await fetch('/printer/gcode/script', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ script: gcode }),
      });
    } catch (e) {
      console.error('[KLIPPACE] G-code send error:', e);
    }
  }

  async function startPrint(filename) {
    try {
      await fetch('/printer/print/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: filename }),
      });
      const app = document.getElementById('app')?.__vue__;
      if (app && app.$router && app.$route?.name !== 'home') {
        app.$router.push({ name: 'home' });
      }
    } catch (e) {
      console.error('[KLIPPACE] Start print error:', e);
    }
  }

  // --- Auto-Match Logic ---
  function runAutoMatch() {
    if (!toolsData.length || !gatesData.length) return;

    const matchedSlots = [];
    const usedGates = new Set();

    // Greedily find best matching gate for each tool
    toolsData.forEach((tool, tIdx) => {
      const tRgb = hexToRgb(tool.color);
      const tMat = (tool.material || '').trim().toUpperCase();

      let bestGate = 0;
      let lowestScore = Infinity;

      gatesData.forEach((gate, gIdx) => {
        const gRgb = hexToRgb(gate.color);
        const gMat = (gate.material || '').trim().toUpperCase();

        let score = colorDistance(tRgb, gRgb);

        // Material mismatch penalty
        if (tMat && gMat && tMat !== 'UNKNOWN' && gMat !== 'UNKNOWN' && tMat !== gMat) {
          score += 100000;
        }

        // Slight penalty if slot is already matched to avoid duplicate assignment if alternative exists
        if (usedGates.has(gIdx)) {
          score += 25000;
        }

        if (score < lowestScore) {
          lowestScore = score;
          bestGate = gIdx;
        }
      });

      usedGates.add(bestGate);
      currentMapping[tIdx] = bestGate;
    });

    renderRows();
    showToast('✨ Filaments auto-matched to ACE Pro slots by material & color!');
  }

  function showToast(msg) {
    const toast = document.getElementById('klippace-toast');
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.add('visible');
    setTimeout(() => {
      toast.classList.remove('visible');
    }, 2800);
  }

  // --- Modal DOM Construction ---
  function createModal() {
    if (document.getElementById('klippace-tool-mapper-overlay')) {
      return document.getElementById('klippace-tool-mapper-overlay');
    }

    const overlay = document.createElement('div');
    overlay.id = 'klippace-tool-mapper-overlay';
    overlay.className = 'klippace-overlay';

    overlay.innerHTML = `
      <div class="klippace-modal" role="dialog" aria-modal="true">
        <div class="klippace-header">
          <div class="klippace-header-title-group">
            <div class="klippace-icon-badge">
              <svg viewBox="0 0 24 24" width="22" height="22">
                <path fill="currentColor" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm0-12.5c-2.48 0-4.5 2.02-4.5 4.5s2.02 4.5 4.5 4.5 4.5-2.02 4.5-4.5-2.02-4.5-4.5-4.5zm0 6c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5z"/>
              </svg>
            </div>
            <div>
              <div class="klippace-title">Tool Mapping <span class="klippace-chip">ACE Pro</span></div>
              <div class="klippace-subtitle" id="klippace-subtitle">Pair sliced tools to physical ACE slots</div>
            </div>
          </div>
          <div class="klippace-header-actions">
            <button id="klippace-btn-automatch" class="klippace-btn-automatch" type="button" title="Auto-match tools to ACE slots by color and material">
              <span class="magic-icon">⚡</span> Auto-Match Filaments
            </button>
            <button id="klippace-btn-close" class="klippace-btn-icon" type="button" title="Close">
              <svg viewBox="0 0 24 24" width="20" height="20">
                <path fill="currentColor" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
              </svg>
            </button>
          </div>
        </div>

        <div id="klippace-toast" class="klippace-toast"></div>

        <div class="klippace-cols-header">
          <span>Sliced Tool (Slicer Expects)</span>
          <span>Feed From Physical ACE Slot (Click to Map)</span>
        </div>

        <div class="klippace-body" id="klippace-tool-rows">
          <!-- Tool rows will be injected here -->
        </div>

        <div class="klippace-footer">
          <div class="klippace-footer-left">
            <button id="klippace-btn-reset" class="klippace-btn klippace-btn-secondary" type="button">
              Reset (1:1)
            </button>
            <button id="klippace-btn-all-tools" class="klippace-btn klippace-btn-ghost" type="button" style="font-size: 0.82rem;">
              Show All Tools: Off
            </button>
          </div>
          <div class="klippace-footer-right">
            <button id="klippace-btn-cancel" class="klippace-btn klippace-btn-ghost" type="button">
              Cancel
            </button>
            <button id="klippace-btn-commit" class="klippace-btn klippace-btn-primary" type="button">
              <span id="klippace-commit-icon">🖨️</span>
              <span id="klippace-commit-text">Start Print</span>
            </button>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);

    // Event listeners
    document.getElementById('klippace-btn-close').addEventListener('click', closeModal);
    document.getElementById('klippace-btn-cancel').addEventListener('click', closeModal);
    document.getElementById('klippace-btn-automatch').addEventListener('click', runAutoMatch);
    document.getElementById('klippace-btn-reset').addEventListener('click', () => {
      currentMapping = [0, 1, 2, 3];
      renderRows();
      showToast('Reset mapping to default 1:1.');
    });
    document.getElementById('klippace-btn-all-tools').addEventListener('click', () => {
      showAllTools = !showAllTools;
      document.getElementById('klippace-btn-all-tools').textContent = `Show All Tools: ${showAllTools ? 'On' : 'Off'}`;
      renderRows();
    });
    document.getElementById('klippace-btn-commit').addEventListener('click', commitMapping);

    // Close on overlay click outside dialog
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeModal();
    });

    // Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && overlay.classList.contains('active')) {
        closeModal();
      }
    });

    return overlay;
  }

  // --- Render Rows ---
  function renderRows() {
    const container = document.getElementById('klippace-tool-rows');
    if (!container) return;

    container.innerHTML = '';

    const displayTools = toolsData.length > 0 ? toolsData : [
      { tool: 0, name: 'Tool 0', color: '#ff7f32', material: 'PLA', temp: 220, weight: '' },
      { tool: 1, name: 'Tool 1', color: '#ff3a2f', material: 'PLA', temp: 220, weight: '' },
      { tool: 2, name: 'Tool 2', color: '#eff0f1', material: 'PLA', temp: 220, weight: '' },
      { tool: 3, name: 'Tool 3', color: '#000000', material: 'PLA', temp: 220, weight: '' },
    ];

    displayTools.forEach((tool, tIdx) => {
      // Filter out unused tools if referenced_tools exists and showAllTools is false
      if (!showAllTools && referencedTools.length > 0 && !referencedTools.includes(tIdx)) {
        return;
      }

      const row = document.createElement('div');
      row.className = 'klippace-row';
      row.dataset.toolIndex = tIdx;

      // Sliced Tool Card (Left)
      const leftCol = document.createElement('div');
      leftCol.className = 'klippace-tool-info';
      leftCol.innerHTML = `
        <div class="klippace-tool-badge">T${tIdx}</div>
        <div class="klippace-swatch-wrapper">
          <div class="klippace-swatch" style="background-color: ${tool.color || '#888'};" title="${tool.color || ''}"></div>
        </div>
        <div class="klippace-tool-meta">
          <div class="klippace-tool-name">${tool.name || `Tool ${tIdx}`}</div>
          <div class="klippace-tool-submeta">
            <span class="klippace-mat-tag">${tool.material || 'PLA'}</span>
            ${tool.temp > 0 ? `<span class="klippace-temp-tag">${tool.temp}°C</span>` : ''}
            ${tool.weight ? `<span class="klippace-weight-tag">${tool.weight}g</span>` : ''}
          </div>
        </div>
      `;

      // Arrow (Center)
      const connector = document.createElement('div');
      connector.className = 'klippace-connector';
      connector.innerHTML = `
        <svg viewBox="0 0 24 24" width="20" height="20">
          <path fill="currentColor" d="M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z"/>
        </svg>
      `;

      // 4 Slot Pills (Right)
      const slotsGroup = document.createElement('div');
      slotsGroup.className = 'klippace-slots-group';

      const selectedSlot = currentMapping[tIdx] !== undefined ? currentMapping[tIdx] : tIdx;

      for (let sIdx = 0; sIdx < 4; sIdx++) {
        const gate = gatesData[sIdx] || { color: '#888', material: 'PLA' };
        const isSelected = selectedSlot === sIdx;

        const pill = document.createElement('button');
        pill.type = 'button';
        pill.className = `klippace-slot-pill ${isSelected ? 'active' : ''}`;
        pill.dataset.slotIndex = sIdx;
        pill.title = `Map Tool ${tIdx} to Slot ${sIdx} (${gate.material || 'PLA'})`;

        pill.innerHTML = `
          <div class="klippace-slot-swatch" style="background-color: ${gate.color || '#888'};"></div>
          <div class="klippace-slot-texts">
            <div class="klippace-slot-num">Slot ${sIdx}</div>
            <div class="klippace-slot-mat">${gate.material || 'PLA'}</div>
          </div>
          <div class="klippace-slot-check">✓</div>
        `;

        pill.addEventListener('click', () => {
          currentMapping[tIdx] = sIdx;
          renderRows();
        });

        slotsGroup.appendChild(pill);
      }

      row.appendChild(leftCol);
      row.appendChild(connector);
      row.appendChild(slotsGroup);
      container.appendChild(row);
    });
  }

  // --- Open / Close Modal ---
  async function openToolMapper(filename = null) {
    currentFilename = filename;
    isPrintingAction = !!filename;

    const overlay = createModal();

    // Update Subtitle & Action Button Text
    const subTitleEl = document.getElementById('klippace-subtitle');
    const commitTextEl = document.getElementById('klippace-commit-text');
    const commitIconEl = document.getElementById('klippace-commit-icon');

    if (filename) {
      const displayName = filename.split('/').pop();
      subTitleEl.innerHTML = `Printing: <span class="klippace-file-tag" title="${filename}">${displayName}</span>`;
      commitTextEl.textContent = 'Start Print';
      commitIconEl.textContent = '🖨️';
    } else {
      subTitleEl.textContent = 'Configure Tool to physical ACE Pro Slot mapping';
      commitTextEl.textContent = 'Save Mapping';
      commitIconEl.textContent = '💾';
    }

    // 1. Fetch live MMU State
    const mmu = await fetchMmuState();
    if (mmu) {
      gatesData = [];
      const numGates = mmu.num_gates || 4;
      for (let i = 0; i < numGates; i++) {
        gatesData.push({
          index: i,
          color: mmu.gate_color?.[i] || '#888888',
          material: mmu.gate_material?.[i] || 'PLA',
          name: mmu.gate_filament_name?.[i] || `Gate ${i}`,
        });
      }
      if (mmu.ttg_map && Array.isArray(mmu.ttg_map)) {
        currentMapping = Array.from(mmu.ttg_map);
      }
    }

    // 2. Fetch File Metadata if printing
    toolsData = [];
    referencedTools = [];

    if (filename) {
      const meta = await fetchFileMetadata(filename);
      if (meta) {
        let colors = meta.filament_colors || meta.extruder_colors || [];
        let types = meta.filament_type || [];
        if (typeof types === 'string') {
          try { types = JSON.parse(types); } catch (_) {}
        }
        let names = meta.filament_name || [];
        if (typeof names === 'string') {
          try { names = JSON.parse(names); } catch (_) {}
        }
        let temps = meta.filament_temps || [];
        let weights = meta.filament_weights || [];
        referencedTools = meta.referenced_tools || [];

        const count = Math.max(colors.length, types.length, referencedTools.length, 4);
        for (let i = 0; i < count; i++) {
          toolsData.push({
            tool: i,
            name: names[i] || `Tool ${i}`,
            color: colors[i] || gatesData[i]?.color || '#ff7f32',
            material: types[i] || 'PLA',
            temp: temps[i] || 220,
            weight: weights[i] ? Number(weights[i]).toFixed(1) : '',
          });
        }
      }
    }

    // Fallback if no file metadata
    if (toolsData.length === 0) {
      for (let i = 0; i < 4; i++) {
        toolsData.push({
          tool: i,
          name: `Tool ${i}`,
          color: gatesData[i]?.color || '#ff7f32',
          material: gatesData[i]?.material || 'PLA',
          temp: 220,
          weight: '',
        });
      }
    }

    renderRows();
    overlay.classList.add('active');

    // Hide any default Vuetify Happy Hare dialogs if opened in background
    setTimeout(() => {
      document.querySelectorAll('.v-dialog--active').forEach((d) => {
        if (
          d.querySelector('mmu-ttg-map, .min-width-map, .mmu-spool') ||
          d.textContent.includes('Edit TTG Map') ||
          d.textContent.includes('Edit Tool Mapping')
        ) {
          d.style.display = 'none';
        }
      });
    }, 50);
  }

  function closeModal() {
    const overlay = document.getElementById('klippace-tool-mapper-overlay');
    if (overlay) {
      overlay.classList.remove('active');
    }
    // Synchronize Fluidd's Vuex store dialog state to closed
    const app = document.getElementById('app')?.__vue__;
    if (app && app.$store) {
      app.$store.commit('mmu/setDialogState', { show: false });
    }
  }

  // --- Commit Mapping ---
  async function commitMapping() {
    const commitBtn = document.getElementById('klippace-btn-commit');
    if (commitBtn) {
      commitBtn.disabled = true;
      commitBtn.innerHTML = `<span>Saving...</span>`;
    }

    const mapStr = currentMapping.join(',');
    const endlessGroups = [0, 1, 2, 3].join(',');
    const gcode = `MMU_SLICER_TOOL_MAP SKIP_AUTOMAP=0\nMMU_TTG_MAP MAP="${mapStr}" QUIET=1\nMMU_ENDLESS_SPOOL GROUPS="${endlessGroups}" QUIET=1`;

    console.log('[KLIPPACE] Committing mapping:', mapStr);
    await sendGcode(gcode);

    if (currentFilename) {
      console.log('[KLIPPACE] Starting print:', currentFilename);
      await startPrint(currentFilename);
    }

    closeModal();

    if (commitBtn) {
      commitBtn.disabled = false;
      commitBtn.innerHTML = `<span id="klippace-commit-icon">🖨️</span> <span id="klippace-commit-text">${isPrintingAction ? 'Start Print' : 'Save Mapping'}</span>`;
    }
  }

  // --- Inject Quick Button into Fluidd Top Bar & MMU Card ---
  function injectButtons() {
    // 1. Top Bar Injection
    const appbar = document.querySelector('header.v-app-bar .v-toolbar__content, header .v-toolbar__content');
    if (appbar && !appbar.querySelector('.klippace-topbar-btn')) {
      const topBtn = document.createElement('button');
      topBtn.type = 'button';
      topBtn.className = 'klippace-topbar-btn';
      topBtn.innerHTML = `<span>⚡</span> Tool Mapper`;
      topBtn.title = 'Open ACE Pro Tool Mapper';
      topBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openToolMapper();
      });
      // Place right after the title or at a prominent position
      const titleEl = appbar.querySelector('.v-toolbar__title');
      if (titleEl && titleEl.nextSibling) {
        appbar.insertBefore(topBtn, titleEl.nextSibling);
      } else {
        appbar.appendChild(topBtn);
      }
    }

    // 2. Dashboard MMU Card Injection
    const mmuCards = document.querySelectorAll('.mmu-card, [layout-path="dashboard.mmu-card"]');
    mmuCards.forEach((card) => {
      if (card.querySelector('.klippace-quick-btn')) return;
      const headerActions = card.querySelector('.v-card__title, .card-heading, header');
      if (headerActions) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'klippace-quick-btn';
        btn.innerHTML = `<span>⚡</span> Tool Mapper`;
        btn.title = 'Open 1-Click ACE Pro Tool Mapper';
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          openToolMapper();
        });
        headerActions.insertBefore(btn, headerActions.firstChild);
      }
    });
  }

  // --- Watcher Setup ---
  function setupFluiddIntegration() {
    const appEl = document.getElementById('app');
    if (!appEl || !appEl.__vue__ || !appEl.__vue__.$store) {
      setTimeout(setupFluiddIntegration, 300);
      return;
    }

    const app = appEl.__vue__;
    console.log('[KLIPPACE] Connected to Fluidd root app and Vuex store!');

    // Watch Fluidd's mmu.dialog state
    app.$store.watch(
      (state) => state.mmu?.dialog,
      (newVal) => {
        if (newVal && newVal.show) {
          console.log('[KLIPPACE] Fluidd requested MMU dialog, opening KLIPPACE Tool Mapper:', newVal);
          openToolMapper(newVal.filename || null);
        } else if (newVal && !newVal.show) {
          const overlay = document.getElementById('klippace-tool-mapper-overlay');
          if (overlay && overlay.classList.contains('active')) {
            overlay.classList.remove('active');
          }
        }
      },
      { deep: true }
    );

    // Periodically check for UI elements to inject buttons
    setInterval(injectButtons, 1500);

    // Expose global opener for console or external macros
    window.openKlippaceToolMapper = openToolMapper;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupFluiddIntegration);
  } else {
    setupFluiddIntegration();
  }
})();
