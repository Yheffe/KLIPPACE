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
         Bambu Lab AMS Styling for Fluidd MMU Card
         ========================================================= */

      /* Card Container */
      .v-application .bambu-ams-card,
      .v-card.bambu-ams-card,
      .mmu-card {
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 18px !important;
        background: linear-gradient(180deg, #1C1E26 0%, #121318 100%) !important;
        box-shadow: 0 16px 40px rgba(0, 0, 0, 0.55), inset 0 1px 1px rgba(255, 255, 255, 0.1) !important;
        position: relative !important;
      }

      /* Card Header */
      .v-application .bambu-ams-card .v-card__title,
      .bambu-ams-card .v-card__title,
      .v-application .bambu-ams-card .card-heading {
        font-weight: 700 !important;
        letter-spacing: -0.01em !important;
        color: #FFFFFF !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
        padding-bottom: 12px !important;
        margin-bottom: 12px !important;
        display: flex !important;
        align-items: center !important;
        gap: 8px !important;
      }

      .v-application .bambu-ams-card .bambu-ams-title-badge,
      .bambu-ams-card .bambu-ams-title-badge {
        background: rgba(0, 194, 80, 0.16) !important;
        color: #00C250 !important;
        border: 1px solid rgba(0, 194, 80, 0.35) !important;
        font-size: 0.68rem !important;
        font-weight: 800 !important;
        padding: 1px 7px !important;
        border-radius: 6px !important;
        letter-spacing: 0.08em !important;
        text-transform: uppercase !important;
        display: inline-block !important;
        line-height: 1.4 !important;
      }

      /* AMS Enclosure: Authentic Smoked Acrylic Dome */
      .v-application .bambu-ams-card .bambu-ams-unit:not(.mmu-unit-clear),
      .bambu-ams-card .mmu-unit:not(.mmu-unit-clear) {
        position: relative !important;
        background: linear-gradient(180deg, #2D323E 0%, #171920 100%) !important;
        border: 1.5px solid rgba(255, 255, 255, 0.22) !important;
        border-radius: 20px !important;
        box-shadow: 0 16px 36px -4px rgba(0, 0, 0, 0.75), inset 0 2px 4px rgba(255, 255, 255, 0.3) !important;
        backdrop-filter: blur(16px) !important;
        -webkit-backdrop-filter: blur(16px) !important;
        padding: 16px 10px 12px 10px !important;
        margin-bottom: 16px !important;
        overflow: hidden !important;
      }

      /* Smoked Glass Dome Gloss Reflection */
      .v-application .bambu-ams-card .bambu-ams-unit:not(.mmu-unit-clear)::before,
      .bambu-ams-card .mmu-unit:not(.mmu-unit-clear)::before {
        content: "" !important;
        position: absolute !important;
        top: 0 !important;
        left: 0 !important;
        right: 0 !important;
        height: 48% !important;
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.18) 0%, rgba(255, 255, 255, 0.03) 60%, transparent 100%) !important;
        border-radius: 20px 20px 0 0 !important;
        pointer-events: none !important;
        z-index: 1 !important;
      }

      /* Recessed Cassette Bays */
      .v-application .bambu-ams-card .bambu-ams-bay,
      .bambu-ams-card .gate {
        background: #0E1015 !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 14px !important;
        padding: 10px 4px 8px 4px !important;
        margin: 0 3px !important;
        box-shadow: inset 0 4px 10px rgba(0, 0, 0, 0.7) !important;
        transition: transform 0.22s cubic-bezier(0.16, 1, 0.3, 1),
                    background 0.22s cubic-bezier(0.16, 1, 0.3, 1),
                    border-color 0.22s cubic-bezier(0.16, 1, 0.3, 1),
                    box-shadow 0.22s cubic-bezier(0.16, 1, 0.3, 1) !important;
        position: relative !important;
        z-index: 2 !important;
      }

      .v-application .bambu-ams-card .bambu-ams-bay:hover,
      .bambu-ams-card .gate:hover {
        background: #181B24 !important;
        border-color: rgba(255, 255, 255, 0.25) !important;
        transform: translateY(-2px) !important;
        box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.4), 0 8px 20px rgba(0, 0, 0, 0.5) !important;
      }

      /* Active / Loaded Bay Neon Green Glow */
      .v-application .bambu-ams-card .bambu-ams-bay.bambu-bay-active,
      .v-application .bambu-ams-card .bambu-ams-bay:has(.highlight-spool),
      .bambu-ams-card .gate.highlight-spool {
        border-color: #00C250 !important;
        background: linear-gradient(180deg, rgba(0, 194, 80, 0.16) 0%, #0E1015 100%) !important;
        box-shadow: inset 0 0 16px rgba(0, 194, 80, 0.35), 0 0 18px rgba(0, 194, 80, 0.45) !important;
      }

      /* Spool 3D Depth */
      .v-application .bambu-ams-card .clip-spool,
      .bambu-ams-card .clip-spool {
        filter: drop-shadow(0 8px 14px rgba(0, 0, 0, 0.75)) !important;
        transition: transform 0.22s cubic-bezier(0.16, 1, 0.3, 1) !important;
      }

      .v-application .bambu-ams-card .bambu-ams-bay:hover .clip-spool {
        transform: scale(1.04) !important;
      }

      /* Slot Badges & Pills */
      .v-application .bambu-ams-card .gate-status-row {
        background: transparent !important;
        margin-top: 6px !important;
        display: flex !important;
        justify-content: center !important;
      }

      .v-application .bambu-ams-card svg[ref="mmuGateStatusSvg"],
      .v-application .bambu-ams-card .mmu-gate-status svg {
        max-height: 28px !important;
        filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.6)) !important;
      }

      /* AMS Unit Tag / Footer Badge */
      .v-application .bambu-ams-card .bambu-ams-footer {
        text-align: center !important;
        margin-top: 10px !important;
        padding-top: 6px !important;
      }

      .v-application .bambu-ams-card .bambu-ams-footer span,
      .v-application .bambu-ams-card .bambu-ams-footer div {
        display: inline-flex !important;
        align-items: center !important;
        background: rgba(255, 255, 255, 0.08) !important;
        border: 1px solid rgba(255, 255, 255, 0.14) !important;
        border-radius: 20px !important;
        padding: 4px 16px !important;
        font-size: 0.78rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.08em !important;
        text-transform: uppercase !important;
        color: #E4E4E7 !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3) !important;
      }

      /* Standalone Bypass Spool Bracket */
      .v-application .bambu-ams-card .mmu-unit-clear,
      .bambu-ams-card .mmu-unit-clear {
        background: rgba(255, 255, 255, 0.025) !important;
        border: 1.5px dashed rgba(255, 255, 255, 0.2) !important;
        border-radius: 18px !important;
        box-shadow: none !important;
        padding: 12px 8px !important;
      }

      /* Filament Status & Flow Panel (Left Column) */
      .v-application .bambu-ams-card .bambu-ams-toolhead-panel {
        background: linear-gradient(180deg, #181A22 0%, #0E1015 100%) !important;
        border: 1px solid rgba(255, 255, 255, 0.09) !important;
        border-radius: 14px !important;
        padding: 14px !important;
        box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.5), 0 4px 14px rgba(0, 0, 0, 0.35) !important;
      }

      .v-application .bambu-ams-card .bambu-ams-toolhead-panel .text--disabled.smaller-font {
        font-size: 0.82rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.06em !important;
        text-transform: uppercase !important;
        color: #FFFFFF !important;
        margin-bottom: 10px !important;
        display: inline-flex !important;
        align-items: center !important;
        gap: 8px !important;
      }

      .v-application .bambu-ams-card .bambu-ams-toolhead-panel .text--disabled.smaller-font::before {
        content: "" !important;
        display: inline-block !important;
        width: 8px !important;
        height: 8px !important;
        border-radius: 50% !important;
        background: #00C250 !important;
        box-shadow: 0 0 8px #00C250 !important;
      }

      /* Spool Metadata Card */
      .v-application .bambu-ams-card .bambu-ams-summary-card,
      .bambu-ams-card .v-card.bambu-ams-summary-card {
        display: block !important;
        background: #181A22 !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-left: 4px solid #00C250 !important;
        border-radius: 12px !important;
        padding: 12px 16px !important;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.4) !important;
        margin-bottom: 14px !important;
      }

      .v-application .bambu-ams-card .bambu-ams-summary-card .text-overline {
        color: #00C250 !important;
        font-weight: 800 !important;
        letter-spacing: 0.08em !important;
        font-size: 0.75rem !important;
        margin-bottom: 4px !important;
      }

      .v-application .bambu-ams-card .bambu-ams-summary-card .text-h6 {
        color: #FFFFFF !important;
        font-weight: 700 !important;
        font-size: 1.2rem !important;
        letter-spacing: -0.01em !important;
        margin-bottom: 4px !important;
      }

      .v-application .bambu-ams-card .bambu-ams-summary-card .subtitle-container {
        color: #A1A1AA !important;
        font-size: 0.85rem !important;
      }

      /* Maintenance Utility Buttons */
      .v-application .bambu-ams-card .bambu-btn-secondary,
      .theme--dark.v-btn.bambu-btn-secondary {
        background: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 8px !important;
        color: #E4E4E7 !important;
        font-weight: 600 !important;
        font-size: 0.82rem !important;
        letter-spacing: 0.04em !important;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3) !important;
        transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
      }

      .v-application .bambu-ams-card .bambu-btn-secondary:hover:not(:disabled),
      .theme--dark.v-btn.bambu-btn-secondary:hover:not(:disabled) {
        background: rgba(255, 255, 255, 0.12) !important;
        border-color: rgba(255, 255, 255, 0.25) !important;
        color: #FFFFFF !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4) !important;
      }

      /* UNLOAD Button: High-Tech Warm Pill */
      .v-application .bambu-ams-card .bambu-btn-unload,
      .theme--dark.v-btn.bambu-btn-unload,
      .bambu-btn-unload {
        background: linear-gradient(135deg, rgba(255, 87, 34, 0.25) 0%, rgba(216, 67, 21, 0.38) 100%) !important;
        background-color: rgba(255, 87, 34, 0.25) !important;
        color: #FF7043 !important;
        border: 1.5px solid rgba(255, 87, 34, 0.55) !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        font-size: 0.95rem !important;
        letter-spacing: 0.05em !important;
        box-shadow: 0 4px 14px rgba(255, 87, 34, 0.25) !important;
        transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
      }

      .v-application .bambu-ams-card .bambu-btn-unload:hover:not(:disabled),
      .theme--dark.v-btn.bambu-btn-unload:hover:not(:disabled) {
        background: linear-gradient(135deg, #FF5722 0%, #D84315 100%) !important;
        background-color: #FF5722 !important;
        color: #FFFFFF !important;
        border-color: #FF7043 !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 20px rgba(255, 87, 34, 0.45) !important;
      }

      /* UNLOAD Button when disabled/standby */
      .v-application .bambu-ams-card .bambu-btn-unload.v-btn--disabled,
      .v-application .bambu-ams-card .bambu-btn-unload:disabled,
      .theme--dark.v-btn.bambu-btn-unload.v-btn--disabled,
      .theme--dark.v-btn.bambu-btn-unload.v-btn--disabled.v-btn--has-bg,
      .bambu-btn-unload.v-btn--disabled {
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
      .bambu-btn-load {
        background: linear-gradient(135deg, #00C250 0%, #00963C 100%) !important;
        background-color: #00C250 !important;
        color: #FFFFFF !important;
        border: 1.5px solid rgba(255, 255, 255, 0.3) !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        font-size: 0.95rem !important;
        letter-spacing: 0.05em !important;
        box-shadow: 0 4px 16px rgba(0, 194, 80, 0.45) !important;
        transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
      }

      .v-application .bambu-ams-card .bambu-btn-load:hover:not(:disabled),
      .theme--dark.v-btn.bambu-btn-load:hover:not(:disabled) {
        background: linear-gradient(135deg, #00E65E 0%, #00AE42 100%) !important;
        background-color: #00E65E !important;
        color: #FFFFFF !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 22px rgba(0, 194, 80, 0.6) !important;
        filter: brightness(1.06) !important;
      }

      /* LOAD Button when in standby / disabled: Sleek dark green indicator */
      .v-application .bambu-ams-card .bambu-btn-load.v-btn--disabled,
      .v-application .bambu-ams-card .bambu-btn-load:disabled,
      .theme--dark.v-btn.bambu-btn-load.v-btn--disabled,
      .theme--dark.v-btn.bambu-btn-load.v-btn--disabled.v-btn--has-bg,
      .bambu-btn-load.v-btn--disabled {
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
      .theme--dark.v-btn.bambu-btn-secondary:disabled {
        opacity: 0.4 !important;
        cursor: not-allowed !important;
        box-shadow: none !important;
        transform: none !important;
      }

      /* Tool Mapping Schematic Panel */
      .v-application .bambu-ams-card .bambu-ams-ttg-panel svg,
      .v-application .bambu-ams-card svg[ref="ttgMap"],
      .v-application .bambu-ams-card svg.cursor-pointer[viewBox*="100 100"] {
        display: block !important;
        background: rgba(0, 0, 0, 0.35) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 12px !important;
        padding: 8px !important;
        margin-top: 8px !important;
        box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.45) !important;
        transition: border-color 0.22s ease !important;
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
      const filCol = filStatusSvg.closest('.col');
      if (filCol) filCol.classList.add('bambu-ams-toolhead-panel');
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
      if (txt.includes('preload')) {
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

    // 7. Decorate Tool Mapping Schematic
    const ttgSvg = card.querySelector('svg.cursor-pointer, svg[ref="ttgMap"]');
    if (ttgSvg) {
      const ttgCol = ttgSvg.closest('.col');
      if (ttgCol) ttgCol.classList.add('bambu-ams-ttg-panel');
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
