class EltakoDiagnosticsPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._events = [];
    this._timer = null;
    this._filter = "";
    this._gateway = "";
    this._level = "";
    this._error = "";
    this._rendered = false;
    this._refreshMs = Number(localStorage.getItem("eltakoDiagnosticsRefreshMs") || 2000);
  }

  set hass(value) {
    this._hass = value;
    if (!this._timer) {
      this._load();
      this._restartTimer();
    }
  }

  _restartTimer() {
    if (this._timer) window.clearInterval(this._timer);
    this._timer = window.setInterval(() => this._load(), this._refreshMs);
  }

  connectedCallback() {
    this._renderShell();
    this._updateView();
  }

  disconnectedCallback() {
    if (this._timer) window.clearInterval(this._timer);
    this._timer = null;
  }

  async _load() {
    if (!this._hass) return;
    try {
      const response = await this._hass.connection.sendMessagePromise({
        type: "eltako_sensors_actuators/diagnostics/get",
      });
      this._events = response.events || [];
      this._error = "";
      this._renderShell();
      this._updateView();
    } catch (err) {
      this._error = String(err);
      this._renderShell();
      this._updateView();
    }
  }

  async _clear() {
    if (!this._hass || !confirm("ELTAKO-Diagnosepuffer wirklich leeren?")) return;
    await this._hass.connection.sendMessagePromise({
      type: "eltako_sensors_actuators/diagnostics/clear",
    });
    await this._load();
  }

  _filtered() {
    const q = this._filter.toLowerCase().trim();
    return this._events.filter((event) => {
      const text = JSON.stringify(event).toLowerCase();
      const gateway = event.gateway || event.gateway_type || "";
      return (
        (!q || text.includes(q)) &&
        (!this._level || event.level === this._level) &&
        (!this._gateway || gateway === this._gateway)
      );
    });
  }

  _renderShell() {
    if (!this.shadowRoot || this._rendered) return;
    this.shadowRoot.innerHTML = `<style>
      :host {
        display: block;
        min-height: 100vh;
        color: var(--primary-text-color);
        background: var(--primary-background-color);
        font-family: var(--paper-font-body1_-_font-family, Arial, sans-serif);
      }
      header {
        position: sticky;
        top: 0;
        z-index: 10;
        padding: 16px 20px;
        background: var(--card-background-color);
        border-bottom: 1px solid var(--divider-color);
        box-shadow: 0 2px 8px rgba(0,0,0,.12);
      }
      .title-row { display:flex; align-items:center; justify-content:space-between; gap:16px; }
      h1 { margin:0; font-size:24px; }
      .live { display:flex; align-items:center; gap:7px; color:var(--secondary-text-color); font-size:13px; }
      .live-dot { width:9px; height:9px; border-radius:50%; background:#2e7d32; box-shadow:0 0 0 3px rgba(46,125,50,.18); }
      .controls { display:grid; grid-template-columns:minmax(260px,1fr) 150px 190px 150px auto auto; gap:10px; margin-top:14px; }
      input, select, button {
        box-sizing:border-box;
        min-height:42px;
        padding:9px 12px;
        border:1px solid var(--divider-color);
        border-radius:9px;
        color:var(--primary-text-color);
        background:var(--secondary-background-color);
        font:inherit;
      }
      input:focus, select:focus, button:focus { outline:2px solid var(--primary-color); outline-offset:1px; }
      button { cursor:pointer; font-weight:600; }
      button.primary { color:var(--text-primary-color, #fff); background:var(--primary-color); border-color:var(--primary-color); }
      button.danger { color:var(--error-color, #b00020); }
      .summary { display:flex; gap:14px; flex-wrap:wrap; margin-top:11px; color:var(--secondary-text-color); font-size:13px; }
      .badge { padding:3px 8px; border-radius:999px; background:var(--secondary-background-color); }
      .error-banner { margin-top:10px; padding:10px 12px; border-radius:8px; color:var(--error-color); background:rgba(244,67,54,.12); }
      main { padding:16px; overflow:auto; }
      .table-wrap { overflow:auto; border:1px solid var(--divider-color); border-radius:12px; background:var(--card-background-color); }
      table { width:100%; border-collapse:separate; border-spacing:0; min-width:950px; }
      th, td { text-align:left; vertical-align:top; padding:10px 12px; border-bottom:1px solid var(--divider-color); font-size:12px; }
      th { position:sticky; top:0; z-index:2; background:var(--card-background-color); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
      tbody tr:last-child td { border-bottom:0; }
      tbody tr:hover td { background:var(--secondary-background-color); }
      td.time, td.level, td.type { white-space:nowrap; font-family:monospace; }
      td.details { font-family:monospace; line-height:1.55; }
      td.details span { display:inline-block; margin:0 10px 4px 0; padding:2px 6px; border-radius:5px; background:var(--secondary-background-color); border-left:3px solid transparent; }
      td.details .field-gateway { border-left-color:#2196f3; background:rgba(33,150,243,.13); }
      td.details .field-sender_id, td.details .field-physical_sender_id { border-left-color:#00acc1; background:rgba(0,172,193,.13); }
      td.details .field-device_id, td.details .field-target_id { border-left-color:#8e24aa; background:rgba(142,36,170,.13); }
      td.details .field-eep, td.details .field-sender_eep { border-left-color:#43a047; background:rgba(67,160,71,.13); }
      td.details .field-raw, td.details .field-data_hex, td.details .field-frame, td.details .field-decoded { border-left-color:#fb8c00; background:rgba(251,140,0,.13); }
      td.details .field-status { border-left-color:#fdd835; background:rgba(253,216,53,.14); }
      td.details .field-state { border-left-color:#7e57c2; background:rgba(126,87,194,.14); font-weight:600; }
      td.details .field-moisture, td.details .field-wet, td.details .field-water_alarm { border-left-color:#0288d1; background:rgba(2,136,209,.14); }
      td.details .field-temperature, td.details .field-target_temperature { border-left-color:#e53935; background:rgba(229,57,53,.12); }
      td.details .field-humidity { border-left-color:#1e88e5; background:rgba(30,136,229,.12); }
      td.details .field-brightness, td.details .field-dawn, td.details .field-sun_west, td.details .field-sun_south, td.details .field-sun_east { border-left-color:#f9a825; background:rgba(249,168,37,.14); }
      td.details .field-rain, td.details .field-wind_speed { border-left-color:#039be5; background:rgba(3,155,229,.13); }
      td.details .decoded-field { box-shadow:inset 0 0 0 1px rgba(127,127,127,.08); }
      td.details .field-command { border-left-color:#039be5; background:rgba(3,155,229,.13); }
      td.details .field-error { border-left-color:#e53935; background:rgba(229,57,53,.15); color:var(--error-color); }
      td.details .is-null { opacity:.55; }
      .level-chip { display:inline-block; min-width:62px; padding:3px 8px; border-radius:999px; text-align:center; font-weight:700; text-transform:uppercase; font-size:10px; }
      .debug .level-chip { color:#455a64; background:rgba(96,125,139,.18); }
      .info .level-chip { color:#1565c0; background:rgba(33,150,243,.18); }
      .warning .level-chip { color:#9a5a00; background:rgba(255,152,0,.20); }
      .error .level-chip { color:#b71c1c; background:rgba(244,67,54,.20); }
      .warning td:first-child { border-left:4px solid #f59e0b; }
      .error td:first-child { border-left:4px solid #d32f2f; }
      .info td:first-child { border-left:4px solid #1976d2; }
      .debug td:first-child { border-left:4px solid #78909c; }
      .empty { padding:30px; text-align:center; color:var(--secondary-text-color); }
      @media (max-width: 900px) {
        .controls { grid-template-columns:1fr 1fr; }
        .controls input { grid-column:1 / -1; }
      }
    </style>
    <header>
      <div class="title-row">
        <h1>Funk / Bus Diagnose</h1>
        <div class="live"><span class="live-dot"></span>Live-Aktualisierung</div>
      </div>
      <div class="controls">
        <input id="filter" placeholder="Gerät, ID, EEP, Frame oder Fehler suchen">
        <select id="level" aria-label="Meldungsstufe">
          <option value="">Alle Stufen</option>
          <option value="debug">Debug</option>
          <option value="info">Info</option>
          <option value="warning">Warnung</option>
          <option value="error">Fehler</option>
        </select>
        <select id="gateway" aria-label="Gateway"><option value="">Alle Gateways</option></select>
        <select id="refreshRate" aria-label="Aktualisierungsrate">
          <option value="500">0,5 Sekunden</option>
          <option value="1000">1 Sekunde</option>
          <option value="2000">2 Sekunden</option>
          <option value="5000">5 Sekunden</option>
          <option value="10000">10 Sekunden</option>
        </select>
        <button id="refresh" class="primary">Aktualisieren</button>
        <button id="clear" class="danger">Puffer leeren</button>
      </div>
      <div id="summary" class="summary"></div>
      <div id="error" class="error-banner" hidden></div>
    </header>
    <main><div class="table-wrap"><table>
      <thead><tr><th>Zeit</th><th>Stufe</th><th>Ereignis</th><th>Details</th></tr></thead>
      <tbody id="rows"></tbody>
    </table></div></main>`;

    const filter = this.shadowRoot.getElementById("filter");
    const level = this.shadowRoot.getElementById("level");
    const gateway = this.shadowRoot.getElementById("gateway");
    const refreshRate = this.shadowRoot.getElementById("refreshRate");
    refreshRate.value = String(this._refreshMs);
    filter.addEventListener("input", (event) => { this._filter = event.target.value; this._updateView(); });
    level.addEventListener("change", (event) => { this._level = event.target.value; this._updateView(); });
    gateway.addEventListener("change", (event) => { this._gateway = event.target.value; this._updateView(); });
    refreshRate.addEventListener("change", (event) => {
      this._refreshMs = Number(event.target.value) || 2000;
      localStorage.setItem("eltakoDiagnosticsRefreshMs", String(this._refreshMs));
      this._restartTimer();
      this._updateView();
    });
    this.shadowRoot.getElementById("refresh").addEventListener("click", () => this._load());
    this.shadowRoot.getElementById("clear").addEventListener("click", () => this._clear());
    this._rendered = true;
  }

  _updateView() {
    if (!this._rendered) return;
    const gateways = [...new Set(this._events.map((e) => e.gateway || e.gateway_type).filter(Boolean))].sort();
    const gatewaySelect = this.shadowRoot.getElementById("gateway");
    const existing = [...gatewaySelect.options].slice(1).map((option) => option.value);
    if (JSON.stringify(existing) !== JSON.stringify(gateways)) {
      const selected = this._gateway;
      gatewaySelect.replaceChildren(new Option("Alle Gateways", ""), ...gateways.map((value) => new Option(value, value)));
      gatewaySelect.value = gateways.includes(selected) ? selected : "";
      if (!gateways.includes(selected)) this._gateway = "";
    }

    this.shadowRoot.getElementById("filter").value = this._filter;
    this.shadowRoot.getElementById("level").value = this._level;
    gatewaySelect.value = this._gateway;

    const filtered = this._filtered();
    const rows = filtered.slice().reverse().map((event) => {
      const hiddenDetailKeys = new Set(["sequence", "timestamp", "type", "level", "entry_id", "port"]);
      const detailItems = [];
      for (const [key, value] of Object.entries(event)) {
        if (hiddenDetailKeys.has(key)) continue;
        if (key === "decoded" && value && typeof value === "object" && !Array.isArray(value)) {
          for (const [decodedKey, decodedValue] of Object.entries(value)) {
            detailItems.push([decodedKey, decodedValue, " decoded-field"]);
          }
          continue;
        }
        detailItems.push([key, value, ""]);
      }
      const details = detailItems.map(([key, value, extraClass]) => {
        const safeClass = String(key).toLowerCase().replace(/[^a-z0-9_-]/g, "-");
        const nullClass = value === null || value === undefined ? " is-null" : "";
        const rendered = typeof value === "string" ? value : JSON.stringify(value);
        return `<span class="field-${safeClass}${nullClass}${extraClass}"><b>${this._esc(key)}:</b> ${this._esc(rendered)}</span>`;
      }).join(" ");
      const level = ["debug", "info", "warning", "error"].includes(event.level) ? event.level : "info";
      return `<tr class="${level}">
        <td class="time">${this._esc(event.timestamp)}</td>
        <td class="level"><span class="level-chip">${this._esc(event.level)}</span></td>
        <td class="type">${this._esc(event.type)}</td>
        <td class="details">${details}</td>
      </tr>`;
    }).join("");

    this.shadowRoot.getElementById("rows").innerHTML = rows || `<tr><td class="empty" colspan="4">Keine passenden Diagnoseeinträge vorhanden.</td></tr>`;
    this.shadowRoot.getElementById("summary").innerHTML = `
      <span class="badge"><b>${filtered.length}</b> von ${this._events.length} Einträgen</span>
      <span class="badge">Ringpuffer: max. 1000</span>
      <span class="badge">Aktualisierung: ${this._refreshMs < 1000 ? "0,5" : this._refreshMs / 1000} s</span>`;
    const errorBox = this.shadowRoot.getElementById("error");
    errorBox.hidden = !this._error;
    errorBox.textContent = this._error || "";
  }

  _esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
    })[char]);
  }
}

customElements.define("eltako-diagnostics-panel", EltakoDiagnosticsPanel);
