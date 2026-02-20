/**
 * Hikvision UserPin – Custom Lovelace Cards  v3
 *
 * Cards:
 *   1. hikvision-userpin-users  – User table + create form (PIN-protected actions)
 *   2. hikvision-userpin-events – Events table with paging
 *
 * Config (YAML):
 *   type: custom:hikvision-userpin-users
 *   entry_id: <optional>
 *   pin: "1234"            # required – PIN to unlock QR / Extend / Delete
 *
 *   type: custom:hikvision-userpin-events
 *   entry_id: <optional>
 *   page_size: 10
 */

console.info(
  "%c HIKVISION-USERPIN-CARD %c v3 loaded ",
  "color:#fff;background:#1f6feb;padding:2px 6px;border-radius:3px",
  ""
);

const DOMAIN = "hikvision_userpin";

const DURATION_OPTIONS = [
  { value: "1d", label: "1 Tag" },
  { value: "7d", label: "7 Tage" },
  { value: "14d", label: "14 Tage" },
  { value: "4w", label: "4 Wochen" },
  { value: "3m", label: "3 Monate" },
  { value: "12m", label: "12 Monate" },
  { value: "forever", label: "Immer" },
  { value: "custom", label: "Benutzerdefiniert" },
];
const EXTEND_DURATION_OPTIONS = DURATION_OPTIONS.filter((o) => o.value !== "custom");

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */
function _pad(n) { return n.toString().padStart(2, "0"); }
function _toISO(d) {
  return d.getFullYear() + "-" + _pad(d.getMonth() + 1) + "-" + _pad(d.getDate());
}
function _addMonths(d, months) {
  const r = new Date(d.getTime());
  const target = r.getMonth() + months;
  r.setMonth(target);
  if (r.getMonth() !== ((target % 12) + 12) % 12) r.setDate(0);
  return r;
}
function _computeEnd(startStr, duration) {
  const s = new Date(startStr + "T00:00:00");
  let e = new Date(s.getTime());
  switch (duration) {
    case "1d":   e.setDate(e.getDate() + 1); break;
    case "7d":   e.setDate(e.getDate() + 7); break;
    case "14d":  e.setDate(e.getDate() + 14); break;
    case "4w":   e.setDate(e.getDate() + 28); break;
    case "3m":   e = _addMonths(s, 3); break;
    case "12m":  e = _addMonths(s, 12); break;
    case "forever": return "2099-12-31";
    default:     e.setDate(e.getDate() + 7);
  }
  return _toISO(e);
}
function _esc(s) {
  if (s == null) return "";
  const el = document.createElement("span");
  el.textContent = String(s);
  return el.innerHTML;
}

/* ------------------------------------------------------------------ */
/*  Shared styles                                                     */
/* ------------------------------------------------------------------ */
const SHARED_STYLES = `
  :host { display: block; }
  ha-card { overflow: visible; }
  .card-content { padding: 0 16px 16px; }
  .loading { color: var(--secondary-text-color, #888); font-style: italic; }
  h3 { margin: 16px 0 8px; font-size: 1.1em; color: var(--primary-text-color); }
  .device-selector { margin-bottom: 12px; }
  .device-selector label { font-weight: 600; margin-right: 8px; }
  .device-selector select {
    max-width: 100%; padding: 6px 8px;
    border: 1px solid var(--divider-color, #e5e5e5); border-radius: 4px;
    background: var(--card-background-color, #fff); color: var(--primary-text-color);
  }
  .table-wrap { width: 100%; overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; }
  th, td {
    padding: 8px; border-bottom: 1px solid var(--divider-color, #e5e5e5);
    text-align: left; vertical-align: middle; color: var(--primary-text-color);
  }
  th { font-weight: 600; }
  .actions-cell { min-height: 44px; }
  .actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .btn {
    display: inline-flex; align-items: center; justify-content: center;
    padding: 0 12px; border-radius: 6px; border: 1px solid transparent;
    height: 34px; line-height: 1; font-size: 13px; cursor: pointer; white-space: nowrap;
  }
  .btn:disabled { opacity: 0.4; cursor: default; }
  .btn-primary { background: var(--primary-color, #1f6feb); color: #fff; border-color: var(--primary-color, #1f6feb); }
  .btn-primary:hover:not(:disabled) { opacity: 0.85; }
  .btn-secondary { background: var(--secondary-text-color, #374151); color: #fff; border-color: var(--secondary-text-color, #374151); }
  .btn-secondary:hover:not(:disabled) { opacity: 0.85; }
  .btn-danger { background: var(--error-color, #dc2626); color: #fff; border-color: var(--error-color, #dc2626); }
  .btn-danger:hover:not(:disabled) { opacity: 0.85; }
  .btn-icon { padding: 0 8px; min-width: 44px; height: 44px; }
  .btn-icon ha-icon { --mdc-icon-size: 20px; display: flex; }
  .btn-full { width: 100%; margin-top: 12px; height: 44px; }
  .btn-full ha-icon { --mdc-icon-size: 18px; margin-right: 6px; }
  .protected-badge {
    display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 4px;
    background: var(--divider-color, #e5e5e5); color: var(--secondary-text-color, #666);
  }
  .protected-row td { color: var(--secondary-text-color, #888); }
  /* Collapsible */
  .collapsible { margin-top: 12px; }
  .collapsible-toggle {
    display: flex; align-items: center; gap: 8px; width: 100%;
    padding: 10px 12px; border: 1px solid var(--divider-color, #e5e5e5); border-radius: 8px;
    background: var(--card-background-color, #fff); color: var(--primary-text-color);
    font-size: 15px; font-weight: 600; cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }
  .collapsible-toggle:active { opacity: 0.7; }
  .collapsible-toggle .toggle-icon { --mdc-icon-size: 20px; color: var(--primary-color); }
  .collapsible-toggle .toggle-chevron {
    --mdc-icon-size: 20px; margin-left: auto;
    transition: transform 0.2s ease;
  }
  .collapsible-toggle.open .toggle-chevron { transform: rotate(180deg); }
  .collapsible-body {
    display: none; padding: 12px 0 0;
  }
  .collapsible-body.open { display: block; }
  @media (max-width: 640px) {
    .card-content { padding: 0 12px 12px; }
    table { table-layout: fixed; }
    th, td { padding: 8px 6px; font-size: 13px; }
    .actions { gap: 4px; }
    th:first-child, td:first-child { width: 35%; }
    th:nth-child(2), td:nth-child(2) { width: 35%; font-size: 12px; }
    th:last-child, td:last-child { width: 30%; }
  }
`;

/* ------------------------------------------------------------------ */
/*  Modal styles (shared between PIN + QR)                            */
/* ------------------------------------------------------------------ */
const MODAL_STYLES = `
  .modal-overlay {
    position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
    background: rgba(0,0,0,0.6); z-index: 99999;
    display: flex; align-items: center; justify-content: center;
  }
  .modal-box {
    background: var(--card-background-color, #fff); color: var(--primary-text-color);
    border-radius: 12px; padding: 24px; max-width: 360px; width: 90%;
    text-align: center; box-shadow: 0 8px 32px rgba(0,0,0,0.3);
  }
  .modal-box h3 { margin: 0 0 16px; }
  .modal-box img { max-width: 100%; height: auto; margin: 12px 0; }

  /* PIN keypad */
  .pin-display {
    font-size: 28px; letter-spacing: 8px; font-weight: 700;
    min-height: 44px; line-height: 44px;
    border-bottom: 2px solid var(--divider-color, #ccc);
    margin-bottom: 16px; font-family: monospace;
  }
  .pin-error {
    color: var(--error-color, #dc2626); font-size: 13px;
    min-height: 20px; margin-bottom: 8px;
  }
  .keypad {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
    max-width: 260px; margin: 0 auto;
  }
  .keypad button {
    height: 52px; font-size: 20px; font-weight: 600; border-radius: 8px;
    border: 1px solid var(--divider-color, #ddd); cursor: pointer;
    background: var(--card-background-color, #fff); color: var(--primary-text-color);
  }
  .keypad button:active { background: var(--divider-color, #eee); }
  .keypad .key-wide { grid-column: span 1; font-size: 14px; }
  .key-confirm {
    background: var(--primary-color, #1f6feb) !important;
    color: #fff !important; border-color: var(--primary-color, #1f6feb) !important;
  }
  .key-cancel {
    background: var(--secondary-text-color, #374151) !important;
    color: #fff !important; border-color: var(--secondary-text-color, #374151) !important;
  }
`;

/* ------------------------------------------------------------------ */
/*  Base class                                                        */
/* ------------------------------------------------------------------ */
class HikvisionBaseCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._data = null;
    this._loading = false;
    this._prevSensorState = null;
    this._sensorId = null;
  }

  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    const prev = this._hass;
    this._hass = hass;
    const sid = this._findSensor(hass);
    const st = sid && hass.states[sid] ? hass.states[sid].last_updated : null;
    if (prev && st && st !== this._prevSensorState) {
      this._prevSensorState = st;
      this._fetchData();
    } else if (!prev) {
      this._prevSensorState = st;
      this._fetchData();
    }
  }

  _findSensor(hass) {
    if (this._sensorId) return this._sensorId;
    for (const eid of Object.keys(hass.states)) {
      if (eid.startsWith("sensor.") && eid.includes("user_count")) {
        this._sensorId = eid;
        return eid;
      }
    }
    return null;
  }

  async _fetchData() {
    if (this._loading || !this._hass) return;
    this._loading = true;
    try {
      const q = this._config.entry_id
        ? `?entry_id=${encodeURIComponent(this._config.entry_id)}`
        : "";
      this._data = await this._hass.callApi("GET", `hikvision_userpin/data${q}`);
    } catch (err) {
      console.error("hikvision-userpin: fetch error", err);
      this._data = null;
    }
    this._loading = false;
    this._render();
  }

  async _callService(service, data) {
    try {
      await this._hass.callService(DOMAIN, service, data);
    } catch (err) {
      alert("Fehler: " + (err.message || err));
      return;
    }
    await new Promise((r) => setTimeout(r, 2000));
    await this._fetchData();
  }

  _renderDeviceSelector(d) {
    if (Object.keys(d.entries).length <= 1) return "";
    return `<div class="device-selector">
      <label>Gerät:</label>
      <select id="device_select">
        ${Object.entries(d.entries)
          .map(([eid, n]) => `<option value="${eid}" ${eid === d.entry_id ? "selected" : ""}>${_esc(n)}</option>`)
          .join("")}
      </select>
    </div>`;
  }

  _attachDeviceSelector() {
    const sel = this.shadowRoot.getElementById("device_select");
    if (sel) sel.addEventListener("change", () => {
      this._config = { ...this._config, entry_id: sel.value };
      this._fetchData();
    });
  }

  _render() {}
  getCardSize() { return 4; }
  static getStubConfig() { return {}; }
}

/* ================================================================== */
/*  CARD 1: Users + Create Form + PIN                                 */
/* ================================================================== */
class HikvisionUserPinUsersCard extends HikvisionBaseCard {
  constructor() {
    super();
    this._pinCallback = null; // function to call after PIN success
  }

  getCardSize() { return 6; }

  /* ---- PIN gate -------------------------------------------------- */
  _requirePin(callback) {
    const pin = this._config.pin;
    if (!pin) { callback(); return; } // no PIN configured → skip
    this._pinCallback = callback;
    this._showPinModal();
  }

  _showPinModal() {
    const root = this.shadowRoot;
    const modal = root.getElementById("pin-modal");
    const display = root.getElementById("pin-display");
    const error = root.getElementById("pin-error");
    if (!modal) return;
    display.textContent = "";
    error.textContent = "";
    modal.style.display = "flex";
    modal._value = "";
  }

  _onPinKey(key) {
    const root = this.shadowRoot;
    const modal = root.getElementById("pin-modal");
    const display = root.getElementById("pin-display");
    const error = root.getElementById("pin-error");
    if (!modal) return;
    let val = modal._value || "";

    if (key === "backspace") {
      val = val.slice(0, -1);
    } else if (key === "cancel") {
      modal.style.display = "none";
      this._pinCallback = null;
      return;
    } else if (key === "confirm") {
      if (val === String(this._config.pin)) {
        modal.style.display = "none";
        if (this._pinCallback) { this._pinCallback(); this._pinCallback = null; }
      } else {
        error.textContent = "Falscher PIN";
        val = "";
      }
    } else if (val.length < 8) {
      val += key;
    }

    modal._value = val;
    display.textContent = "\u2022".repeat(val.length);
  }

  /* ---- Render ---------------------------------------------------- */
  _render() {
    const root = this.shadowRoot;
    if (!root) return;
    const d = this._data;
    const loading = this._loading && !d;

    root.innerHTML = `
      <style>${SHARED_STYLES}${MODAL_STYLES}${this._extraStyles()}</style>
      <ha-card header="${_esc(this._config.title || "Hikvision Benutzer")}">
        <div class="card-content">
          ${loading ? '<p class="loading">Laden…</p>' : ""}
          ${d ? this._renderContent(d) : loading ? "" : '<p class="loading">Keine Daten</p>'}
        </div>
      </ha-card>
      ${this._renderPinModal()}
      ${this._renderQrModal()}
    `;
    if (d) this._attachEvents(d);
  }

  _renderContent(d) {
    const protectedSet = new Set(d.protected || []);
    let html = this._renderDeviceSelector(d);

    /* Users table */
    if (d.users && d.users.length) {
      html += `<div class="table-wrap"><table>
        <thead><tr><th>Name</th><th>Gültig</th><th>Aktion</th></tr></thead>
        <tbody>`;
      for (const u of d.users) {
        const begin = u.Valid && u.Valid.beginTime ? u.Valid.beginTime.split("T")[0] : "";
        const end   = u.Valid && u.Valid.endTime   ? u.Valid.endTime.split("T")[0]   : "";
        const isProt = protectedSet.has(u.employeeNo);
        const eno = u.employeeNo;

        if (isProt) {
          html += `<tr class="protected-row">
            <td>${_esc(u.name)}</td>
            <td></td>
            <td></td>
          </tr>`;
          continue;
        }

        html += `<tr>
          <td>${_esc(u.name)}</td>
          <td>${begin} – ${end}</td>
          <td class="actions-cell">`;

        html += `<div class="actions">
            <button class="btn btn-icon btn-primary btn-qr" data-eno="${_esc(eno)}" data-name="${_esc(u.name)}" title="QR-Code"><ha-icon icon="mdi:qrcode"></ha-icon></button>
            <button class="btn btn-icon btn-primary btn-extend" data-eno="${_esc(eno)}" data-name="${_esc(u.name)}" data-begin="${begin}" data-end="${end}" title="Verlängern"><ha-icon icon="mdi:calendar-plus"></ha-icon></button>
            <button class="btn btn-icon btn-danger btn-delete" data-eno="${_esc(eno)}" data-name="${_esc(u.name)}" title="Löschen"><ha-icon icon="mdi:delete"></ha-icon></button>
          </div>
          <div class="extend-form" id="extend-${_esc(eno)}" style="display:none;">
            <label>Verlängern: ${_esc(u.name)}</label>
            <p class="extend-info">Aktuell bis: ${end}</p>
            <select class="extend-duration">
              ${EXTEND_DURATION_OPTIONS.map((o) => `<option value="${o.value}">${o.label}</option>`).join("")}
            </select>
            <div class="extend-buttons">
              <button class="btn btn-primary btn-extend-confirm" data-eno="${_esc(eno)}" data-begin="${begin}" data-end="${end}">Speichern</button>
              <button class="btn btn-secondary btn-extend-cancel" data-eno="${_esc(eno)}">Abbrechen</button>
            </div>
          </div>`;
        html += `</td></tr>`;
      }
      html += `</tbody></table></div>`;
    } else {
      html += `<p>Keine Benutzer auf dem Gerät gefunden.</p>`;
    }

    /* Create form – collapsible */
    html += `
      <div class="collapsible">
        <button class="collapsible-toggle" id="toggle-create" type="button">
          <ha-icon icon="mdi:account-plus" class="toggle-icon"></ha-icon>
          <span>Neuen Benutzer anlegen</span>
          <ha-icon icon="mdi:chevron-down" class="toggle-chevron"></ha-icon>
        </button>
        <div class="collapsible-body" id="create-body">
          <div class="create-form">
            <label for="cf-name">Name</label>
            <input id="cf-name" type="text" required placeholder="Vor- und Nachname" />
            <label for="cf-duration">Gültigkeitsdauer</label>
            <select id="cf-duration">
              ${DURATION_OPTIONS.map((o) => `<option value="${o.value}">${o.label}</option>`).join("")}
            </select>
            <div class="date-row">
              <div class="col">
                <label for="cf-start">Start</label>
                <input id="cf-start" type="date" value="${d.today}" min="${d.today}" required />
              </div>
              <div class="col">
                <label for="cf-end">Ende</label>
                <input id="cf-end" type="date" readonly required />
              </div>
            </div>
            <button class="btn btn-primary btn-full" id="btn-create">
              <ha-icon icon="mdi:check"></ha-icon> Speichern
            </button>
          </div>
        </div>
      </div>`;

    return html;
  }

  /* ---- Modals (rendered OUTSIDE ha-card to avoid overflow clip) --- */
  _renderPinModal() {
    return `
      <div id="pin-modal" class="modal-overlay" style="display:none;">
        <div class="modal-box">
          <h3>PIN eingeben</h3>
          <div class="pin-display" id="pin-display"></div>
          <div class="pin-error" id="pin-error"></div>
          <div class="keypad">
            <button class="key" data-key="1">1</button>
            <button class="key" data-key="2">2</button>
            <button class="key" data-key="3">3</button>
            <button class="key" data-key="4">4</button>
            <button class="key" data-key="5">5</button>
            <button class="key" data-key="6">6</button>
            <button class="key" data-key="7">7</button>
            <button class="key" data-key="8">8</button>
            <button class="key" data-key="9">9</button>
            <button class="key key-wide key-cancel" data-key="cancel">Abbruch</button>
            <button class="key" data-key="0">0</button>
            <button class="key key-wide key-confirm" data-key="confirm">OK</button>
          </div>
        </div>
      </div>`;
  }

  _renderQrModal() {
    return `
      <div id="qr-modal" class="modal-overlay" style="display:none;">
        <div class="modal-box">
          <h3 id="qr-modal-title">QR-Code</h3>
          <img id="qr-modal-img" src="" alt="QR Code" />
          <div style="margin-top:12px;">
            <button class="btn btn-secondary" id="qr-modal-close">Schließen</button>
          </div>
        </div>
      </div>`;
  }

  /* ---- Event wiring ---------------------------------------------- */
  _attachEvents(d) {
    const root = this.shadowRoot;
    this._attachDeviceSelector();

    /* Collapsible toggle */
    const toggleBtn = root.getElementById("toggle-create");
    const createBody = root.getElementById("create-body");
    if (toggleBtn && createBody) {
      toggleBtn.addEventListener("click", () => {
        toggleBtn.classList.toggle("open");
        createBody.classList.toggle("open");
      });
    }

    /* PIN keypad */
    root.querySelectorAll("#pin-modal .key").forEach((btn) => {
      btn.addEventListener("click", () => this._onPinKey(btn.dataset.key));
    });
    const pinModal = root.getElementById("pin-modal");
    if (pinModal) pinModal.addEventListener("click", (e) => {
      if (e.target === pinModal) { pinModal.style.display = "none"; this._pinCallback = null; }
    });

    /* Date computation */
    const cfStart = root.getElementById("cf-start");
    const cfDuration = root.getElementById("cf-duration");
    const cfEnd = root.getElementById("cf-end");
    const updateEnd = () => {
      if (!cfStart || !cfDuration || !cfEnd) return;
      if (cfDuration.value === "custom") {
        cfEnd.readOnly = false; cfEnd.min = cfStart.value; cfEnd.value = cfStart.value; return;
      }
      cfEnd.readOnly = true;
      cfEnd.value = _computeEnd(cfStart.value, cfDuration.value);
      cfEnd.min = cfStart.value;
    };
    if (cfStart) cfStart.addEventListener("change", updateEnd);
    if (cfDuration) cfDuration.addEventListener("change", updateEnd);
    updateEnd();

    /* Create */
    const btnCreate = root.getElementById("btn-create");
    if (btnCreate) btnCreate.addEventListener("click", () => {
      const name = root.getElementById("cf-name").value.trim();
      const startDate = cfStart.value;
      const duration = cfDuration.value;
      const endDate = cfEnd.value;
      if (!name || !startDate) { alert("Bitte Name und Startdatum eingeben."); return; }
      this._callService("create_user", {
        config_entry_id: d.entry_id, name, start_date: startDate, duration, end_date: endDate,
      });
    });

    /* Delete – PIN protected */
    root.querySelectorAll(".btn-delete").forEach((btn) => {
      btn.addEventListener("click", () => {
        const eno = btn.dataset.eno;
        const name = btn.dataset.name;
        this._requirePin(() => {
          if (!confirm(`Benutzer ${name} (${eno}) wirklich löschen?`)) return;
          this._callService("delete_user", { config_entry_id: d.entry_id, employee_no: eno });
        });
      });
    });

    /* QR – PIN protected */
    root.querySelectorAll(".btn-qr").forEach((btn) => {
      btn.addEventListener("click", () => {
        const eno = btn.dataset.eno;
        const name = btn.dataset.name;
        this._requirePin(async () => {
          const modal = root.getElementById("qr-modal");
          const img = root.getElementById("qr-modal-img");
          const title = root.getElementById("qr-modal-title");
          title.textContent = `QR-Code: ${name}`;
          img.src = "";
          modal.style.display = "flex";
          try {
            const resp = await this._hass.callApi(
              "GET", `hikvision_userpin/qr/base64/${encodeURIComponent(eno)}`
            );
            img.src = `data:image/png;base64,${resp.qr_data}`;
          } catch (err) {
            console.error("QR fetch error", err);
            title.textContent = "Fehler beim Laden des QR-Codes";
          }
        });
      });
    });
    /* QR close */
    const qrClose = root.getElementById("qr-modal-close");
    if (qrClose) qrClose.addEventListener("click", () => root.getElementById("qr-modal").style.display = "none");
    const qrModal = root.getElementById("qr-modal");
    if (qrModal) qrModal.addEventListener("click", (e) => { if (e.target === qrModal) qrModal.style.display = "none"; });

    /* Extend toggle – PIN protected */
    root.querySelectorAll(".btn-extend").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._requirePin(() => {
          root.querySelectorAll(".extend-form").forEach((el) => (el.style.display = "none"));
          const form = root.getElementById(`extend-${btn.dataset.eno}`);
          if (form) form.style.display = "block";
        });
      });
    });
    root.querySelectorAll(".btn-extend-cancel").forEach((btn) => {
      btn.addEventListener("click", () => {
        const form = root.getElementById(`extend-${btn.dataset.eno}`);
        if (form) form.style.display = "none";
      });
    });
    root.querySelectorAll(".btn-extend-confirm").forEach((btn) => {
      btn.addEventListener("click", () => {
        const eno = btn.dataset.eno;
        const form = root.getElementById(`extend-${eno}`);
        const sel = form ? form.querySelector(".extend-duration") : null;
        this._callService("extend_user", {
          config_entry_id: d.entry_id, employee_no: eno,
          duration: sel ? sel.value : "7d",
          begin_date: btn.dataset.begin, current_end: btn.dataset.end,
        });
      });
    });
  }

  _extraStyles() {
    return `
      .create-form label, .extend-form label {
        display: block; font-weight: 600; margin-top: 8px; color: var(--primary-text-color);
      }
      .create-form input, .create-form select, .extend-form select {
        width: 100%; padding: 10px; margin-top: 4px;
        font-size: 16px;
        border: 1px solid var(--divider-color, #e5e5e5); border-radius: 8px; box-sizing: border-box;
        background: var(--card-background-color, #fff); color: var(--primary-text-color);
        -webkit-appearance: none; appearance: none;
      }
      .create-form select, .extend-form select {
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23666' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
        background-repeat: no-repeat; background-position: right 10px center;
        padding-right: 30px;
      }
      .date-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
      .date-row .col { min-width: 0; }
      .extend-form {
        margin-top: 8px; padding: 10px;
        background: var(--card-background-color, #fff);
        border: 1px solid var(--divider-color, #e5e5e5); border-radius: 6px;
      }
      .extend-info { margin: 4px 0 8px; font-size: 0.9em; color: var(--secondary-text-color, #888); }
      .extend-buttons { display: flex; gap: 6px; margin-top: 8px; }
      .extend-buttons .btn { flex: 1; height: 44px; }
    `;
  }
}

/* ================================================================== */
/*  CARD 2: Events with paging                                        */
/* ================================================================== */
class HikvisionUserPinEventsCard extends HikvisionBaseCard {
  constructor() { super(); this._page = 0; }
  getCardSize() { return 5; }

  _render() {
    const root = this.shadowRoot;
    if (!root) return;
    const d = this._data;
    const loading = this._loading && !d;
    root.innerHTML = `
      <style>${SHARED_STYLES}${this._extraStyles()}</style>
      <ha-card header="${_esc(this._config.title || "Hikvision Ereignisse")}">
        <div class="card-content">
          ${loading ? '<p class="loading">Laden…</p>' : ""}
          ${d ? this._renderContent(d) : loading ? "" : '<p class="loading">Keine Daten</p>'}
        </div>
      </ha-card>
    `;
    if (d) this._attachEvt(d);
  }

  _renderContent(d) {
    const ps = this._config.page_size || 10;
    const evts = d.events || [];
    const tp = Math.max(1, Math.ceil(evts.length / ps));
    if (this._page >= tp) this._page = tp - 1;
    if (this._page < 0) this._page = 0;
    const slice = evts.slice(this._page * ps, this._page * ps + ps);

    let html = this._renderDeviceSelector(d);
    if (evts.length) {
      html += `<div class="table-wrap"><table>
        <thead><tr><th>Zeit</th><th>User</th><th>Typ</th></tr></thead><tbody>`;
      for (const ev of slice) {
        html += `<tr>
          <td>${_esc(ev.time || "")}</td>
          <td>${_esc(ev.employeeNoString || ev.employeeNo || "")}</td>
          <td>${_esc(ev.description || "")} (${_esc(ev.code || "")})</td>
        </tr>`;
      }
      html += `</tbody></table></div>
        <div class="paging">
          <button class="btn btn-secondary" id="pg-prev" ${this._page === 0 ? "disabled" : ""}>&#9664; Zurück</button>
          <span class="pg-info">Seite ${this._page + 1} / ${tp}</span>
          <button class="btn btn-secondary" id="pg-next" ${this._page >= tp - 1 ? "disabled" : ""}>Weiter &#9654;</button>
        </div>`;
    } else {
      html += `<p>Keine Ereignisse gefunden.</p>`;
    }
    return html;
  }

  _attachEvt(d) {
    const root = this.shadowRoot;
    this._attachDeviceSelector();
    const prev = root.getElementById("pg-prev");
    const next = root.getElementById("pg-next");
    if (prev) prev.addEventListener("click", () => { this._page--; this._render(); });
    if (next) next.addEventListener("click", () => { this._page++; this._render(); });
  }

  _extraStyles() {
    return `
      .paging {
        display: flex; align-items: center; justify-content: center;
        gap: 12px; margin-top: 12px; padding: 8px 0;
      }
      .pg-info { font-size: 14px; color: var(--primary-text-color); min-width: 100px; text-align: center; }
    `;
  }
}

/* ================================================================== */
/*  Register                                                          */
/* ================================================================== */
customElements.define("hikvision-userpin-users", HikvisionUserPinUsersCard);
customElements.define("hikvision-userpin-events", HikvisionUserPinEventsCard);

window.customCards = window.customCards || [];
window.customCards.push(
  { type: "hikvision-userpin-users",  name: "Hikvision Benutzer",    description: "Benutzertabelle mit PIN-Schutz, QR-Codes und Anlegen-Formular." },
  { type: "hikvision-userpin-events", name: "Hikvision Ereignisse",  description: "Ereignistabelle mit Blättern (10 pro Seite)." }
);
