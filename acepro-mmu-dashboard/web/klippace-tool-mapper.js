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

  // A single gate element, across both supported UIs:
  //   Fluidd  -> <div class="gate gate--menu bambu-ams-bay">
  //   Mainsail -> <div class="... gate-menu">   (no `.gate` class at all)
  // The two are mutually exclusive, so this never matches an element twice.
  // Wrapped in :is() so it can also be used as a descendant selector.
  const GATE_SELECTOR = ':is(.gate, .gate-menu)';

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

  // Toasts are raised from the card (slot editor, dryer) as well as from the
  // tool mapper. The in-modal element only exists once the tool mapper has been
  // built, so relying on it alone made every card toast disappear silently.
  // Fall back to a floating toast on <body> when the modal one is absent.
  function showToast(msg) {
    const timerKey = '_klippaceToastTimer';

    const inModal = document.getElementById('klippace-toast');
    let target = inModal;

    if (!target) {
      target = document.getElementById('klippace-toast-float');
      if (!target) {
        target = document.createElement('div');
        target.id = 'klippace-toast-float';
        target.className = 'klippace-toast-float';
        target.setAttribute('role', 'status');
        document.body.appendChild(target);
      }
      // Retrigger the entry animation for a repeated message.
      target.classList.remove('visible');
      void target.offsetWidth;
    }

    target.textContent = msg;
    target.classList.add('visible');
    clearTimeout(showToast[timerKey]);
    showToast[timerKey] = setTimeout(() => target.classList.remove('visible'), 2800);
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
          <span id="klippace-col-header-left">Sliced Tool (Slicer Expects)</span>
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

    // Last-resort view when neither file metadata nor gate data is available:
    // derive from the live ACE slots so we never invent a temperature.
    const displayTools = toolsData.length > 0 ? toolsData : [0, 1, 2, 3].map((i) => ({
      tool: i,
      name: `Tool ${i}`,
      color: gatesData[i]?.color || '#888888',
      material: gatesData[i]?.material || 'PLA',
      temp: gatesData[i]?.temp || 0,
      weight: '',
    }));

    displayTools.forEach((tool, tIdx) => {
      // Filter out unused tools if referenced_tools exists and showAllTools is false
      if (!showAllTools && referencedTools.length > 0 && !referencedTools.includes(tIdx)) {
        return;
      }

      const row = document.createElement('div');
      row.className = 'klippace-row';
      row.dataset.toolIndex = tIdx;

      // With no print file loaded there is nothing for a slicer to expect, so the
      // left card mirrors the live ACE slot this tool is currently mapped to.
      let cardTool = tool;
      let cardUnknown = false;
      if (!isPrintingAction) {
        const gateIdx = currentMapping[tIdx] !== undefined ? currentMapping[tIdx] : tIdx;
        const mappedGate = gatesData[gateIdx];
        if (mappedGate) {
          cardUnknown = isUnknownGate(mappedGate);
          cardTool = {
            ...tool,
            color: mappedGate.color || tool.color,
            material: mappedGate.material || tool.material,
            temp: mappedGate.temp || 0,
          };
        }
      }

      // Sliced Tool Card (Left)
      const leftCol = document.createElement('div');
      leftCol.className = 'klippace-tool-info';
      leftCol.innerHTML = `
        <div class="klippace-tool-badge">T${tIdx}</div>
        <div class="klippace-swatch-wrapper">
          <div class="klippace-swatch${cardUnknown ? ' klippace-swatch--unknown' : ''}"${cardUnknown ? ' title="No colour data"' : ` style="background-color: ${cardTool.color || '#888'};" title="${cardTool.color || ''}"`}></div>
        </div>
        <div class="klippace-tool-meta">
          <div class="klippace-tool-name">${cardTool.name || `Tool ${tIdx}`}</div>
          <div class="klippace-tool-submeta">
            <span class="klippace-mat-tag">${cardTool.material || 'PLA'}</span>
            ${cardTool.temp > 0 ? `<span class="klippace-temp-tag">${cardTool.temp}°C</span>` : ''}
            ${cardTool.weight ? `<span class="klippace-weight-tag">${cardTool.weight}g</span>` : ''}
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
        const gate = gatesData[sIdx] || { color: '#888', material: 'PLA', temp: 0 };
        const isSelected = selectedSlot === sIdx;
        const gateUnknown = isUnknownGate(gate);

        const pill = document.createElement('button');
        pill.type = 'button';
        pill.className = `klippace-slot-pill ${isSelected ? 'active' : ''}`;
        pill.dataset.slotIndex = sIdx;
        pill.title = `Map Tool ${tIdx} to Slot ${sIdx} (${gate.material || 'PLA'}${gate.temp > 0 ? ` ${gate.temp}°C` : ''})`;

        pill.innerHTML = `
          <div class="klippace-slot-swatch${gateUnknown ? ' klippace-slot-swatch--unknown' : ''}"${gateUnknown ? '' : ` style="background-color: ${gate.color || '#888'};"`}></div>
          <div class="klippace-slot-texts">
            <div class="klippace-slot-num">Slot ${sIdx}</div>
            <div class="klippace-slot-mat">${gate.material || 'PLA'}${gate.temp > 0 ? ` · ${gate.temp}°C` : ''}</div>
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

  // A slot holding filament the ACE cannot identify reports the #000000
  // sentinel with material "Unknown". Rendering that as a black disc would
  // read as black filament, so flag it for the striped placeholder.
  function isUnknownGate(gate) {
    if (!gate) return false;
    const hex = (gate.color || '').replace('#', '').toLowerCase();
    const mat = (gate.material || '').trim().toLowerCase();
    return (hex === '000000' || hex === '') && (mat === '' || mat === 'unknown');
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

    // Without a print file the left column mirrors the mapped ACE slot, so the
    // "what the slicer expects" wording would be misleading.
    const leftHeaderEl = document.getElementById('klippace-col-header-left');
    if (leftHeaderEl) {
      leftHeaderEl.textContent = filename
        ? 'Sliced Tool (Slicer Expects)'
        : 'Tool (Mapped ACE Slot)';
    }

    // 1. Fetch live MMU State
    const mmu = await fetchMmuState();
    if (mmu) {
      gatesData = [];
      const numGates = mmu.num_gates || 4;
      for (let i = 0; i < numGates; i++) {
        const mat = mmu.gate_material?.[i] || 'PLA';
        gatesData.push({
          index: i,
          color: mmu.gate_color?.[i] || '#888888',
          material: mat,
          // Authoritative source is the ACE slot inventory. The material table is
          // only a fallback for older shims / slots that store no temperature.
          temp: mmu.gate_temp?.[i] || lookupMaterialTemp(mat) || 0,
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

    // Fallback if no file metadata — mirror the live ACE slot inventory so the
    // tool cards show what is physically loaded, not a hardcoded default.
    if (toolsData.length === 0) {
      for (let i = 0; i < 4; i++) {
        toolsData.push({
          tool: i,
          name: `Tool ${i}`,
          color: gatesData[i]?.color || '#ff7f32',
          material: gatesData[i]?.material || 'PLA',
          temp: gatesData[i]?.temp || 0,
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

  // =========================================================================
  // DRYER — heat the ACE chamber to dry filament.
  // Ported from the standalone acepro-mmu-dashboard so the Fluidd card can
  // start/stop the dryer rather than only reporting its state.
  // =========================================================================

  function dryerState() {
    const unit = (cachedMmu && cachedMmu.unit && cachedMmu.unit[0]) || {};
    const drying = (unit.dryer_status === 'drying');
    const target = unit.dryer_target_temp || 0;
    const remain = unit.dryer_remain_time || 0;
    return { drying, target, remain, on: drying || target > 0 };
  }

  function describeDryer() {
    const { drying, target, remain, on } = dryerState();
    if (!on) return 'Off';
    if (!drying) return `Standby · target ${target}°C`;
    // `duration` is minutes but `remain_time` is SECONDS — an inconsistency in
    // the device reports, not here. Confirmed against serial_manager.py (logs
    // "remaining={n}s") and KlipperScreen/acepro.py (`remain_time // 3600`).
    // Rendering it raw is what produced "2664 min left" for a 60-minute dry.
    const mins = remain > 0 ? Math.round(remain / 60) : 0;
    let left = '';
    if (mins >= 1) left = ` · ${mins} min left`;
    else if (remain > 0) left = ' · under a minute left';
    return `Drying at ${target}°C${left}`;
  }

  function renderDryerModal() {
    const status = document.getElementById('klippace-dryer-status');
    if (!status) return;
    const { drying, target, on } = dryerState();
    const text = describeDryer();
    if (status.textContent !== text) status.textContent = text;
    const state = drying ? 'drying' : (on ? 'on' : 'off');
    if (status.dataset.state !== state) status.dataset.state = state;

    const startBtn = document.getElementById('klippace-dryer-start');
    const stopBtn = document.getElementById('klippace-dryer-stop');
    if (startBtn) startBtn.disabled = drying;
    if (stopBtn) stopBtn.disabled = !on;

  }

  function createDryerModal() {
    let overlay = document.getElementById('klippace-dryer-overlay');
    if (overlay) return overlay;

    overlay = document.createElement('div');
    overlay.id = 'klippace-dryer-overlay';
    overlay.className = 'klippace-overlay';
    overlay.innerHTML = `
      <div class="klippace-modal klippace-modal--narrow" role="dialog" aria-modal="true">
        <div class="klippace-header">
          <div class="klippace-header-title-group">
            <div class="klippace-icon-badge">
              <svg viewBox="0 0 24 24" width="22" height="22">
                <path fill="currentColor" d="M17.66 11.2c-.23-.3-.51-.56-.77-.82-.67-.6-1.43-1.03-2.07-1.66C13.33 7.26 13 4.85 13.95 3c-.95.23-1.78.75-2.49 1.32-2.59 2.08-3.61 5.75-2.39 8.9.04.1.08.2.08.33 0 .22-.15.42-.35.5-.23.1-.47.04-.66-.12a.58.58 0 0 1-.14-.17c-1.13-1.43-1.31-3.48-.55-5.12C5.78 10 4.87 12.3 5 14.47c.06.5.12 1 .29 1.5.14.45.35.87.6 1.27.35.55.79 1.04 1.3 1.45 2.15 1.72 5.32 1.7 7.45-.03 1.6-1.3 2.54-3.32 2.46-5.4 0-.26-.02-.52-.05-.78-.06-.5-.18-1-.36-1.48z"/>
              </svg>
            </div>
            <div>
              <div class="klippace-title">ACE Pro Dryer</div>
              <div class="klippace-subtitle">Heat the chamber to dry filament</div>
            </div>
          </div>
          <div class="klippace-header-actions">
            <button id="klippace-dryer-close" class="klippace-btn-icon" type="button" title="Close">
              <svg viewBox="0 0 24 24" width="20" height="20">
                <path fill="currentColor" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
              </svg>
            </button>
          </div>
        </div>

        <div class="klippace-editor-body">
          <div class="klippace-dryer-status" id="klippace-dryer-status" data-state="off">Off</div>

          <label class="klippace-field">
            <span class="klippace-field-label">Target temp (°C)</span>
            <input id="klippace-dryer-temp" class="klippace-input" type="number" min="30" max="70" step="5" value="50">
          </label>

          <label class="klippace-field">
            <span class="klippace-field-label">Duration (minutes)</span>
            <input id="klippace-dryer-duration" class="klippace-input" type="number" min="1" max="1440" step="10" value="240">
          </label>
        </div>

        <div class="klippace-footer">
          <div class="klippace-footer-left">
            <button id="klippace-dryer-stop" class="klippace-btn klippace-btn-ghost" type="button">Stop Dryer</button>
          </div>
          <div class="klippace-footer-right">
            <button id="klippace-dryer-cancel" class="klippace-btn klippace-btn-ghost" type="button">Cancel</button>
            <button id="klippace-dryer-start" class="klippace-btn klippace-btn-primary" type="button">Start Drying</button>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);
    const el = (id) => document.getElementById(id);

    el('klippace-dryer-close').addEventListener('click', closeDryerModal);
    el('klippace-dryer-cancel').addEventListener('click', closeDryerModal);
    el('klippace-dryer-temp').addEventListener('input', (e) => {
      e.target.dataset.touched = '1';
    });
    el('klippace-dryer-duration').addEventListener('input', (e) => {
      e.target.dataset.touched = '1';
    });
    el('klippace-dryer-start').addEventListener('click', startDryer);
    el('klippace-dryer-stop').addEventListener('click', stopDryer);

    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeDryerModal(); });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && overlay.classList.contains('active')) closeDryerModal();
    });

    return overlay;
  }

  async function openDryerModal() {
    const overlay = createDryerModal();
    // Refresh first so the status line and inputs reflect the real dryer.
    await getCachedMmu().catch(() => null);
    await seedDryerInputs();
    renderDryerModal();
    overlay.classList.add('active');
  }

  // The mmu shim's unit exposes the dryer target and remaining time but NOT the
  // configured duration, so read it from the ACE instance. Without this the
  // duration field always showed its default even while a shorter cycle ran.
  async function seedDryerInputs() {
    const el = (id) => document.getElementById(id);
    const tempInput = el('klippace-dryer-temp');
    const durInput = el('klippace-dryer-duration');
    if (!tempInput || !durInput) return;

    let duration = null;
    let target = null;
    try {
      const res = await fetch('/printer/objects/query?ace_instance_0');
      const data = await res.json();
      const inst = (data.result && data.result.status && data.result.status.ace_instance_0) || {};
      const dryer = inst.dryer_status || {};
      duration = Number(dryer.duration) || null;
      target = Number(dryer.target_temp) || null;
    } catch (e) {
      duration = null;
    }

    if (target && !tempInput.dataset.touched) tempInput.value = target;
    // Only overwrite the duration when a cycle is actually configured, so an
    // idle dryer leaves whatever the user last typed alone.
    if (duration && duration > 0 && !durInput.dataset.touched) {
      durInput.value = duration;
    }
  }

  function closeDryerModal() {
    const overlay = document.getElementById('klippace-dryer-overlay');
    if (overlay) overlay.classList.remove('active');
  }

  async function startDryer() {
    const el = (id) => document.getElementById(id);
    const temp = parseInt(el('klippace-dryer-temp').value, 10);
    const duration = parseInt(el('klippace-dryer-duration').value, 10);

    if (!Number.isFinite(temp) || temp < 30 || temp > 70) {
      showToast('Temperature must be between 30 and 70°C.');
      return;
    }
    if (!Number.isFinite(duration) || duration < 1) {
      showToast('Duration must be at least 1 minute.');
      return;
    }

    const btn = el('klippace-dryer-start');
    if (btn) { btn.disabled = true; btn.textContent = 'Starting…'; }
    try {
      await sendGcode(`ACE_START_DRYING TEMP=${temp} DURATION=${duration}`);
      closeDryerModal();
      showToast(`Dryer started: ${temp}°C for ${duration} min.`);
      setTimeout(() => { cachedMmu = null; mmuFetchedAt = 0; decorateAll(); }, 800);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Start Drying'; }
    }
  }

  async function stopDryer() {
    const btn = document.getElementById('klippace-dryer-stop');
    if (btn) { btn.disabled = true; btn.textContent = 'Stopping…'; }
    try {
      await sendGcode('ACE_STOP_DRYING');
      closeDryerModal();
      showToast('Dryer stopped.');
      setTimeout(() => { cachedMmu = null; mmuFetchedAt = 0; decorateAll(); }, 800);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Stop Dryer'; }
    }
  }

  // =========================================================================
  // SLOT EDITOR — manually set material/colour/temp for a slot.
  // Needed for non-RFID spools, which the ACE cannot identify automatically.
  // =========================================================================

  // Fallback material presets, used only when the backend table is unavailable
  // (page load race, older Klipper module). The authoritative list arrives as
  // mmu.material_temps from AceInstance.MATERIAL_TEMPS via the MMU shim.
  const MATERIAL_TEMPS_FALLBACK = {
    'PLA': 210, 'PLA+': 215, 'PLA-CF': 220, 'PLA Matte': 210, 'PLA Silk': 215,
    'PLA High Speed': 220, 'PETG': 240, 'PETG-CF': 250, 'ABS': 250, 'ASA': 260,
    'TPU': 230, 'TPE': 230, 'PVA': 200, 'HIPS': 240, 'PC': 270, 'PA': 260,
    'PA-CF': 280, 'Nylon': 260, 'POM': 220, 'PP': 240, 'PPS': 300,
    'PC-ABS': 265, 'PEEK': 380
  };

  // Live tables. Seeded from the fallback, then replaced wholesale by the
  // backend table so material names/temps have a single owner.
  let MATERIAL_TEMPS = Object.assign({}, MATERIAL_TEMPS_FALLBACK);
  let SLOT_MATERIALS = Object.keys(MATERIAL_TEMPS);
  let materialSource = 'fallback';

  // Adopt the backend's material table when present. Guarded against an empty
  // or truncated table so a bad payload cannot wipe the preset list.
  function syncMaterialTables(mmu) {
    const table = mmu && mmu.material_temps;
    if (!table || typeof table !== 'object') return;
    const names = Object.keys(table);
    if (names.length < 5) return;

    const next = {};
    names.forEach((name) => {
      const temp = parseInt(table[name], 10);
      if (name && Number.isFinite(temp) && temp > 0) next[name] = temp;
    });
    if (Object.keys(next).length < 5) return;

    MATERIAL_TEMPS = next;
    SLOT_MATERIALS = Object.keys(next);
    materialSource = 'backend';
  }

  // Case-insensitive material -> temp lookup against the live table.
  function lookupMaterialTemp(name) {
    if (!name) return 0;
    const key = String(name).trim();
    if (MATERIAL_TEMPS[key]) return MATERIAL_TEMPS[key];
    const lower = key.toLowerCase();
    const match = SLOT_MATERIALS.find(m => m.toLowerCase() === lower);
    return match ? MATERIAL_TEMPS[match] : 0;
  }

  // Rebuild the material <select> from the current table. The modal is created
  // once, so this runs on every open to pick up a late-arriving backend table.
  function populateMaterialOptions() {
    const sel = document.getElementById('klippace-editor-material');
    if (!sel) return;
    const rendered = [...sel.options].map(o => o.value).join('\u0000');
    const wanted = SLOT_MATERIALS.join('\u0000');
    if (rendered === wanted) return;
    const current = sel.value;
    sel.innerHTML = SLOT_MATERIALS
      .map(m => `<option value="${m}">${m}</option>`).join('');
    if (current && SLOT_MATERIALS.includes(current)) sel.value = current;
  }

  const SLOT_PALETTE = [
    '#ffffff', '#000000', '#808080', '#c0c0c0',
    '#ff0000', '#ff7f32', '#ffc800', '#ffff00',
    '#00ff00', '#008000', '#00ffff', '#0000ff',
    '#8000ff', '#ff00ff', '#8b4513', '#ffc0cb'
  ];

  // Presets loaded from localStorage (set by the standalone dashboard)
  function getStoredPresets() {
    try {
      const raw = localStorage.getItem('klippace_presets');
      return raw ? JSON.parse(raw) : [];
    } catch (e) { return []; }
  }

  let slotEditorState = { gateIndex: 0, material: 'PLA', temp: 210, color: '#ffffff', name: '' };

  function createSlotEditorModal() {
    let overlay = document.getElementById('klippace-slot-editor-overlay');
    if (overlay) return overlay;

    overlay = document.createElement('div');
    overlay.id = 'klippace-slot-editor-overlay';
    overlay.className = 'klippace-overlay';

    const matOptions = SLOT_MATERIALS.map(m => `<option value="${m}">${m}</option>`).join('');
    const swatches = SLOT_PALETTE.map(c =>
      `<button type="button" class="klippace-palette-chip" data-color="${c}" style="background:${c};" title="${c}"></button>`
    ).join('');

    overlay.innerHTML = `
      <div class="klippace-modal klippace-modal--narrow" role="dialog" aria-modal="true">
        <div class="klippace-header">
          <div class="klippace-header-title-group">
            <div class="klippace-icon-badge">
              <svg viewBox="0 0 24 24" width="22" height="22">
                <path fill="currentColor" d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>
              </svg>
            </div>
            <div>
              <div class="klippace-title">Edit Slot <span class="klippace-chip" id="klippace-editor-chip">T3</span></div>
              <div class="klippace-subtitle">Set filament data for a spool the ACE cannot read</div>
            </div>
          </div>
          <div class="klippace-header-actions">
            <button id="klippace-editor-close" class="klippace-btn-icon" type="button" title="Close">
              <svg viewBox="0 0 24 24" width="20" height="20">
                <path fill="currentColor" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
              </svg>
            </button>
          </div>
        </div>

        <div class="klippace-editor-body">
          <div class="klippace-editor-preview">
            <div class="klippace-editor-swatch" id="klippace-editor-swatch"></div>
            <div class="klippace-editor-preview-text">
              <div class="klippace-editor-preview-mat" id="klippace-editor-preview-mat">PLA</div>
              <div class="klippace-editor-preview-temp" id="klippace-editor-preview-temp">210°C</div>
            </div>
          </div>

          <label class="klippace-field">
            <span class="klippace-field-label">Material</span>
            <select id="klippace-editor-material" class="klippace-input">${matOptions}</select>
          </label>

          <label class="klippace-field">
            <span class="klippace-field-label">Nozzle temp (°C)</span>
            <input id="klippace-editor-temp" class="klippace-input" type="number" min="150" max="350" step="5">
          </label>

          <div class="klippace-field">
            <span class="klippace-field-label">Colour</span>
            <div class="klippace-color-row">
              <input id="klippace-editor-color" class="klippace-color-input" type="color">
              <div class="klippace-palette">${swatches}</div>
            </div>
          </div>

          <label class="klippace-field">
            <span class="klippace-field-label">Preset name <span class="klippace-optional">(optional)</span></span>
            <input id="klippace-editor-name" class="klippace-input" type="text" placeholder="e.g. Prusament Galaxy Black">
          </label>

          <label class="klippace-field klippace-field--preset" id="klippace-editor-preset-wrap" style="display:none;">
            <span class="klippace-field-label">Saved preset</span>
            <select id="klippace-editor-preset" class="klippace-input"></select>
          </label>

          <!-- Filament actions act immediately; they are not part of Save -->
          <div class="klippace-field klippace-field--actions">
            <span class="klippace-field-label">Filament</span>

            <div class="klippace-action-row">
              <button id="klippace-editor-feed-assist" class="klippace-btn klippace-btn-ghost klippace-btn-sm" type="button"
                      title="Hold this slot's filament under tension while printing">Feed Assist</button>
              <span class="klippace-action-hint" id="klippace-editor-assist-state">…</span>
            </div>

            <div class="klippace-action-row">
              <input id="klippace-editor-length" class="klippace-input klippace-input--num" type="number"
                     min="1" max="500" step="5" value="40" aria-label="Filament length in mm">
              <span class="klippace-action-unit">mm</span>
              <button id="klippace-editor-feed" class="klippace-btn klippace-btn-ghost klippace-btn-sm" type="button">Feed</button>
              <button id="klippace-editor-retract" class="klippace-btn klippace-btn-ghost klippace-btn-sm" type="button">Retract</button>
            </div>
          </div>
        </div>

        <div class="klippace-footer">
          <div class="klippace-footer-left">
            <button id="klippace-editor-clear" class="klippace-btn klippace-btn-ghost" type="button" title="Wipe the material data but keep the spool slot in use">Clear Data</button>
            <button id="klippace-editor-empty" class="klippace-btn klippace-btn-ghost" type="button" title="Tell Klipper this slot no longer holds a spool">Mark Empty</button>
          </div>
          <div class="klippace-footer-right">
            <button id="klippace-editor-cancel" class="klippace-btn klippace-btn-ghost" type="button">Cancel</button>
            <button id="klippace-editor-save" class="klippace-btn klippace-btn-primary" type="button">Save Slot</button>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);

    const el = (id) => document.getElementById(id);

    el('klippace-editor-close').addEventListener('click', closeSlotEditor);
    el('klippace-editor-cancel').addEventListener('click', closeSlotEditor);
    el('klippace-editor-save').addEventListener('click', () => saveSlotEditor(false));
    el('klippace-editor-clear').addEventListener('click', () => {
      if (confirm('Clear this slot\u2019s filament data?\n\nThe spool stays marked as loaded, but the material and colour are forgotten so you can re-enter them.')) {
        clearSlotEditor();
      }
    });
    el('klippace-editor-empty').addEventListener('click', () => {
      if (confirm('Mark this slot as empty?\n\nThis tells Klipper the slot no longer holds a spool.')) {
        saveSlotEditor(true);
      }
    });

    el('klippace-editor-material').addEventListener('change', (e) => {
      slotEditorState.material = e.target.value;
      const t = lookupMaterialTemp(e.target.value);
      if (t) { slotEditorState.temp = t; el('klippace-editor-temp').value = t; }
      refreshSlotEditorPreview();
    });

    // Filament actions — these act immediately and are deliberately outside the
    // Save/Clear flow, which only writes slot metadata.
    el('klippace-editor-feed-assist').addEventListener('click', toggleSlotFeedAssist);
    el('klippace-editor-feed').addEventListener('click', () => moveSlotFilament(1));
    el('klippace-editor-retract').addEventListener('click', () => moveSlotFilament(-1));

    el('klippace-editor-temp').addEventListener('input', (e) => {
      slotEditorState.temp = parseInt(e.target.value, 10) || 0;
      refreshSlotEditorPreview();
    });
    el('klippace-editor-color').addEventListener('input', (e) => {
      slotEditorState.color = e.target.value;
      refreshSlotEditorPreview();
    });
    el('klippace-editor-name').addEventListener('input', (e) => {
      slotEditorState.name = e.target.value;
    });
    el('klippace-editor-preset').addEventListener('change', (e) => {
      const preset = getStoredPresets().find(p => p.name === e.target.value);
      if (!preset) return;
      slotEditorState.material = preset.material || slotEditorState.material;
      slotEditorState.temp = preset.temp || slotEditorState.temp;
      if (preset.color) slotEditorState.color = preset.color;
      el('klippace-editor-material').value = slotEditorState.material;
      el('klippace-editor-temp').value = slotEditorState.temp;
      el('klippace-editor-color').value = slotEditorState.color;
      el('klippace-editor-name').value = preset.name;
      slotEditorState.name = preset.name;
      refreshSlotEditorPreview();
    });

    overlay.querySelectorAll('.klippace-palette-chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        slotEditorState.color = chip.dataset.color;
        el('klippace-editor-color').value = chip.dataset.color;
        refreshSlotEditorPreview();
      });
    });

    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeSlotEditor(); });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && overlay.classList.contains('active')) closeSlotEditor();
    });

    return overlay;
  }

  function refreshSlotEditorPreview() {
    const swatch = document.getElementById('klippace-editor-swatch');
    const matEl = document.getElementById('klippace-editor-preview-mat');
    const tempEl = document.getElementById('klippace-editor-preview-temp');
    if (swatch) swatch.style.backgroundColor = slotEditorState.color;
    if (matEl) matEl.textContent = slotEditorState.material || '—';
    if (tempEl) tempEl.textContent = (slotEditorState.temp > 0) ? `${slotEditorState.temp}°C` : '—';
  }

  async function openSlotEditor(gateIndex) {
    const overlay = createSlotEditorModal();
    const el = (id) => document.getElementById(id);

    // Prefer the cached MMU snapshot, but fetch if we do not have one yet so
    // the authoritative material table is available on the very first open.
    let mmu = cachedMmu;
    if (!mmu) {
      mmu = await getCachedMmu().catch(() => null);
    }
    mmu = mmu || {};

    // Adopt the backend's material table, then refresh the preset list before
    // we bind a value to it (the modal markup is created only once).
    syncMaterialTables(mmu);
    populateMaterialOptions();

    const gateColor = mmu.gate_color?.[gateIndex];
    const gateMat = (mmu.gate_material?.[gateIndex] || '').trim();
    const gateTemp = mmu.gate_temp?.[gateIndex] || 0;
    const isUnknown = (!gateMat || gateMat.toLowerCase() === 'unknown')
      || (gateColor || '').replace('#', '').toLowerCase() === '000000';

    // Prefer the temperature recorded against the ACE slot; only fall back to a
    // material suggestion when the slot itself stores no temperature.
    slotEditorState = {
      gateIndex,
      material: (!gateMat || gateMat.toLowerCase() === 'unknown') ? 'PLA' : gateMat,
      temp: gateTemp || lookupMaterialTemp(gateMat) || 210,
      color: (!gateColor || (isUnknown && gateColor === '#000000')) ? '#ffffff' : gateColor,
      name: ''
    };

    el('klippace-editor-chip').textContent = `T${gateIndex}`;
    el('klippace-editor-material').value = slotEditorState.material;
    el('klippace-editor-temp').value = slotEditorState.temp;
    el('klippace-editor-color').value = slotEditorState.color;
    el('klippace-editor-name').value = '';

    // Populate preset dropdown if presets exist
    const presets = getStoredPresets();
    const presetWrap = el('klippace-editor-preset-wrap');
    const presetSel = el('klippace-editor-preset');
    if (presets.length) {
      presetSel.innerHTML = '<option value="">— pick —</option>' +
        presets.map(p => `<option value="${p.name}">${p.name}</option>`).join('');
      presetWrap.style.display = '';
    } else {
      presetWrap.style.display = 'none';
    }

    refreshSlotEditorPreview();
    overlay.classList.add('active');

    // Feed-assist state lives on the ACE instance object, not the mmu shim, so
    // read it lazily rather than gating the modal on a second round trip.
    slotEditorState.feedAssist = false;
    renderFeedAssistState();
    refreshFeedAssistState();
  }

  function closeSlotEditor() {
    const overlay = document.getElementById('klippace-slot-editor-overlay');
    if (overlay) overlay.classList.remove('active');
  }

  // ---------------------------------------------------------------------------
  // Per-slot filament actions (feed assist, feed, retract)
  //
  // These animate hardware, so they run on click rather than on Save — Save only
  // writes slot metadata. The gate index is translated to an ACE instance +
  // local slot via the shim's unit metadata, so a multi-unit setup addresses the
  // right object instead of assuming ace_instance_0.
  // ---------------------------------------------------------------------------

  function instanceForGate(gate) {
    const units = (cachedMmu && Array.isArray(cachedMmu.unit)) ? cachedMmu.unit : [];
    for (let i = 0; i < units.length; i++) {
      const first = Number.isFinite(units[i].first_gate) ? units[i].first_gate : i * 4;
      const count = Number.isFinite(units[i].num_gates) ? units[i].num_gates : 4;
      if (gate >= first && gate < first + count) {
        return { name: `ace_instance_${i}`, local: gate - first };
      }
    }
    return { name: 'ace_instance_0', local: gate };
  }

  function renderFeedAssistState() {
    const hint = document.getElementById('klippace-editor-assist-state');
    const btn = document.getElementById('klippace-editor-feed-assist');
    if (!hint || !btn) return;
    const on = !!slotEditorState.feedAssist;
    const text = on ? 'On' : 'Off';
    if (hint.textContent !== text) hint.textContent = text;
    hint.dataset.state = on ? 'on' : 'off';
    btn.textContent = on ? 'Disable' : 'Enable';
  }

  async function refreshFeedAssistState() {
    const { name, local } = instanceForGate(slotEditorState.gateIndex);
    let on = false;
    try {
      const res = await fetch(`/printer/objects/query?${name}`);
      const data = await res.json();
      const obj = (data.result && data.result.status && data.result.status[name]) || {};
      on = (obj.feed_assist_slot === local);
    } catch (e) {
      on = false;
    }
    slotEditorState.feedAssist = on;
    renderFeedAssistState();
  }

  async function toggleSlotFeedAssist() {
    const idx = slotEditorState.gateIndex;
    const on = !slotEditorState.feedAssist;
    const verb = on ? 'ACE_ENABLE_FEED_ASSIST' : 'ACE_DISABLE_FEED_ASSIST';
    await sendGcode(`${verb} T=${idx}`);
    slotEditorState.feedAssist = on;
    renderFeedAssistState();
    showToast(`Feed assist ${on ? 'enabled' : 'disabled'} on T${idx}.`);
  }

  async function moveSlotFilament(direction) {
    const idx = slotEditorState.gateIndex;
    const input = document.getElementById('klippace-editor-length');
    const length = parseInt(input ? input.value : '', 10);
    if (!Number.isFinite(length) || length <= 0) {
      showToast('Enter a length greater than 0 mm.');
      return;
    }
    const cmd = direction > 0 ? 'ACE_FEED' : 'ACE_RETRACT';
    const verb = direction > 0 ? 'Feeding' : 'Retracting';
    await sendGcode(`${cmd} T=${idx} LENGTH=${length}`);
    showToast(`${verb} ${length}mm on T${idx}.`);
  }

  // Discard the stored material/colour/temp but keep the slot marked as holding
  // a spool. Distinct from "Mark Empty", which tells Klipper there is no spool.
  async function clearSlotEditor() {
    const idx = slotEditorState.gateIndex;
    await sendGcode(`ACE_SET_SLOT T=${idx} CLEAR=1\nACE_SAVE_INVENTORY`);
    closeSlotEditor();
    showToast(`Slot T${idx} data cleared — spool still marked loaded.`);
    cachedMmu = null;
    mmuFetchedAt = 0;
    setTimeout(decorateAll, 600);
  }

  async function saveSlotEditor(markEmpty) {
    const saveBtn = document.getElementById('klippace-editor-save');
    const idx = slotEditorState.gateIndex;

    if (markEmpty) {
      await sendGcode(`ACE_SET_SLOT T=${idx} EMPTY=1\nACE_SAVE_INVENTORY`);
      closeSlotEditor();
      showToast(`Slot T${idx} marked empty.`);
      setTimeout(decorateAll, 600);
      return;
    }
    const temp = parseInt(slotEditorState.temp, 10) || 0;
    if (!slotEditorState.material || temp <= 0) {
      showToast('Material and temperature are required.');
      return;
    }

    const rgb = hexToRgb(slotEditorState.color);
    const safeMat = String(slotEditorState.material).replace(/"/g, '\\"');
    const safeName = String(slotEditorState.name || '').replace(/"/g, '\\"');

    let script = `ACE_SET_SLOT T=${idx} COLOR="${rgb[0]},${rgb[1]},${rgb[2]}" ` +
                 `MATERIAL="${safeMat}" TEMP=${temp}`;
    if (safeName) script += ` FILAMENT_SETTINGS_ID="${safeName}"`;

    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving...'; }

    try {
      await sendGcode(script);
      await sendGcode('ACE_SAVE_INVENTORY');
      closeSlotEditor();
      showToast(`T${idx} saved: ${slotEditorState.material} ${temp}°C`);
      // Optimistically update the card, then refresh from the backend
      const swatch = document.querySelectorAll(`.mmu-unit:not(.mmu-unit-clear) ${GATE_SELECTOR}`)[idx]?.querySelector('.klippace-swatch');
      if (swatch) {
        swatch.dataset.nocolor = 'false';
        swatch.dataset.klippaceColor = slotEditorState.color;
        swatch.style.backgroundColor = slotEditorState.color;
      }
      setTimeout(() => { cachedMmu = null; mmuFetchedAt = 0; decorateAll(); }, 700);
    } finally {
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save Slot'; }
    }
  }

  // Re-run decoration across every MMU card
  function decorateAll() {
    findMmuCards().forEach((c) => decorateBambuMmuCard(c));
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
  // The card CSS ships as a real stylesheet: klippace-tool-mapper.css, linked
  // into Fluidd's index.html by install.sh. Inject the <link> ourselves when it
  // is missing — a purely manual install, or a Fluidd update that replaced
  // index.html — so the card is never left unstyled.
  const KLIPPACE_STYLESHEET = 'klippace-tool-mapper.css';

  function ensureStyleSheet() {
    // Match on "contains", not "ends with": install.sh writes the href with a
    // cache-busting query string ("./klippace-tool-mapper.css?v=123456"), which
    // an attribute-ends-with selector would miss and cause a second, duplicate
    // stylesheet to be injected.
    const present = document.querySelector(
      'link[rel="stylesheet"][href*="' + KLIPPACE_STYLESHEET + '"]'
    );
    if (present) return;
    const link = document.createElement('link');
    link.id = 'klippace-card-style';
    link.rel = 'stylesheet';
    link.href = './' + KLIPPACE_STYLESHEET;
    document.head.appendChild(link);
  }

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

    // 2. Dashboard MMU Card Injection & Bambu Lab AMS Styling
    const mmuCards = findMmuCards();
    mmuCards.forEach((card) => {
      // Apply Bambu AMS style decoration
      decorateBambuMmuCard(card);
    });
  }

  // Helper to locate Fluidd MMU card across different Fluidd/Vuetify DOM variants
  function findMmuCards() {
    const list = [];
    const directMatches = document.querySelectorAll('.bambu-ams-card, .mmu-card, [layout-path="dashboard.mmu-card"]');
    directMatches.forEach((el) => {
      if (!list.includes(el)) list.push(el);
    });

    const allCards = document.querySelectorAll('.v-card');
    allCards.forEach((c) => {
      if (list.includes(c)) return;
      if (c.closest('#klippace-tool-mapper-overlay')) return;
      if (c.querySelector(`.mmu-unit, ${GATE_SELECTOR}, .mmu-controls, .mmu-gate-summary, svg.clip-spool, [ref="mmuControls"]`)) {
        list.push(c);
        return;
      }
      const titleEl = c.querySelector('.v-card__title, .card-heading, header');
      if (titleEl && /mmu|happy hare/i.test(titleEl.textContent)) {
        list.push(c);
      }
    });
    return list;
  }

  // --- Gate tile building (color swatches) ---
  let cachedMmu = null;
  let mmuFetchedAt = 0;
  let mmuFetchPromise = null;
  const MMU_CACHE_TTL_MS = 3000;

  function getCachedMmu() {
    const fresh = cachedMmu && (Date.now() - mmuFetchedAt < MMU_CACHE_TTL_MS);
    if (fresh) return Promise.resolve(cachedMmu);
    if (mmuFetchPromise) return mmuFetchPromise;
    // Do NOT permanently cache a null result (the first query often runs before
    // Moonraker connects, returning null) — otherwise swatch colours stay blank.
    // A short TTL also keeps colours current after spool/tool changes.
    // Clearing the in-flight promise afterwards lets a later call retry.
    mmuFetchPromise = fetchMmuState()
      .then((m) => { if (m) { cachedMmu = m; mmuFetchedAt = Date.now(); } return m; })
      .catch(() => null)
      .then((m) => { mmuFetchPromise = null; return m; });
    return mmuFetchPromise;
  }

  function buildGateTiles(card) {
    const unit = card.querySelector('.mmu-unit:not(.mmu-unit-clear)');
    if (!unit) return;

    // Intercept gate clicks in the CAPTURE phase on the card so the native
    // per-gate menu (Vuetify) never receives the event. A bubble-phase handler
    // on the gate itself is too late — Vuetify's listener runs first and opens
    // its own "Gate N" menu.
    if (!card.dataset.klippaceGateClick) {
      card.dataset.klippaceGateClick = '1';
      card.addEventListener('click', (e) => {
        const gate = e.target && e.target.closest ? e.target.closest(GATE_SELECTOR) : null;
        if (!gate || !card.contains(gate)) return;
        const gates = Array.from(card.querySelectorAll(`.mmu-unit:not(.mmu-unit-clear) ${GATE_SELECTOR}`));
        const idx = gates.indexOf(gate);
        if (idx < 0) return;
        e.stopPropagation();
        e.preventDefault();
        openSlotEditor(idx);
      }, true);
    }

    unit.querySelectorAll(GATE_SELECTOR).forEach((gate, i) => {
      gate.style.cursor = 'pointer';
      gate.title = `Edit slot T${i} (click to set material/colour)`;

      if (gate.querySelector('.klippace-swatch')) return; // DOM already built

      const swatch = document.createElement('div');
      swatch.className = 'klippace-swatch';
      gate.insertBefore(swatch, gate.firstChild);

      // Slot badge: gate number + spool-present indicator, replacing the native
      // (hardcoded-green) ring so the indicator reflects real spool presence.
      const slot = document.createElement('div');
      slot.className = 'klippace-slot';
      slot.innerHTML = `
        <span class="klippace-slot-dot" data-present="unknown"></span>
        <span class="klippace-slot-num">${i}</span>
      `;
      gate.appendChild(slot);

      const material = document.createElement('div');
      material.className = 'klippace-gate-material';
      material.textContent = '';
      gate.appendChild(material);
    });
  }

  function updateStatusRibbon(card, mmu) {
    const ribbon = card.querySelector('.bambu-status-ribbon');
    if (!ribbon) return;
    const title = ribbon.querySelector('.bambu-status-title');
    const temp = ribbon.querySelector('.bambu-temp-badge');
    const dot = ribbon.querySelector('.bambu-status-dot');

    // Authoritative MMU state. `gate`/`tool` are the SELECTED index only and do
    // NOT indicate whether filament is actually loaded — that is `filament_pos`
    // (bowden → splitter → toolhead → nozzle) and `action`. Using `gate` here was
    // what made the state look wrong/inconsistent.
    const action = String(mmu.action || 'Idle');
    const pos = String(mmu.filament_pos || 'bowden').toLowerCase();
    const gate = (typeof mmu.gate === 'number' && mmu.gate >= 0) ? mmu.gate : null;
    const tool = (typeof mmu.tool === 'number' && mmu.tool >= 0) ? mmu.tool : null;
    const id = tool != null ? `T${tool}` : (gate != null ? `Gate ${gate}` : '');

    let stateText, stateClass;
    if (action && action.toLowerCase() !== 'idle') {
      // e.g. Loading, Unloading, Exchanging, Checking
      stateText = id ? `${action} · ${id}` : action;
      stateClass = 'busy';
    } else if (pos === 'nozzle') {
      stateText = id ? `Loaded · ${id}` : 'Loaded';
      stateClass = 'loaded';
    } else if (pos === 'toolhead') {
      stateText = id ? `At toolhead · ${id}` : 'At toolhead';
      stateClass = 'partial';
    } else if (pos === 'splitter') {
      stateText = id ? `At splitter · ${id}` : 'At splitter';
      stateClass = 'partial';
    } else {
      stateText = id ? `Unloaded · ${id}` : 'Unloaded';
      stateClass = 'unloaded';
    }

    if (title) {
      if (title.textContent !== stateText) title.textContent = stateText;
      if (title.dataset.state !== stateClass) {
        title.dataset.state = stateClass;
        ribbon.dataset.state = stateClass;
      }
    }
    if (dot && dot.dataset.state !== stateClass) {
      dot.dataset.state = stateClass;
    }

    if (temp) {
      const unit = mmu.unit?.[0] || {};
      // The native text carries "32°C · Dryer Off" as one string; the two are
      // now separate elements so the dryer half can be its own control.
      const t = (unit.temp != null) ? `${unit.temp}°C` : '';
      if (temp.textContent !== t) temp.textContent = t;
    }

    const dryerBtn = ribbon.querySelector('.klippace-dryer-btn');
    if (dryerBtn) {
      const unit = mmu.unit?.[0] || {};
      const drying = (unit.dryer_status === 'drying');
      const on = drying || (unit.dryer_target_temp || 0) > 0;
      const label = drying ? 'Drying' : (on ? 'Dryer On' : 'Dryer Off');
      const state = drying ? 'drying' : (on ? 'on' : 'off');
      if (dryerBtn.textContent !== label) dryerBtn.textContent = label;
      if (dryerBtn.dataset.state !== state) dryerBtn.dataset.state = state;
    }
  }

  function applyGateData(card, mmu) {
    if (!mmu) return;
    const unit = card.querySelector('.mmu-unit:not(.mmu-unit-clear)');
    if (!unit) return;
    const activeGate = (typeof mmu.gate === 'number' && mmu.gate >= 0) ? mmu.gate : -1;
    unit.querySelectorAll(GATE_SELECTOR).forEach((gate, i) => {
      const swatch = gate.querySelector('.klippace-swatch');
      if (swatch) {
        const color = mmu.gate_color?.[i] || '#666666';
        const mat = mmu.gate_material?.[i] || '';
        // "#000000" (all-zero RGB) is the sentinel the ACE module uses for
        // "no colour data" (DEFAULT_COLOR = [0,0,0]). Rendering it as pure black
        // makes the swatch look like a hollow hole and is ambiguous with a real
        // black spool. Treat all-zero + unknown material as "unknown" so it gets
        // a distinct neutral placeholder instead.
        const rgbMatch = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color.replace('#', ''));
        const isAllZero = rgbMatch
          ? (parseInt(rgbMatch[1], 16) === 0 && parseInt(rgbMatch[2], 16) === 0 && parseInt(rgbMatch[3], 16) === 0)
          : false;
        const matUnknown = !mat || mat.toLowerCase() === 'unknown';
        const noColor = isAllZero && matUnknown;
        if (swatch.dataset.nocolor !== (noColor ? 'true' : 'false')) {
          swatch.dataset.nocolor = noColor ? 'true' : 'false';
        }
        // Track in a data attribute (NOT style readback) so this stays
        // idempotent: the browser normalizes "#ff7f32" -> "rgb(255,127,50)"
        // on readback, which would otherwise make this write every pass and
        // re-trigger the MutationObserver in an endless loop.
        if (swatch.dataset.klippaceColor !== color) {
          swatch.dataset.klippaceColor = color;
          swatch.style.backgroundColor = color;
        }
      }
      const material = gate.querySelector('.klippace-gate-material');
      let needsData = false;
      if (material) {
        const mat = (mmu.gate_material?.[i] || '').trim();
        // Show a label for every slot — "Unknown" when there's no material data,
        // rather than leaving it blank.
        const label = (mat && mat.toLowerCase() !== 'unknown') ? mat : 'Unknown';
        if (material.textContent !== label) material.textContent = label;
        const unknown = (label === 'Unknown');
        if (material.dataset.unknown !== (unknown ? 'true' : 'false')) {
          material.dataset.unknown = unknown ? 'true' : 'false';
        }
      }

      // Spool-present indicator: 1 = present, 0 = empty, -1/None = unknown.
      const slotDot = gate.querySelector('.klippace-slot-dot');
      let present = 'unknown';
      if (slotDot) {
        const raw = Array.isArray(mmu.gate_status) ? mmu.gate_status[i] : null;
        present = (raw === 1) ? 'present' : (raw === 0 ? 'empty' : 'unknown');
        if (slotDot.dataset.present !== present) slotDot.dataset.present = present;
      }

      // Flag a slot that has filament but no material data — it needs manual
      // entry via the slot editor. Highlighted so it is not overlooked.
      const mat = (mmu.gate_material?.[i] || '').trim();
      needsData = (present === 'present') && (!mat || mat.toLowerCase() === 'unknown');
      if (gate.classList.contains('klippace-needs-data') !== needsData) {
        gate.classList.toggle('klippace-needs-data', needsData);
      }

      const shouldActive = (i === activeGate);
      if (gate.classList.contains('klippace-gate-active') !== shouldActive) {
        gate.classList.toggle('klippace-gate-active', shouldActive);
      }
    });
    updateStatusRibbon(card, mmu);
  }

  // The card's header element differs by UI: Fluidd renders a `.v-card__title`,
  // Mainsail a `.panel-toolbar` whose `.v-toolbar__content` holds a
  // `.v-toolbar__title`. Everything header-related goes through this helper.
  function cardHeaderEl(card) {
    return card.querySelector('.v-card__title') ||
           card.querySelector('.panel-toolbar .v-toolbar__content') ||
           card.querySelector('.v-toolbar__title') ||
           null;
  }

  function decorateHeader(card) {
    const title = cardHeaderEl(card);
    if (!title) return;

    // Style the "Mmu" title span via INLINE style. CSS rules targeting the MMU
    // title cannot be scoped reliably (the JS-added .bambu-ams-card class is
    // transiently patched away by Vue, and :has()-scoped rules were dropped by
    // the CSS parser). Inline styles on the persistent span are dependable.
    const titleSpan = title.querySelector('.font-weight-light, .subheading');
    if (titleSpan) {
      if (titleSpan.style.textTransform !== 'uppercase') {
        titleSpan.style.textTransform = 'uppercase';
        titleSpan.style.letterSpacing = '0.02em';
      }
    }

    // Move the ACE badge next to the title text (idempotent)
    const badge = title.querySelector('.bambu-ams-title-badge');
    const titleCol = title.querySelector('.text-no-wrap') || title.querySelector('.v-toolbar__title');
    if (badge && titleCol && badge.parentElement !== titleCol) {
      titleCol.appendChild(badge);
    }
    if (badge && badge.style.marginLeft !== '10px') {
      badge.style.marginLeft = '10px';
    }

    // Tools Mapper trigger, inside the card's own header, in BOTH UIs:
    //   Mainsail -> .panel-toolbar > .v-toolbar__items
    //   Fluidd   -> .v-card__title > .row > .col-auto (the button group)
    // Fluidd additionally has a page-app-bar trigger (klippace-topbar-btn) and
    // Mainsail's app bar is hidden by Moonraker's config/.theme/custom.css, so
    // the card trigger is the one that works everywhere.
    let toolsHost = title.querySelector('.v-toolbar__items');
    if (!toolsHost) {
      const cols = [...title.querySelectorAll('.col-auto, [class*="col-auto"]')];
      // Prefer the column holding Fluidd's own MMU "Tools" affordance; fall back
      // to the first column that has a button (never the title text column).
      toolsHost =
        cols.find((c) => c.querySelector('button') && /tools/i.test(c.textContent)) ||
        cols.find((c) => c.querySelector('button')) ||
        null;
    }
    if (toolsHost && !toolsHost.querySelector('.klippace-tools-btn')) {
      const toolsBtn = document.createElement('button');
      toolsBtn.type = 'button';
      toolsBtn.className = 'klippace-tools-btn';
      // Icon-only. A text label stole so much of Mainsail's toolbar that the
      // panel title was clipped, and an icon matches the neighbouring round
      // controls in Fluidd's header.
      toolsBtn.innerHTML = '<span aria-hidden="true">\u26a1</span>';
      toolsBtn.title = 'Open ACE Pro Tool Mapper';
      toolsBtn.setAttribute('aria-label', 'Open ACE Pro Tool Mapper');
      toolsBtn.addEventListener('click', (e) => {
        // Both UIs put other handlers on the header: Fluidd's card collapses
        // when the title is clicked, and Mainsail's toolbar hosts menus. Stop
        // the event in both phases so neither fires.
        e.preventDefault();
        e.stopPropagation();
        openToolMapper();
      });
      toolsHost.insertBefore(toolsBtn, toolsHost.firstChild);
    }

    // Hide the status/refresh round icon button; keep only the collapse chevron.
    // Mainsail-specific: its toolbar hosts the panel menu (kebab) and settings
    // (gear) buttons, which are real features and must stay usable, so this is
    // restricted to Fluidd's .v-card__title.
    if (card.querySelector('.v-card__title')) {
      title.querySelectorAll('button.v-btn--round, button.v-btn--icon').forEach((btn) => {
        const path = btn.querySelector('svg path');
        const d = path ? (path.getAttribute('d') || '') : '';
        // Collapse chevron (expand_more) contains "L12,10.83"; hide everything else
        if (!d.includes('L12,10.83')) {
          if (btn.style.display !== 'none') btn.style.display = 'none';
        }
      });
    }
  }

  // --- Bambu Lab AMS Style Injection & Decoration ---
  // ---------------------------------------------------------------------------
  // Action-button classification
  //
  // Fluidd renders the card's action buttons from a localized label list and
  // gives them no distinguishing class, so the only stable, locale-independent
  // handle is the leading glyph of each button's inline SVG path. Matching on
  // that lets CSS address individual actions (e.g. to hide the ones our shim
  // does not implement) without depending on row order or the UI language.
  // ---------------------------------------------------------------------------
  const MMU_ACTION_ICONS = {
    preload: 'M13,5V11H14.17L12,13.17L9.83,11H11V5H13M',
    eject: 'M12,5L5.33,15H18.67M5,17H19V19H5V17Z',
    'check-gate': 'M21,7L9,19L3.5,13.5L4.91,12.09L9,16.17L1',
    recover: 'M7.5,5.6L5,7L6.4,4.5L5,2L7.5,3.4L10,2L8.',
    unlock: 'M19 11V8H17V11H14V13H17V16H19V13H22V11M1',
    unload: 'M9,16V10H5L12,3L19,10H15V16H9M5,20V18H19',
    load: 'M5,20H19V18H5M19,9H15V3H9V9H5L12,16L19,9',
  };

  // Button captions. Fluidd prints its own localised label inside the button;
  // Mainsail renders the action buttons icon-only and puts the label in a
  // tooltip, which leaves our action dock unlabelled. These are used only to
  // fill a button that has no text of its own.
  const MMU_ACTION_LABELS = {
    preload: 'PRELOAD',
    eject: 'EJECT',
    'check-gate': 'CHECK GATE',
    recover: 'RECOVER',
    unlock: 'UNLOCK',
    unload: 'UNLOAD',
    load: 'LOAD',
  };

  // Actions our command shim does not implement, so the card should not offer
  // them: MMU_PRELOAD and MMU_UNLOCK only print a message, and MMU_EJECT runs
  // the identical UNLOAD path. CSS hides these rows.
  const MMU_ACTION_DEAD = ['preload', 'eject'];

  function classifyActionButton(button) {
    const path = button.querySelector('svg.v-icon__svg path');
    if (!path) return null;
    const d = path.getAttribute('d') || '';
    for (const [action, marker] of Object.entries(MMU_ACTION_ICONS)) {
      if (d.startsWith(marker)) return action;
    }
    return null;
  }

  // Locate the card's MMU action buttons without assuming Fluidd's markup.
  // Fluidd tags them `button.base-btn` / `button.wrap-text-btn`; Mainsail gives
  // them no distinguishing class and hides the label (icon + tooltip only), so
  // the shared, locale-independent handle is the icon path that
  // classifyActionButton() already matches on.
  //
  // Deliberately NOT restricted to a row class: Fluidd puts Check Gate/Recover
  // in `.row--dense` but Unload/Load in a plain `.row`, so keying on the row
  // silently dropped the two most important buttons. classifyActionButton()
  // returns null for anything that is not an MMU action (header menus etc.),
  // so scanning every button in the card is safe.
  function mmuActionButtons(card) {
    const scoped = card.querySelectorAll('mmu-controls button.v-btn, [ref="mmuControls"] button.v-btn');
    if (scoped.length) return [...scoped];
    return [...card.querySelectorAll('button.v-btn')];
  }

  // True when a column holds the MMU controls, in either UI.
  function columnHasMmuControls(col) {
    if (col.querySelector('mmu-controls, [ref="mmuControls"]')) return true;
    return mmuActionButtons(col).some((b) => classifyActionButton(b) !== null);
  }

  function decorateActionButtons(card) {
    mmuActionButtons(card).forEach((button) => {
      const action = classifyActionButton(button);
      if (!action) return;

      // Idempotent writes only — assigning an unchanged attribute on every pass
      // would emit mutations and re-trigger our own MutationObserver.
      if (button.dataset.klippaceAction !== action) {
        button.dataset.klippaceAction = action;
      }
      const disabled = (button.disabled || button.classList.contains('v-btn--disabled'))
        ? 'true' : 'false';
      if (button.dataset.klippaceDisabled !== disabled) {
        button.dataset.klippaceDisabled = disabled;
      }

      // Size group. Fluidd marks the large Load/Unload pair with its own
      // `wrap-text-btn` class; Mainsail has no equivalent, so tag the two groups
      // ourselves and let the stylesheet key off these instead of on a
      // UI-specific class. `toggle(cls, force)` is a no-op when the state is
      // already correct, so this stays mutation-free on repeat passes.
      const big = (action === 'load' || action === 'unload');
      button.classList.toggle('klippace-btn-lg', big);
      button.classList.toggle('klippace-btn-sm', !big);

      // Add a caption when the UI left the button icon-only (Mainsail). Fluidd
      // supplies its own localised text, so this is a no-op there.
      const content = button.querySelector('.v-btn__content');
      if (content && !content.textContent.trim() && !content.querySelector('.klippace-btn-label')) {
        const label = document.createElement('span');
        label.className = 'klippace-btn-label';
        label.textContent = MMU_ACTION_LABELS[action] || action.toUpperCase();
        content.appendChild(label);
      }
    });
  }

  function decorateBambuMmuCard(card) {
    if (!card || card.closest('#klippace-tool-mapper-overlay')) return;

    // Buttons need re-checking on every pass: their disabled state is driven by
    // live MMU state, so this must run before the fast path returns.
    decorateActionButtons(card);

    // Fast path: if the card is already fully decorated, skip ALL structural DOM
    // work and only refresh live data. This makes repeated calls cheap and, more
    // importantly, CONVERGENT — once decorated, no further mutations occur, so the
    // MutationObserver cannot re-trigger itself in an endless loop.
    const alreadyDecorated =
      card.classList.contains('bambu-ams-card') &&
      card.querySelector('.klippace-swatch') &&
      card.querySelector('.bambu-status-ribbon');
    if (alreadyDecorated) {
      getCachedMmu().then((mmu) => { if (mmu) applyGateData(card, mmu); });
      return;
    }

    // 1. Inject the style element ONCE. Assigning .textContent on every pass
    //    would replace its text node (a childList mutation) and re-trigger the
    //    MutationObserver, causing an endless re-decorate loop.
    // 1. Ensure the card stylesheet is loaded.
    //
    //    The CSS lives in klippace-tool-mapper.css only. It used to be
    //    duplicated here as an injected <style> of ~940 lines whose every
    //    selector also existed in the file (66 of 66). Because the injected
    //    block came later in the document it silently won, so the two copies
    //    could drift and each change had to be made in both places.
    ensureStyleSheet();

    // 2. Decorate card root
    card.classList.add('bambu-ams-card', 'mmu-card');

    // 3. Decorate AMS chamber units
    const units = card.querySelectorAll('.mmu-unit');
    units.forEach((u) => {
      u.classList.add('bambu-ams-unit');
      // Bay slots
      const gates = u.querySelectorAll(GATE_SELECTOR);
      gates.forEach((g) => {
        g.classList.add('bambu-ams-bay');
        if (g.querySelector('.highlight-spool') || g.classList.contains('highlight-spool')) {
          g.classList.add('bambu-bay-active');
        } else {
          g.classList.remove('bambu-bay-active');
        }
      });
      // Footer = the unit's label bar (e.g. "#1 ACE Pro 0").
      // Prefer an explicit footer class, and never accept an element that
      // contains the gates. In Mainsail the gate wrapper is *also*
      // `.position-relative` and appears earlier in the DOM than the real
      // `mmu-unit-footer`, so the old bare `.position-relative` query grabbed
      // the gate wrapper — which made the footer badge styles apply to every
      // gate tile. Fluidd has a single `.position-relative` (the footer), so
      // this picks the same element as before there.
      const footer =
        u.querySelector('mmu-unit-footer, .mmu-unit-footer') ||
        [...u.querySelectorAll('[class*="footer"]')].find((el) => !el.querySelector(GATE_SELECTOR)) ||
        [...u.querySelectorAll('.position-relative')].find((el) => !el.querySelector(GATE_SELECTOR)) ||
        null;
      if (footer) {
        footer.classList.add('bambu-ams-footer');
        // Tag the label element so CSS can style just it. Mainsail's footer
        // also holds a logo icon, a tooltip wrapper and a sensor div; styling
        // every descendant turned those into stray pill boxes.
        const label = footer.querySelector('.klippace-unit-label') ||
          [...footer.querySelectorAll('div, span')].find(
            (el) => el.textContent.trim() && ![...el.children].some((c) => c.textContent.trim())
          );
        if (label) label.classList.add('klippace-unit-label');
      }
      // Repair a footer class left on a gate container by an earlier version.
      u.querySelectorAll('.bambu-ams-footer').forEach((el) => {
        if (el.querySelector(GATE_SELECTOR)) el.classList.remove('bambu-ams-footer');
      });
    });

    // 3b. Build color-swatch gate tiles and apply live MMU data
    buildGateTiles(card);
    getCachedMmu().then((mmu) => applyGateData(card, mmu));

    // 4. Decorate Filament Status & Toolhead Flow.
    // The native filament-status SVG only exists once Fluidd has MMU data, so
    // fall back to an already-decorated panel if it is not present yet — this
    // keeps the ribbon from appearing "late" on a cold load.
    const filStatusSvg = card.querySelector('svg.svg-colors, [ref="filStatusSvg"]');
    const existingPanel = card.querySelector('.bambu-ams-toolhead-panel');
    if (filStatusSvg || existingPanel) {
      const filCol = filStatusSvg ? filStatusSvg.closest('.v-col, .col') : existingPanel;
      if (filCol) {
        filCol.classList.add('bambu-ams-toolhead-panel');
        filCol.style.width = '100%';
        filCol.style.maxWidth = '100%';
        filCol.style.flex = '1 1 100%';

        // Hide only DIRECT sibling columns (e.g. TTG map) — never anything
        // inside or containing mmu-controls (its buttons live in nested .col's)
        const parentRow = filCol.parentElement;
        if (parentRow) {
          Array.from(parentRow.children).forEach((col) => {
            if (col === filCol) return;
            if (!col.matches('.v-col, .col, [class*="col-"]')) return;
            // Never hide the column that holds the MMU controls. This guard
            // used to test for Fluidd's <mmu-controls> element, which Mainsail
            // does not have — so on Mainsail the entire action-button column
            // was hidden and the card lost every control (Preload/Eject/
            // Unlock/Load/Unload) along with the gate summary and TTG map.
            if (columnHasMmuControls(col)) {
              if (col.style.display === 'none') col.style.display = '';
              return;
            }
            col.style.display = 'none';
          });
          // Repair columns hidden by an earlier version of this code.
          card.querySelectorAll('.v-col, .col, [class*="col-"]').forEach((c) => {
            if (c.style.display === 'none' && columnHasMmuControls(c)) c.style.display = '';
          });
        }

        // Inject or update the status ribbon. To avoid a late pop-in we seed it
        // IMMEDIATELY from the native filament-status SVG that is already in the
        // DOM (same underlying MMU data), then refine it from live MMU state.
        let ribbon = filCol.querySelector('.bambu-status-ribbon');
        if (!ribbon) {
          // Instant seed from the native SVG text (when available)
          let seedText = '';
          let seedTemp = '';
          if (filStatusSvg) {
            filStatusSvg.querySelectorAll('text').forEach((t) => {
              const content = (t.textContent || '').trim();
              if (content.includes('°C')) seedTemp = content;
              if (/unloaded|loaded|printing|loading|unloading/i.test(content)) seedText = content;
            });
          }
          let seedState = 'unloaded';
          if (/printing|loaded/i.test(seedText)) seedState = 'loaded';
          else if (/loading|unloading/i.test(seedText)) seedState = 'busy';
          else if (/splitter|toolhead|bowden/i.test(seedText)) seedState = 'partial';
          const seedLabel = seedText
            ? seedText.replace(/^filament:\s*/i, '').trim()
            : '';

          ribbon = document.createElement('div');
          ribbon.className = 'bambu-status-ribbon';
          ribbon.innerHTML = `
            <div class="bambu-status-left">
              <span class="bambu-status-dot" data-state="${seedState}"></span>
              <span class="bambu-status-title" data-state="${seedState}">${seedLabel}</span>
            </div>
            <div class="bambu-status-right">
              <span class="bambu-temp-badge">${seedTemp}</span>
              <button type="button" class="klippace-dryer-btn" title="ACE Pro chamber dryer">Dryer</button>
            </div>
          `;
          filCol.insertBefore(ribbon, filCol.firstChild);

          // Own the dryer control before the ribbon's own handler sees it.
          const dryerBtn = ribbon.querySelector('.klippace-dryer-btn');
          if (dryerBtn) {
            dryerBtn.addEventListener('click', (e) => {
              e.stopPropagation();
              openDryerModal();
            });
          }
        }

        ribbon.style.cursor = 'pointer';
        ribbon.title = 'Click to open KLIPPACE Tool Mapper';
        ribbon.onclick = (e) => {
          e.stopPropagation();
          openToolMapper();
        };

        // Fill the ribbon from live MMU state (single source of truth). If we
        // already have cached data, apply it synchronously for a no-flash paint.
        if (cachedMmu) {
          applyGateData(card, cachedMmu);
        } else {
          getCachedMmu().then((mmu) => applyGateData(card, mmu));
        }
      }
    }

    // 5. Decorate Spool Metadata Summary
    const overline = card.querySelector('.text-overline');
    if (overline && overline.parentElement) {
      overline.parentElement.classList.add('bambu-ams-summary-card');
    }
    const summaryCards = card.querySelectorAll('.v-card');
    summaryCards.forEach((c) => {
      if (c !== card && c.querySelector('.text-overline, .text-h6')) {
        c.classList.add('bambu-ams-summary-card');
      }
    });
    const gateSummary = card.querySelector('mmu-gate-summary');
    if (gateSummary) {
      gateSummary.classList.add('bambu-ams-summary-card');
      gateSummary.style.display = 'none';
    }

    // 6. Decorate Title with ACE Badge + clean header
    const titleEl = cardHeaderEl(card);
    if (titleEl && !titleEl.querySelector('.bambu-ams-title-badge')) {
      const badge = document.createElement('span');
      badge.className = 'bambu-ams-title-badge';
      badge.textContent = 'ACE';
      (titleEl.querySelector('.v-toolbar__title') || titleEl).appendChild(badge);
    }
    decorateHeader(card);

    // 7. Decorate Control Buttons (scope to mmu-controls only, not the header)
    const btns = card.querySelectorAll('mmu-controls .v-btn');
    btns.forEach((btn) => {
      const txt = (btn.textContent || '').trim().toLowerCase();
      if (txt.includes('preload') || txt.includes('eject') || txt.includes('check gate') || txt.includes('recover') || txt.includes('unlock') || txt.includes('lock')) {
        btn.classList.add('bambu-btn-secondary');
        btn.classList.remove('bambu-btn-load', 'bambu-btn-unload');
      } else if (txt.includes('unload')) {
        btn.classList.add('bambu-btn-unload');
        btn.classList.remove('bambu-btn-load', 'bambu-btn-secondary');
      } else if (txt.includes('load')) {
        btn.classList.add('bambu-btn-load');
        btn.classList.remove('bambu-btn-unload', 'bambu-btn-secondary');
      } else if (txt.length > 0) {
        btn.classList.add('bambu-btn-secondary');
        btn.classList.remove('bambu-btn-load', 'bambu-btn-unload');
      }
    });

    // 8. Hide redundant stock TTG schematics and gate summary from card deck
    const ttgSvg = card.querySelector('svg.cursor-pointer, svg[ref="ttgMap"]');
    if (ttgSvg) {
      ttgSvg.style.display = 'none';
    }
    const ttgMapEl = card.querySelector('mmu-ttg-map');
    if (ttgMapEl) {
      ttgMapEl.style.display = 'none';
    }

    // 8b. Mainsail equivalents. Its `.disabled-panel` list item repeats the very
    // gate data our tiles show (and reads as raw "@-1 | Unknown ..." text), and
    // the trailing caption labels the unused TTG schematic. Both left a large
    // empty gap between the ribbon and the action buttons.
    if (card.querySelector('.panel-toolbar')) {
      const disabledPanel = card.querySelector('.v-list-item.disabled-panel');
      if (disabledPanel) disabledPanel.style.display = 'none';
      const ttgCaption = card.querySelector('.v-card__text .text--disabled.text-center');
      if (ttgCaption) ttgCaption.style.display = 'none';
      const ttgWrap = card.querySelector('.v-card__text .d-flex.flex-column.align-center');
      if (ttgWrap && ttgWrap.querySelector('svg')) ttgWrap.style.display = 'none';
    }

    // 9. Ensure Controls Container and its Column are 100% Width & Visible
    const mmuControls = card.querySelector('mmu-controls');
    if (mmuControls) {
      mmuControls.style.display = 'block';
      mmuControls.style.width = '100%';
      const ctrlCol = mmuControls.closest('.v-col, .col');
      if (ctrlCol) {
        ctrlCol.style.display = 'flex';
        ctrlCol.style.flexDirection = 'column';
        ctrlCol.style.width = '100%';
        ctrlCol.style.maxWidth = '100%';
        ctrlCol.style.flex = '1 1 100%';
        ctrlCol.style.padding = '0';
        ctrlCol.style.margin = '0';
      }
    }
  }

  // Expose global opener for console or external macros immediately
  window.openKlippaceToolMapper = openToolMapper;

  // Initialize UI injection & Bambu AMS decoration immediately (do NOT wait for Vuex)
  function initDecorator() {
    console.log('[KLIPPACE] Initializing Bambu AMS decorator engine...');

    // Pre-warm the MMU state fetch so the status ribbon can paint with real data
    // on the very first decoration (avoids a visible delay/fade-in on load).
    getCachedMmu();

    let scheduled = false;
    let running = false;
    let observer = null;

    // Run the decorator under a re-entrancy guard rather than disconnecting the
    // observer. Disconnecting created a blind window: DOM that Vue rebuilt while
    // we were mid-run was never seen, so it waited for the 300ms fallback tick.
    // That is long enough for the card's expand animation to measure the
    // still-undecorated layout — with the hidden action rows and full-size
    // buttons still laid out — and animate to that taller height before the
    // decoration shortened it, producing a visible overshoot and snap.
    //
    // Re-entrancy is safe: every write below is idempotent (element existence
    // guards, dataset comparisons, and the fast path in decorateBambuMmuCard),
    // so the decorate -> mutate -> observe cycle settles instead of looping.
    const run = () => {
      scheduled = false;
      if (running) return;
      running = true;
      try {
        injectButtons();
      } finally {
        running = false;
      }
    };

    run();

    // Coalesce a burst of mutations into a single microtask run (before paint),
    // which also eliminates the flash of the undecorated "old card".
    const schedule = () => {
      if (scheduled) return;
      scheduled = true;
      Promise.resolve().then(run);
    };

    observer = new MutationObserver(schedule);
    observer.observe(document.body, { childList: true, subtree: true });

    // Frequent fallback so any decoration missed by the observer (e.g. content
    // rendered while the observer was momentarily disconnected) is corrected
    // quickly instead of after a visible delay.
    setInterval(run, 300);
  }

  // Optional: Connect to Vuex store for auto-opening modal on mmu.dialog
  function tryConnectVuexStore(attempts = 0) {
    if (attempts > 50) return; // Stop after ~25s to not spin forever
    const appEl = document.getElementById('app');
    if (!appEl || !appEl.__vue__ || !appEl.__vue__.$store) {
      setTimeout(() => tryConnectVuexStore(attempts + 1), 500);
      return;
    }
    const app = appEl.__vue__;
    console.log('[KLIPPACE] Connected to Fluidd root app and Vuex store!');
    try {
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
    } catch (err) {
      console.warn('[KLIPPACE] Error attaching to Vuex store watch:', err);
    }
  }

  function start() {
    initDecorator();
    tryConnectVuexStore();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
