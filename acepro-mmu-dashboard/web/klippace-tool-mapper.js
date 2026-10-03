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
      if (c.querySelector('.mmu-unit, .gate, .mmu-controls, .mmu-gate-summary, svg.clip-spool, [ref="mmuControls"]')) {
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

  // --- Bambu Lab AMS Style Injection & Decoration ---
  function decorateBambuMmuCard(card) {
    if (!card || card.closest('#klippace-tool-mapper-overlay')) return;

    // 1. Ensure style element is injected at the bottom of head
    let style = document.getElementById('klippace-bambu-ams-style');
    if (!style) {
      style = document.createElement('style');
      style.id = 'klippace-bambu-ams-style';
      document.head.appendChild(style);
    }

    style.textContent = `
      /* =========================================================
         KLIPPACE - Ultra-Compact Streamlined Deck for MMU / AMS Card
         ========================================================= */

      /* Root Card Frame */
      .v-application .bambu-ams-card,
      .v-card.bambu-ams-card,
      [layout-path="dashboard.mmu-card"],
      .mmu-card {
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 16px !important;
        background: linear-gradient(180deg, #1C1E26 0%, #121318 100%) !important;
        box-shadow: 0 12px 32px rgba(0, 0, 0, 0.55), inset 0 1px 1px rgba(255, 255, 255, 0.1) !important;
        position: relative !important;
        overflow: hidden !important;
      }

      /* Card Header */
      .v-application .bambu-ams-card .v-card__title,
      .bambu-ams-card .v-card__title,
      .v-application .bambu-ams-card .card-heading,
      [layout-path="dashboard.mmu-card"] .v-card__title,
      .mmu-card .v-card__title {
        font-weight: 700 !important;
        letter-spacing: -0.01em !important;
        color: #FFFFFF !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
        padding: 10px 16px !important;
        margin-bottom: 0 !important;
        display: flex !important;
        align-items: center !important;
        gap: 8px !important;
        background: rgba(255, 255, 255, 0.02) !important;
      }

      .v-application .bambu-ams-card .bambu-ams-title-badge,
      .bambu-ams-card .bambu-ams-title-badge,
      [layout-path="dashboard.mmu-card"] .bambu-ams-title-badge,
      .mmu-card .bambu-ams-title-badge {
        background: rgba(0, 194, 80, 0.16) !important;
        color: #00C250 !important;
        border: 1px solid rgba(0, 194, 80, 0.35) !important;
        font-size: 0.65rem !important;
        font-weight: 800 !important;
        padding: 1px 6px !important;
        border-radius: 5px !important;
        letter-spacing: 0.08em !important;
        text-transform: uppercase !important;
        display: inline-block !important;
        line-height: 1.3 !important;
      }

      /* Hide stock dividing lines */
      .v-application .bambu-ams-card hr.v-divider,
      .bambu-ams-card hr.v-divider,
      [layout-path="dashboard.mmu-card"] hr.v-divider,
      .mmu-card hr.v-divider {
        display: none !important;
      }

      /* Card Body Container */
      .v-application .bambu-ams-card .v-card__text,
      .bambu-ams-card .v-card__text,
      [layout-path="dashboard.mmu-card"] .v-card__text,
      .mmu-card .v-card__text {
        padding: 10px 14px !important;
      }

      .v-application .bambu-ams-card .v-card__text > .container,
      .bambu-ams-card .v-card__text > .container,
      [layout-path="dashboard.mmu-card"] .v-card__text > .container,
      .mmu-card .v-card__text > .container {
        padding: 0 !important;
        display: flex !important;
        flex-direction: column !important;
        gap: 8px !important;
        width: 100% !important;
      }

      /* =========================================================
         TIER 1: Wide AMS Chamber Hero (Top Section)
         ========================================================= */
      .v-application .bambu-ams-card .mmu-machine,
      .bambu-ams-card .mmu-machine,
      [layout-path="dashboard.mmu-card"] .mmu-machine,
      .mmu-card .mmu-machine {
        width: 100% !important;
        display: block !important;
        overflow: visible !important;
      }

      .v-application .bambu-ams-card .mmu-machine > .row,
      .bambu-ams-card .mmu-machine > .row,
      [layout-path="dashboard.mmu-card"] .mmu-machine > .row,
      .mmu-card .mmu-machine > .row {
        margin: 0 !important;
        display: flex !important;
        flex-wrap: nowrap !important;
        align-items: stretch !important;
        justify-content: space-between !important;
        width: 100% !important;
        gap: 8px !important;
      }

      .v-application .bambu-ams-card .mmu-machine > .row > .col:first-child,
      .bambu-ams-card .mmu-machine > .row > .col:first-child,
      [layout-path="dashboard.mmu-card"] .mmu-machine > .row > .col:first-child,
      .mmu-card .mmu-machine > .row > .col:first-child {
        flex: 1 1 auto !important;
        max-width: calc(100% - 76px) !important;
        padding: 0 !important;
      }

      .v-application .bambu-ams-card .mmu-machine > .row > .col:last-child,
      .bambu-ams-card .mmu-machine > .row > .col:last-child,
      [layout-path="dashboard.mmu-card"] .mmu-machine > .row > .col:last-child,
      .mmu-card .mmu-machine > .row > .col:last-child {
        flex: 0 0 68px !important;
        width: 68px !important;
        max-width: 68px !important;
        padding: 0 !important;
      }

      /* Completely eliminate scrollbars anywhere in MMU unit */
      .v-application .bambu-ams-card .mmu-unit,
      .v-application .bambu-ams-card .mmu-unit *,
      .v-application .bambu-ams-card .mmu-machine,
      .v-application .bambu-ams-card .mmu-machine *,
      .v-application .bambu-ams-card .bambu-ams-unit,
      .v-application .bambu-ams-card .bambu-ams-unit *,
      .v-application .bambu-ams-card .v-sheet,
      .v-application .bambu-ams-card .v-sheet * {
        scrollbar-width: none !important;
        -ms-overflow-style: none !important;
      }

      .v-application .bambu-ams-card *::-webkit-scrollbar,
      .bambu-ams-card *::-webkit-scrollbar,
      [layout-path="dashboard.mmu-card"] *::-webkit-scrollbar,
      .mmu-card *::-webkit-scrollbar {
        display: none !important;
        width: 0 !important;
        height: 0 !important;
      }

      /* AMS Enclosure: Authentic Smoked Acrylic Dome */
      .v-application .bambu-ams-card .bambu-ams-unit:not(.mmu-unit-clear),
      .bambu-ams-card .mmu-unit:not(.mmu-unit-clear),
      [layout-path="dashboard.mmu-card"] .mmu-unit:not(.mmu-unit-clear),
      .mmu-card .mmu-unit:not(.mmu-unit-clear) {
        width: 100% !important;
        position: relative !important;
        background: linear-gradient(180deg, #262B37 0%, #14161D 100%) !important;
        border: 1.5px solid rgba(255, 255, 255, 0.18) !important;
        border-radius: 14px !important;
        box-shadow: 0 10px 24px -4px rgba(0, 0, 0, 0.7), inset 0 2px 3px rgba(255, 255, 255, 0.25) !important;
        backdrop-filter: blur(14px) !important;
        -webkit-backdrop-filter: blur(14px) !important;
        padding: 8px 6px 4px 6px !important;
        margin-bottom: 0 !important;
        overflow: hidden !important;
      }

      /* Smoked Glass Dome Gloss Reflection */
      .v-application .bambu-ams-card .bambu-ams-unit:not(.mmu-unit-clear)::before,
      .bambu-ams-card .mmu-unit:not(.mmu-unit-clear)::before,
      [layout-path="dashboard.mmu-card"] .mmu-unit:not(.mmu-unit-clear)::before,
      .mmu-card .mmu-unit:not(.mmu-unit-clear)::before {
        content: "" !important;
        position: absolute !important;
        top: 0 !important;
        left: 0 !important;
        right: 0 !important;
        height: 44% !important;
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.16) 0%, rgba(255, 255, 255, 0.02) 60%, transparent 100%) !important;
        border-radius: 14px 14px 0 0 !important;
        pointer-events: none !important;
        z-index: 1 !important;
      }

      /* Spool Cassette Bay Row */
      .v-application .bambu-ams-card .bambu-ams-unit .v-row,
      .bambu-ams-card .mmu-unit .v-row,
      [layout-path="dashboard.mmu-card"] .mmu-unit .v-row,
      .mmu-card .mmu-unit .v-row {
        margin: 0 !important;
        display: flex !important;
        flex-wrap: nowrap !important;
        justify-content: space-between !important;
        width: 100% !important;
        overflow: hidden !important;
      }

      /* Recessed Cassette Bays */
      .v-application .bambu-ams-card .bambu-ams-bay,
      .bambu-ams-card .gate,
      [layout-path="dashboard.mmu-card"] .gate,
      .mmu-card .gate {
        flex: 1 1 0 !important;
        min-width: 0 !important;
        max-width: 25% !important;
        background: #0E1015 !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 10px !important;
        padding: 4px 2px 2px 2px !important;
        margin: 0 2px !important;
        box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.7) !important;
        transition: transform 0.18s cubic-bezier(0.16, 1, 0.3, 1),
                    background 0.18s cubic-bezier(0.16, 1, 0.3, 1),
                    border-color 0.18s cubic-bezier(0.16, 1, 0.3, 1) !important;
        position: relative !important;
        z-index: 2 !important;
      }

      .v-application .bambu-ams-card .bambu-ams-bay:hover,
      .bambu-ams-card .gate:hover,
      [layout-path="dashboard.mmu-card"] .gate:hover,
      .mmu-card .gate:hover {
        background: #181B24 !important;
        border-color: rgba(255, 255, 255, 0.25) !important;
        transform: translateY(-2px) !important;
        box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.4), 0 4px 12px rgba(0, 0, 0, 0.5) !important;
      }

      /* Active / Loaded Bay Neon Green Glow */
      .v-application .bambu-ams-card .bambu-ams-bay.bambu-bay-active,
      .v-application .bambu-ams-card .bambu-ams-bay:has(.highlight-spool),
      .bambu-ams-card .gate.highlight-spool,
      [layout-path="dashboard.mmu-card"] .gate.highlight-spool,
      .mmu-card .gate.highlight-spool {
        border-color: #00C250 !important;
        background: linear-gradient(180deg, rgba(0, 194, 80, 0.16) 0%, #0E1015 100%) !important;
        box-shadow: inset 0 0 12px rgba(0, 194, 80, 0.35), 0 0 14px rgba(0, 194, 80, 0.4) !important;
      }

      /* Spool Graphic Depth */
      .v-application .bambu-ams-card .clip-spool,
      .bambu-ams-card .clip-spool,
      [layout-path="dashboard.mmu-card"] .clip-spool,
      .mmu-card .clip-spool {
        width: 100% !important;
        height: auto !important;
        max-height: 62px !important;
        filter: drop-shadow(0 4px 8px rgba(0, 0, 0, 0.7)) !important;
        transition: transform 0.18s cubic-bezier(0.16, 1, 0.3, 1) !important;
      }

      .v-application .bambu-ams-card .bambu-ams-bay:hover .clip-spool,
      .bambu-ams-card .gate:hover .clip-spool,
      [layout-path="dashboard.mmu-card"] .gate:hover .clip-spool,
      .mmu-card .gate:hover .clip-spool {
        transform: scale(1.03) !important;
      }

      /* Slot Badges & Gate Numbers */
      .v-application .bambu-ams-card .gate-status-row,
      .bambu-ams-card .gate-status-row,
      [layout-path="dashboard.mmu-card"] .gate-status-row,
      .mmu-card .gate-status-row {
        background: transparent !important;
        margin-top: 2px !important;
        display: flex !important;
        justify-content: center !important;
      }

      .v-application .bambu-ams-card svg[ref="mmuGateStatusSvg"],
      .v-application .bambu-ams-card .mmu-gate-status svg,
      [layout-path="dashboard.mmu-card"] svg[ref="mmuGateStatusSvg"],
      .mmu-card svg[ref="mmuGateStatusSvg"] {
        max-height: 20px !important;
        filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.5)) !important;
      }

      /* AMS Unit Tag / Footer Badge */
      .v-application .bambu-ams-card .bambu-ams-footer,
      .bambu-ams-card .bambu-ams-footer,
      [layout-path="dashboard.mmu-card"] .bambu-ams-footer,
      .mmu-card .mmu-unit-footer {
        text-align: center !important;
        margin-top: 3px !important;
        padding-top: 0 !important;
      }

      .v-application .bambu-ams-card .bambu-ams-footer span,
      .v-application .bambu-ams-card .bambu-ams-footer div,
      .bambu-ams-card .bambu-ams-footer span,
      [layout-path="dashboard.mmu-card"] .bambu-ams-footer span,
      .mmu-card .mmu-unit-footer span {
        display: inline-flex !important;
        align-items: center !important;
        background: rgba(255, 255, 255, 0.07) !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 12px !important;
        padding: 1px 8px !important;
        font-size: 0.65rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.08em !important;
        text-transform: uppercase !important;
        color: #D4D4D8 !important;
      }

      /* Standalone Bypass Spool Bracket */
      .v-application .bambu-ams-card .mmu-unit-clear,
      .bambu-ams-card .mmu-unit-clear,
      [layout-path="dashboard.mmu-card"] .mmu-unit-clear,
      .mmu-card .mmu-unit-clear {
        width: 68px !important;
        height: 100% !important;
        background: rgba(255, 255, 255, 0.02) !important;
        border: 1.5px dashed rgba(255, 255, 255, 0.16) !important;
        border-radius: 14px !important;
        box-shadow: none !important;
        padding: 6px 2px !important;
        margin-bottom: 0 !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
        justify-content: center !important;
        overflow: hidden !important;
      }

      .v-application .bambu-ams-card .mmu-unit-clear .clip-spool,
      .bambu-ams-card .mmu-unit-clear .clip-spool {
        max-height: 62px !important;
      }

      /* =========================================================
         TIER 2: Horizontal Status Ribbon (Tight 1-Line Deck)
         ========================================================= */

      /* Middle Row container: Full width vertical stack for ribbon & controls */
      .v-application .bambu-ams-card .v-card__text > .container > .v-row:nth-of-type(2),
      .v-application .bambu-ams-card .v-card__text > .container > .row:nth-of-type(2),
      .v-application .bambu-ams-card .v-card__text > .container > .v-row:nth-child(2),
      .v-application .bambu-ams-card .v-card__text > .container > .row:nth-child(2),
      .bambu-ams-card .v-card__text > .container > .v-row:nth-of-type(2),
      .bambu-ams-card .v-card__text > .container > .row:nth-of-type(2),
      .bambu-ams-card .v-card__text > .container > .v-row:nth-child(2),
      .bambu-ams-card .v-card__text > .container > .row:nth-child(2),
      [layout-path="dashboard.mmu-card"] .v-card__text > .container > .v-row:nth-of-type(2),
      [layout-path="dashboard.mmu-card"] .v-card__text > .container > .row:nth-of-type(2),
      .mmu-card .v-card__text > .container > .v-row:nth-of-type(2),
      .mmu-card .v-card__text > .container > .row:nth-of-type(2) {
        display: flex !important;
        flex-direction: column !important;
        gap: 6px !important;
        margin: 0 !important;
        width: 100% !important;
      }

      /* Col 1: Transforms into a sleek full-width 34px horizontal status ribbon */
      .v-application .bambu-ams-card .bambu-ams-toolhead-panel,
      .bambu-ams-card .bambu-ams-toolhead-panel,
      [layout-path="dashboard.mmu-card"] .bambu-ams-toolhead-panel,
      .mmu-card .bambu-ams-toolhead-panel {
        flex: 1 1 100% !important;
        width: 100% !important;
        max-width: 100% !important;
        height: 34px !important;
        min-height: 34px !important;
        max-height: 34px !important;
        background: rgba(255, 255, 255, 0.035) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 9px !important;
        padding: 0 12px !important;
        box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.3) !important;
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        justify-content: space-between !important;
        gap: 12px !important;
        margin: 0 !important;
        overflow: hidden !important;
        cursor: pointer !important;
        transition: background 0.18s ease, border-color 0.18s ease !important;
      }

      .v-application .bambu-ams-card .bambu-ams-toolhead-panel:hover,
      .bambu-ams-card .bambu-ams-toolhead-panel:hover {
        background: rgba(255, 255, 255, 0.06) !important;
        border-color: rgba(255, 255, 255, 0.16) !important;
      }

      /* Col 2: Contains mmu-controls (full width stack below ribbon) */
      .v-application .bambu-ams-card .v-card__text > .container > .v-row:nth-of-type(2) > .v-col:nth-child(2),
      .v-application .bambu-ams-card .v-card__text > .container > .v-row:nth-of-type(2) > [class*="v-col"]:has(mmu-controls),
      .v-application .bambu-ams-card .v-card__text > .container > .row:nth-of-type(2) > .col:nth-child(2),
      .v-application .bambu-ams-card .v-card__text > .container > .row:nth-of-type(2) > [class*="col"]:has(mmu-controls),
      .bambu-ams-card .v-card__text > .container > .v-row:nth-of-type(2) > .v-col:nth-child(2),
      .bambu-ams-card .v-card__text > .container > .v-row:nth-of-type(2) > [class*="v-col"]:has(mmu-controls),
      [layout-path="dashboard.mmu-card"] .v-card__text > .container > [class*="v-col"]:has(mmu-controls),
      .mmu-card .v-card__text > .container > [class*="v-col"]:has(mmu-controls) {
        display: flex !important;
        flex-direction: column !important;
        flex: 1 1 100% !important;
        width: 100% !important;
        max-width: 100% !important;
        padding: 0 !important;
        margin: 0 !important;
        gap: 6px !important;
      }

      /* Hide the clunky stock SVG wire diagram, TTG schematic, and gate summary in card */
      .v-application .bambu-ams-card .bambu-ams-toolhead-panel svg[ref="filStatusSvg"],
      .bambu-ams-card .bambu-ams-toolhead-panel svg[ref="filStatusSvg"],
      [layout-path="dashboard.mmu-card"] svg[ref="filStatusSvg"],
      .mmu-card svg[ref="filStatusSvg"],
      .v-application .bambu-ams-card mmu-ttg-map,
      .bambu-ams-card mmu-ttg-map,
      [layout-path="dashboard.mmu-card"] mmu-ttg-map,
      .mmu-card mmu-ttg-map,
      .v-application .bambu-ams-card .bambu-ams-ttg-panel,
      .bambu-ams-card .bambu-ams-ttg-panel,
      .v-application .bambu-ams-card mmu-gate-summary,
      .bambu-ams-card mmu-gate-summary,
      .v-application .bambu-ams-card .bambu-ams-summary-card,
      .bambu-ams-card .bambu-ams-summary-card {
        display: none !important;
      }

      /* Status Ribbon */
      .v-application .bambu-ams-card .bambu-status-ribbon,
      .bambu-ams-card .bambu-status-ribbon,
      [layout-path="dashboard.mmu-card"] .bambu-status-ribbon,
      .mmu-card .bambu-status-ribbon {
        display: flex !important;
        align-items: center !important;
        justify-content: space-between !important;
        width: 100% !important;
      }

      .v-application .bambu-ams-card .bambu-status-left,
      .bambu-ams-card .bambu-status-left {
        display: flex !important;
        align-items: center !important;
        gap: 8px !important;
      }

      .v-application .bambu-ams-card .bambu-status-dot,
      .bambu-ams-card .bambu-status-dot {
        width: 8px !important;
        height: 8px !important;
        border-radius: 50% !important;
        background: #00C250 !important;
        box-shadow: 0 0 10px #00C250 !important;
        display: inline-block !important;
      }

      .v-application .bambu-ams-card .bambu-status-title,
      .bambu-ams-card .bambu-status-title {
        font-size: 0.8rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.04em !important;
        text-transform: uppercase !important;
        color: #FFFFFF !important;
        white-space: nowrap !important;
      }

      .v-application .bambu-ams-card .bambu-status-right,
      .bambu-ams-card .bambu-status-right {
        display: flex !important;
        align-items: center !important;
      }

      .v-application .bambu-ams-card .bambu-temp-badge,
      .bambu-ams-card .bambu-temp-badge {
        font-size: 0.74rem !important;
        font-weight: 700 !important;
        color: #A1A1AA !important;
        background: rgba(255, 255, 255, 0.06) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 6px !important;
        padding: 1px 8px !important;
        letter-spacing: 0.03em !important;
      }

      /* =========================================================
         TIER 3: Action Dock (Single-Row Tools + Load/Unload Hero)
         ========================================================= */

      /* Controls Container */
      .v-application .bambu-ams-card mmu-controls,
      .bambu-ams-card mmu-controls,
      [layout-path="dashboard.mmu-card"] mmu-controls,
      .mmu-card mmu-controls {
        width: 100% !important;
        margin-top: 0 !important;
      }

      .v-application .bambu-ams-card mmu-controls > .container,
      .v-application .bambu-ams-card mmu-controls .mmu-controls-container,
      .bambu-ams-card mmu-controls > .container,
      .bambu-ams-card mmu-controls .mmu-controls-container,
      [layout-path="dashboard.mmu-card"] mmu-controls > .container,
      [layout-path="dashboard.mmu-card"] mmu-controls .mmu-controls-container,
      .mmu-card mmu-controls > .container,
      .mmu-card mmu-controls .mmu-controls-container {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: wrap !important;
        gap: 4px !important;
        padding: 0 !important;
        margin: 0 !important;
        width: 100% !important;
      }

      /* Secondary Tools Row: Unwrap rows 0, 1, 2 into a single unified flex row */
      .v-application .bambu-ams-card mmu-controls .v-row:not(:last-child),
      .v-application .bambu-ams-card mmu-controls .row:not(:last-child),
      .bambu-ams-card mmu-controls .v-row:not(:last-child),
      .bambu-ams-card mmu-controls .row:not(:last-child),
      [layout-path="dashboard.mmu-card"] mmu-controls .v-row:not(:last-child),
      [layout-path="dashboard.mmu-card"] mmu-controls .row:not(:last-child),
      .mmu-card mmu-controls .v-row:not(:last-child),
      .mmu-card mmu-controls .row:not(:last-child) {
        display: contents !important;
      }

      /* All 5 Secondary Utility Buttons Cols sit in ONE single horizontal row (order: 1) */
      .v-application .bambu-ams-card mmu-controls .v-row:not(:last-child) > .v-col,
      .v-application .bambu-ams-card mmu-controls .v-row:not(:last-child) > [class*="v-col"],
      .v-application .bambu-ams-card mmu-controls .row:not(:last-child) > .col,
      .v-application .bambu-ams-card mmu-controls .row:not(:last-child) > [class*="col"],
      .bambu-ams-card mmu-controls .v-row:not(:last-child) > .v-col,
      .bambu-ams-card mmu-controls .v-row:not(:last-child) > [class*="v-col"],
      .bambu-ams-card mmu-controls .row:not(:last-child) > .col,
      .bambu-ams-card mmu-controls .row:not(:last-child) > [class*="col"],
      [layout-path="dashboard.mmu-card"] mmu-controls .v-row:not(:last-child) > [class*="v-col"],
      .mmu-card mmu-controls .v-row:not(:last-child) > [class*="v-col"] {
        display: flex !important;
        flex: 1 1 0 !important;
        min-width: 0 !important;
        max-width: none !important;
        width: auto !important;
        padding: 0 !important;
        margin: 0 !important;
        order: 1 !important;
      }

      /* Compact Mini-Pill Style for Secondary Buttons */
      .v-application .bambu-ams-card .bambu-btn-secondary,
      .v-application .bambu-ams-card mmu-controls .v-row:not(:last-child) .v-btn,
      .theme--dark.v-btn.bambu-btn-secondary,
      .bambu-ams-card .bambu-btn-secondary,
      .bambu-ams-card mmu-controls .v-row:not(:last-child) .v-btn,
      [layout-path="dashboard.mmu-card"] .bambu-btn-secondary,
      .mmu-card .bambu-btn-secondary,
      .mmu-card mmu-controls .v-row:not(:last-child) .v-btn {
        height: 28px !important;
        min-height: 28px !important;
        max-height: 28px !important;
        padding: 0 4px !important;
        background: rgba(255, 255, 255, 0.045) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 6px !important;
        color: #D4D4D8 !important;
        font-weight: 600 !important;
        font-size: 0.65rem !important;
        letter-spacing: 0.02em !important;
        white-space: nowrap !important;
        text-overflow: ellipsis !important;
        overflow: hidden !important;
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25) !important;
        transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1) !important;
        width: 100% !important;
      }

      .v-application .bambu-ams-card .bambu-btn-secondary .v-btn__content,
      .v-application .bambu-ams-card mmu-controls .v-row:not(:last-child) .v-btn .v-btn__content {
        font-size: 0.65rem !important;
        letter-spacing: 0.01em !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        white-space: nowrap !important;
        padding: 0 2px !important;
      }

      .v-application .bambu-ams-card .bambu-btn-secondary .v-icon,
      .theme--dark.v-btn.bambu-btn-secondary .v-icon,
      .mmu-card mmu-controls .v-row:not(:last-child) .v-btn .v-icon {
        font-size: 11px !important;
        margin-right: 2px !important;
      }

      .v-application .bambu-ams-card .bambu-btn-secondary:hover:not(:disabled),
      .v-application .bambu-ams-card mmu-controls .v-row:not(:last-child) .v-btn:hover:not(:disabled),
      .theme--dark.v-btn.bambu-btn-secondary:hover:not(:disabled),
      [layout-path="dashboard.mmu-card"] .bambu-btn-secondary:hover:not(:disabled),
      .mmu-card .bambu-btn-secondary:hover:not(:disabled) {
        background: rgba(255, 255, 255, 0.1) !important;
        border-color: rgba(255, 255, 255, 0.22) !important;
        color: #FFFFFF !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 3px 8px rgba(0, 0, 0, 0.35) !important;
      }

      /* Primary Action Bar: Big Bold UNLOAD & LOAD Buttons (order: 2, breaks onto next row) */
      .v-application .bambu-ams-card mmu-controls .v-row:last-child,
      .v-application .bambu-ams-card mmu-controls .row:last-child,
      .bambu-ams-card mmu-controls .v-row:last-child,
      .bambu-ams-card mmu-controls .row:last-child,
      [layout-path="dashboard.mmu-card"] mmu-controls .v-row:last-child,
      [layout-path="dashboard.mmu-card"] mmu-controls .row:last-child,
      .mmu-card mmu-controls .v-row:last-child,
      .mmu-card mmu-controls .row:last-child {
        margin: 4px 0 0 0 !important;
        display: flex !important;
        flex: 1 1 100% !important;
        width: 100% !important;
        order: 2 !important;
        gap: 6px !important;
      }

      .v-application .bambu-ams-card mmu-controls .v-row:last-child > .v-col,
      .v-application .bambu-ams-card mmu-controls .v-row:last-child > [class*="v-col"],
      .v-application .bambu-ams-card mmu-controls .row:last-child > .col,
      .v-application .bambu-ams-card mmu-controls .row:last-child > [class*="col"],
      .bambu-ams-card mmu-controls .v-row:last-child > .v-col,
      .bambu-ams-card mmu-controls .v-row:last-child > [class*="v-col"],
      .bambu-ams-card mmu-controls .row:last-child > .col,
      .bambu-ams-card mmu-controls .row:last-child > [class*="col"],
      [layout-path="dashboard.mmu-card"] mmu-controls .v-row:last-child > [class*="v-col"],
      .mmu-card mmu-controls .v-row:last-child > [class*="v-col"] {
        padding: 0 !important;
        margin: 0 !important;
        flex: 1 1 0 !important;
        max-width: none !important;
      }

      /* UNLOAD Button: High-Tech Warm Coral Pill */
      .v-application .bambu-ams-card .bambu-btn-unload,
      .theme--dark.v-btn.bambu-btn-unload,
      .bambu-btn-unload,
      [layout-path="dashboard.mmu-card"] .bambu-btn-unload,
      .mmu-card .bambu-btn-unload {
        height: 42px !important;
        min-height: 42px !important;
        width: 100% !important;
        border-radius: 10px !important;
        font-weight: 800 !important;
        font-size: 0.95rem !important;
        letter-spacing: 0.05em !important;
        text-transform: uppercase !important;
        background: linear-gradient(135deg, rgba(255, 87, 34, 0.28) 0%, rgba(216, 67, 21, 0.42) 100%) !important;
        background-color: rgba(255, 87, 34, 0.28) !important;
        color: #FF7043 !important;
        border: 1.5px solid rgba(255, 87, 34, 0.55) !important;
        box-shadow: 0 3px 12px rgba(255, 87, 34, 0.2) !important;
        transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1) !important;
      }

      .v-application .bambu-ams-card .bambu-btn-unload:hover:not(:disabled),
      .theme--dark.v-btn.bambu-btn-unload:hover:not(:disabled),
      [layout-path="dashboard.mmu-card"] .bambu-btn-unload:hover:not(:disabled),
      .mmu-card .bambu-btn-unload:hover:not(:disabled) {
        background: linear-gradient(135deg, #FF5722 0%, #D84315 100%) !important;
        background-color: #FF5722 !important;
        color: #FFFFFF !important;
        border-color: #FF7043 !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 5px 16px rgba(255, 87, 34, 0.4) !important;
      }

      /* UNLOAD Button when disabled/standby */
      .v-application .bambu-ams-card .bambu-btn-unload.v-btn--disabled,
      .v-application .bambu-ams-card .bambu-btn-unload:disabled,
      .theme--dark.v-btn.bambu-btn-unload.v-btn--disabled,
      .theme--dark.v-btn.bambu-btn-unload.v-btn--disabled.v-btn--has-bg,
      .bambu-btn-unload.v-btn--disabled,
      [layout-path="dashboard.mmu-card"] .bambu-btn-unload.v-btn--disabled,
      .mmu-card .bambu-btn-unload.v-btn--disabled {
        background: rgba(255, 112, 67, 0.14) !important;
        background-color: rgba(255, 112, 67, 0.14) !important;
        color: rgba(255, 112, 67, 0.65) !important;
        border: 1px solid rgba(255, 112, 67, 0.32) !important;
        opacity: 0.65 !important;
        cursor: not-allowed !important;
        box-shadow: none !important;
        transform: none !important;
      }

      /* LOAD Button: Iconic Bambu Green */
      .v-application .bambu-ams-card .bambu-btn-load,
      .theme--dark.v-btn.bambu-btn-load,
      .bambu-btn-load,
      [layout-path="dashboard.mmu-card"] .bambu-btn-load,
      .mmu-card .bambu-btn-load {
        height: 42px !important;
        min-height: 42px !important;
        width: 100% !important;
        border-radius: 10px !important;
        font-weight: 800 !important;
        font-size: 0.95rem !important;
        letter-spacing: 0.05em !important;
        text-transform: uppercase !important;
        background: linear-gradient(135deg, #00C250 0%, #00963C 100%) !important;
        background-color: #00C250 !important;
        color: #FFFFFF !important;
        border: 1.5px solid rgba(255, 255, 255, 0.25) !important;
        box-shadow: 0 3px 14px rgba(0, 194, 80, 0.35) !important;
        transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1) !important;
      }

      .v-application .bambu-ams-card .bambu-btn-load:hover:not(:disabled),
      .theme--dark.v-btn.bambu-btn-load:hover:not(:disabled),
      [layout-path="dashboard.mmu-card"] .bambu-btn-load:hover:not(:disabled),
      .mmu-card .bambu-btn-load:hover:not(:disabled) {
        background: linear-gradient(135deg, #00E65E 0%, #00AE42 100%) !important;
        background-color: #00E65E !important;
        color: #FFFFFF !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 5px 18px rgba(0, 194, 80, 0.5) !important;
        filter: brightness(1.06) !important;
      }

      /* LOAD Button when in standby / disabled: Sleek dark green indicator */
      .v-application .bambu-ams-card .bambu-btn-load.v-btn--disabled,
      .v-application .bambu-ams-card .bambu-btn-load:disabled,
      .theme--dark.v-btn.bambu-btn-load.v-btn--disabled,
      .theme--dark.v-btn.bambu-btn-load.v-btn--disabled.v-btn--has-bg,
      .bambu-btn-load.v-btn--disabled,
      [layout-path="dashboard.mmu-card"] .bambu-btn-load.v-btn--disabled,
      .mmu-card .bambu-btn-load.v-btn--disabled {
        background: rgba(0, 174, 66, 0.22) !important;
        background-color: rgba(0, 174, 66, 0.22) !important;
        color: rgba(0, 230, 94, 0.85) !important;
        border: 1.2px solid rgba(0, 174, 66, 0.45) !important;
        opacity: 0.75 !important;
        cursor: not-allowed !important;
        box-shadow: 0 0 10px rgba(0, 174, 66, 0.2) !important;
        transform: none !important;
      }

      /* Generic disabled button */
      .v-application .bambu-ams-card .bambu-btn-secondary:disabled,
      .theme--dark.v-btn.bambu-btn-secondary:disabled,
      [layout-path="dashboard.mmu-card"] .bambu-btn-secondary:disabled,
      .mmu-card .bambu-btn-secondary:disabled {
        opacity: 0.4 !important;
        cursor: not-allowed !important;
        box-shadow: none !important;
        transform: none !important;
      }
    `;

    // 2. Decorate card root
    card.classList.add('bambu-ams-card', 'mmu-card');

    // 3. Decorate AMS chamber units
    const units = card.querySelectorAll('.mmu-unit');
    units.forEach((u) => {
      u.classList.add('bambu-ams-unit');
      // Bay slots
      const gates = u.querySelectorAll('.gate');
      gates.forEach((g) => {
        g.classList.add('bambu-ams-bay');
        if (g.querySelector('.highlight-spool') || g.classList.contains('highlight-spool')) {
          g.classList.add('bambu-bay-active');
        } else {
          g.classList.remove('bambu-bay-active');
        }
      });
      // Footer
      const footer = u.querySelector('.position-relative, [class*="footer"], mmu-unit-footer');
      if (footer) footer.classList.add('bambu-ams-footer');
    });

    // 4. Decorate Filament Status & Toolhead Flow
    const filStatusSvg = card.querySelector('svg.svg-colors, [ref="filStatusSvg"]');
    if (filStatusSvg) {
      const filCol = filStatusSvg.closest('.v-col, .col');
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
            if (col.querySelector('mmu-controls') || col.closest('mmu-controls')) return;
            col.style.display = 'none';
          });
          // Undo any stale hiding from earlier versions
          card.querySelectorAll('mmu-controls .col, mmu-controls .v-col, mmu-controls [class*="col-"]').forEach((c) => {
            c.style.display = '';
          });
        }

        // Extract nozzle temperature or tool text if available
        let nozzleTemp = '';
        const allSvgTexts = filStatusSvg.querySelectorAll('text');
        allSvgTexts.forEach((t) => {
          const content = (t.textContent || '').trim();
          if (content.includes('°C')) {
            nozzleTemp = content;
          }
        });

        // Determine active gate or loaded status
        let statusText = 'Filament: Unloaded';
        allSvgTexts.forEach((t) => {
          const content = (t.textContent || '').trim();
          if (/unloaded|loaded|printing/i.test(content)) {
            statusText = content;
          }
        });

        const activeBay = card.querySelector('.bambu-bay-active, .highlight-spool');
        if (activeBay) {
          const gText = activeBay.querySelector('text');
          const gateNum = gText ? gText.textContent.trim() : '';
          statusText = gateNum ? `Loaded: Gate ${gateNum}` : 'Filament: Loaded';
        }

        // Inject or update sleek HTML status ribbon
        let ribbon = filCol.querySelector('.bambu-status-ribbon');
        if (!ribbon) {
          ribbon = document.createElement('div');
          ribbon.className = 'bambu-status-ribbon';
          filCol.insertBefore(ribbon, filCol.firstChild);
        }

        ribbon.style.cursor = 'pointer';
        ribbon.title = 'Click to open KLIPPACE Tool Mapper';
        ribbon.onclick = (e) => {
          e.stopPropagation();
          openToolMapper();
        };

        ribbon.innerHTML = `
          <div class="bambu-status-left">
            <span class="bambu-status-dot"></span>
            <span class="bambu-status-title">${statusText}</span>
          </div>
          <div class="bambu-status-right">
            <span class="bambu-temp-badge">${nozzleTemp || 'Nozzle: Ready'}</span>
          </div>
        `;
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

    // 6. Decorate Title with AMS Badge
    const titleEl = card.querySelector('.v-card__title');
    if (titleEl && !titleEl.querySelector('.bambu-ams-title-badge')) {
      const badge = document.createElement('span');
      badge.className = 'bambu-ams-title-badge';
      badge.textContent = 'AMS';
      titleEl.appendChild(badge);
    }

    // 7. Decorate Control Buttons
    const btns = card.querySelectorAll('.v-btn');
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
    injectButtons();

    // Re-apply immediately when Vue mutates the DOM
    let debounceTimer = null;
    const observer = new MutationObserver(() => {
      if (debounceTimer) return;
      debounceTimer = setTimeout(() => {
        debounceTimer = null;
        injectButtons();
      }, 100);
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Periodic heartbeat fallback
    setInterval(injectButtons, 1200);
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
