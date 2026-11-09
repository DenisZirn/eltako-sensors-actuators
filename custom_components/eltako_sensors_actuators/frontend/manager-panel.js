const DOMAIN = "eltako_sensors_actuators";

class EltakoManagerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: "open"});
    this._hass = null;
    this.data = null;
    this.entryId = "";
    this.tab = "devices";
    this.search = "";
    this.group = "";
    this.editing = null;
    this.message = "";
    this.loading = false;
  }

  set hass(value) {
    this._hass = value;
    if (!this.data && !this.loading) this.load();
  }
  set narrow(value) { this._narrow = value; }
  set route(value) { this._route = value; }
  set panel(value) { this._panel = value; }

  esc(value) {
    return String(value == null ? "" : value)
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  }

  async load(keepMessage) {
    if (!this._hass) return;
    this.loading = true;
    if (!keepMessage) this.message = "";
    this.render();
    try {
      this.data = await this._hass.callWS({type: DOMAIN + "/manager/get"});
      var entries = this.data.entries || [];
      if (!this.entryId || !entries.some((x) => x.entry_id === this.entryId)) {
        this.entryId = entries.length ? entries[0].entry_id : "";
      }
    } catch (err) {
      this.message = "Fehler beim Laden: " + (err && err.message ? err.message : err);
    }
    this.loading = false;
    this.render();
  }

  entry() {
    return (this.data && this.data.entries || []).find((x) => x.entry_id === this.entryId) || null;
  }

  catalog() {
    return this.data && this.data.catalog && this.data.catalog.devices || [];
  }

  groups() {
    return Array.from(new Set(this.catalog().map((x) => x.group).filter(Boolean))).sort((a,b) => a.localeCompare(b, "de"));
  }

  filteredCatalog() {
    var q = this.search.trim().toLowerCase();
    return this.catalog().filter((item) => {
      if (this.group && item.group !== this.group) return false;
      if (!q) return true;
      return [item.label,item.device_type,item.eep_out,item.group,item.eltako,item.key]
        .filter(Boolean).some((v) => String(v).toLowerCase().includes(q));
    });
  }

  style() {
    return [
      ":host{display:block;min-height:100%;color:var(--primary-text-color);background:var(--primary-background-color);font-family:Roboto,sans-serif}",
      "*{box-sizing:border-box}.page{max-width:1500px;margin:0 auto;padding:22px}",
      ".top{display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin-bottom:18px}",
      "h1{font-size:28px;margin:0 0 4px}.sub,.muted{color:var(--secondary-text-color)}",
      ".actions,.tabs,.filters{display:flex;gap:8px;align-items:center;flex-wrap:wrap}",
      "button,a.btn,select,input,textarea{font:inherit;border:1px solid var(--divider-color);border-radius:10px;background:var(--card-background-color);color:var(--primary-text-color)}",
      "button,a.btn{padding:10px 14px;cursor:pointer;text-decoration:none}button.primary{background:var(--primary-color);color:white;border-color:var(--primary-color)}button.danger{color:var(--error-color)}",
      "select,input,textarea{padding:10px 12px;min-height:42px}textarea{width:100%;min-height:320px;font-family:monospace}",
      ".tabs{border-bottom:1px solid var(--divider-color);gap:0;margin-bottom:18px}.tab{border:0;border-radius:0;background:transparent;border-bottom:3px solid transparent}.tab.active{border-bottom-color:var(--primary-color);color:var(--primary-color);font-weight:600}",
      ".card,.stat,.profile{background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:14px}.card{padding:18px;margin-bottom:14px}",
      ".stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:16px}.stat{padding:16px}.big{font-size:26px;font-weight:700}.small{color:var(--secondary-text-color);font-size:13px}",
      "table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:11px 9px;border-bottom:1px solid var(--divider-color)}th{font-size:12px;color:var(--secondary-text-color);text-transform:uppercase}.right{text-align:right}",
      ".mono{font-family:monospace}.badge{display:inline-block;padding:4px 8px;border-radius:999px;background:var(--secondary-background-color);font-size:12px}.empty{text-align:center;padding:40px;color:var(--secondary-text-color)}",
      ".catalog{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}.profile{padding:15px}.profile h3{font-size:16px;margin:0 0 7px}.meta{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}",
      ".msg{padding:11px 14px;border-radius:10px;background:var(--secondary-background-color);margin-bottom:14px}",
      ".modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;padding:18px;z-index:10}.modal{width:min(720px,100%);max-height:92vh;overflow:auto;background:var(--card-background-color);border-radius:16px;padding:22px}",
      ".grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}label{display:flex;flex-direction:column;gap:6px;color:var(--secondary-text-color);font-size:13px}.full{grid-column:1/-1}.footer{display:flex;justify-content:flex-end;gap:8px;margin-top:20px}",
      ".last{padding:10px 12px;border-radius:10px;background:var(--secondary-background-color);display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:12px}.scroll{overflow:auto}",
      "@media(max-width:760px){.page{padding:12px}.grid{grid-template-columns:1fr}h1{font-size:23px}}"
    ].join("");
  }

  render() {
    var root = this.shadowRoot;
    var entry = this.entry();
    var entries = this.data && this.data.entries || [];
    var devices = entry && entry.devices || [];
    var html = "<style>" + this.style() + "</style><div class='page'>";
    html += "<div class='top'><div><h1>ELTAKO Gerätekonfiguration</h1><div class='sub'>Integrierter EEDTOY-Test · " +
      this.esc(this.data && this.data.beta || "0.2.0-beta.1") + " · Katalog " +
      this.esc(this.data && this.data.catalog && this.data.catalog.source_version || "?") + "</div></div><div class='actions'>";
    if (entries.length) {
      html += "<select id='entry'>";
      entries.forEach((x) => {
        html += "<option value='" + this.esc(x.entry_id) + "'" + (x.entry_id === this.entryId ? " selected" : "") + ">" +
          this.esc(x.title || x.gateway_type || "ELTAKO") + " · " + this.esc(x.port || "") + "</option>";
      });
      html += "</select>";
    }
    html += "<a class='btn' href='/eltako-diagnostics'>Funk-/Bus-Diagnose</a><button id='refresh'>Aktualisieren</button></div></div>";
    if (this.message) html += "<div class='msg'>" + this.esc(this.message) + "</div>";
    if (this.loading && !this.data) html += "<div class='card empty'>Konfiguration wird geladen …</div>";
    if (!this.loading && !entries.length) html += "<div class='card empty'>Noch kein ELTAKO-Gateway eingerichtet.</div>";

    if (entry) {
      html += "<div class='stats'>" +
        "<div class='stat'><div class='big'>" + devices.length + "</div><div class='small'>konfigurierte Geräte</div></div>" +
        "<div class='stat'><div class='big'>" + this.catalog().length + "</div><div class='small'>EEDTOY-Geräteprofile</div></div>" +
        "<div class='stat'><div class='big'>" + this.esc(entry.gateway_type || "auto") + "</div><div class='small'>Gateway-Typ</div></div>" +
        "<div class='stat'><div class='big'>" + this.esc(this.data.areas && this.data.areas.length || 0) + "</div><div class='small'>HA-Räume</div></div></div>";
      html += "<div class='tabs'><button class='tab " + (this.tab==="devices"?"active":"") + "' data-tab='devices'>Geräte</button>" +
        "<button class='tab " + (this.tab==="catalog"?"active":"") + "' data-tab='catalog'>Gerätekatalog</button>" +
        "<button class='tab " + (this.tab==="export"?"active":"") + "' data-tab='export'>Import / Export</button></div>";
      if (this.tab === "devices") html += this.renderDevices(entry);
      if (this.tab === "catalog") html += this.renderCatalog();
      if (this.tab === "export") html += this.renderExport();
    }
    html += "</div>";
    if (this.editing) html += this.renderModal(entry);
    root.innerHTML = html;
    this.bind();
  }

  renderDevices(entry) {
    var devices = entry.devices || [];
    var html = "<div class='card'><div class='top' style='margin-bottom:10px'><div><strong>Geräte an diesem Gateway</strong><div class='muted'>Direkte Konfiguration ohne externen YAML-Editor.</div></div><button class='primary' id='add'>+ Gerät hinzufügen</button></div>";
    if (entry.last_telegram && entry.last_telegram.sender_id) {
      html += "<div class='last'><div><span class='muted'>Zuletzt empfangen:</span> <span class='mono'>" + this.esc(entry.last_telegram.sender_id) +
        "</span> <span class='badge'>" + this.esc(entry.last_telegram.eep || "EEP unbekannt") + "</span></div><button id='add-last'>Als Gerät übernehmen</button></div>";
    }
    if (!devices.length) return html + "<div class='empty'>Noch keine Geräte konfiguriert.</div></div>";
    html += "<div class='scroll'><table><thead><tr><th>Name</th><th>ID</th><th>EEP</th><th>Typ</th><th>Raum</th><th></th></tr></thead><tbody>";
    devices.forEach((d,i) => {
      html += "<tr><td><strong>" + this.esc(d.name || "ELTAKO Gerät") + "</strong><div class='muted'>" + this.esc(d.platform || "") +
        "</div></td><td class='mono'>" + this.esc(d.id || "") + "</td><td><span class='badge'>" + this.esc(d.eep || "") +
        "</span></td><td>" + this.esc(d.device_type || d.profile_key || "") + "</td><td>" + this.esc(d.area || "—") +
        "</td><td class='right'><button data-edit='" + i + "'>Bearbeiten</button> <button class='danger' data-delete='" + i + "'>Löschen</button></td></tr>";
    });
    return html + "</tbody></table></div></div>";
  }

  renderCatalog() {
    var list = this.filteredCatalog();
    var html = "<div class='card'><div class='filters'><input id='search' style='flex:1;min-width:240px' placeholder='Gerät, EEP oder Typ suchen …' value='" + this.esc(this.search) + "'><select id='group'><option value=''>Alle Gruppen</option>";
    this.groups().forEach((g) => html += "<option value='" + this.esc(g) + "'" + (g===this.group?" selected":"") + ">" + this.esc(g) + "</option>");
    html += "</select><span class='muted'>" + list.length + " Profile</span></div></div><div class='catalog'>";
    list.forEach((p) => {
      html += "<div class='profile'><h3>" + this.esc(p.label || p.device_type || p.key) + "</h3><div class='muted'>" + this.esc(p.group || "") +
        "</div><div class='meta'><span class='badge'>" + this.esc(p.eep_out || "") + "</span><span class='badge'>" + this.esc(p.platform || "") +
        "</span>" + (p.needs_sender ? "<span class='badge'>Sender-ID erforderlich</span>" : "") +
        "</div><button class='primary' data-profile='" + this.esc(p.key) + "'>Dieses Gerät hinzufügen</button></div>";
    });
    return html + "</div>";
  }

  renderExport() {
    return "<div class='card'><h3 style='margin-top:0'>Backup / Kompatibilität</h3><p class='muted'>Die Geräteverwaltung speichert direkt in der Integration. YAML bleibt als Backup- und Austauschformat erhalten.</p>" +
      "<div class='actions'><button class='primary' id='export'>YAML erzeugen</button><button id='copy'>YAML kopieren</button></div>" +
      "<textarea id='yaml' readonly placeholder='Hier erscheint der Export …'></textarea></div>";
  }

  renderModal(entry) {
    var e = this.editing || {};
    var p = this.catalog().find((x) => x.key === e.profile_key);
    var html = "<div class='modal-bg' id='backdrop'><div class='modal'><h2>" + (e.index == null ? "Gerät hinzufügen" : "Gerät bearbeiten") + "</h2><div class='grid'>";
    html += "<label class='full'>Geräteprofil<select id='f-profile'><option value=''>Profil auswählen …</option>";
    this.catalog().forEach((x) => html += "<option value='" + this.esc(x.key) + "'" + (x.key===e.profile_key?" selected":"") + ">" + this.esc(x.label || x.device_type || x.key) + "</option>");
    html += "</select></label>";
    html += "<label>Name<input id='f-name' value='" + this.esc(e.name || p && p.device_type || "") + "'></label>";
    html += "<label>EnOcean-ID<div class='actions'><input style='flex:1' class='mono' id='f-id' value='" + this.esc(e.id || "") + "' placeholder='FE-FE-AD-C8'>" +
      (entry && entry.last_telegram && entry.last_telegram.sender_id ? "<button id='use-last'>Letzte ID</button>" : "") + "</div></label>";
    html += "<label>Raum<input id='f-area' list='areas' value='" + this.esc(e.area || "") + "'><datalist id='areas'>";
    (this.data.areas || []).forEach((a) => html += "<option value='" + this.esc(a.name) + "'></option>");
    html += "</datalist></label><label>Device Class<select id='f-class'><option value=''>Automatisch / keine</option>";
    ((p && p.device_classes) || []).forEach((dc) => html += "<option value='" + this.esc(dc) + "'" + (dc===(e.device_class || p.default_dc)?" selected":"") + ">" + this.esc(dc) + "</option>");
    html += "</select></label>";
    if (p && p.needs_sender) {
      html += "<label>Sender-ID<input class='mono' id='f-sender' value='" + this.esc(e.sender_id || "") + "' placeholder='FF-xx-xx-xx'></label>" +
        "<label>Sender-EEP<input id='f-sender-eep' value='" + this.esc(e.sender_eep || p.sender_eep || "") + "' readonly></label>";
    }
    html += "<div class='full card' style='margin:0;padding:12px'><strong>" + this.esc(p ? (p.label || p.device_type) : "Noch kein Profil gewählt") +
      "</strong><div class='muted'>EEP: " + this.esc(p && p.eep_out || "—") + " · Plattform: " + this.esc(p && p.platform || "—") +
      (p && p.teach_in_telegram ? " · Teach-in: " + this.esc(p.teach_in_telegram) : "") + "</div></div></div>";
    return html + "<div class='footer'><button id='cancel'>Abbrechen</button><button class='primary' id='save'>Speichern</button></div></div></div>";
  }

  openAdd(profileKey, id) {
    var p = this.catalog().find((x) => x.key === (profileKey || ""));
    this.editing = {index:null,profile_key:profileKey||"",id:id||"",name:p&&p.device_type||"",area:"",device_class:p&&p.default_dc||"",sender_id:"",sender_eep:p&&p.sender_eep||""};
    this.render();
  }

  openEdit(index) {
    var d = this.entry() && this.entry().devices[index];
    if (!d) return;
    this.editing = Object.assign({}, d, {index:index, profile_key:d.profile_key || d.raw && d.raw.profile_key || ""});
    this.render();
  }

  value(id) {
    var x = this.shadowRoot.getElementById(id);
    return x ? x.value : "";
  }

  async save() {
    if (!this.editing) return;
    var profile = this.value("f-profile");
    if (!profile) { this.message = "Bitte zuerst ein Geräteprofil auswählen."; this.render(); return; }
    var request = {
      type: DOMAIN + "/manager/save_device",
      entry_id: this.entryId,
      device: {
        profile_key: profile,
        name: this.value("f-name"),
        id: this.value("f-id"),
        area: this.value("f-area"),
        device_class: this.value("f-class"),
        sender_id: this.value("f-sender"),
        sender_eep: this.value("f-sender-eep")
      }
    };
    if (this.editing.index != null) request.index = this.editing.index;
    try {
      await this._hass.callWS(request);
      this.editing = null;
      this.message = "Gerät gespeichert. Die Integration wird neu geladen.";
      await new Promise((r) => setTimeout(r, 700));
      await this.load(true);
    } catch (err) {
      this.message = err && err.message ? err.message : String(err);
      this.render();
    }
  }

  async remove(index) {
    var d = this.entry() && this.entry().devices[index];
    if (!d || !confirm("„" + (d.name || d.id) + "“ wirklich löschen?")) return;
    try {
      await this._hass.callWS({type:DOMAIN + "/manager/delete_device",entry_id:this.entryId,index:index});
      this.message = "Gerät gelöscht. Die Integration wird neu geladen.";
      await new Promise((r) => setTimeout(r, 700));
      await this.load(true);
    } catch (err) { this.message = err && err.message ? err.message : String(err); this.render(); }
  }

  async exportYaml() {
    try {
      var result = await this._hass.callWS({type:DOMAIN + "/manager/export_yaml",entry_id:this.entryId});
      var box = this.shadowRoot.getElementById("yaml");
      if (box) box.value = result.yaml || "";
    } catch (err) { this.message = err && err.message ? err.message : String(err); this.render(); }
  }

  bind() {
    var r = this.shadowRoot;
    var x;
    x=r.getElementById("refresh"); if(x)x.onclick=()=>this.load();
    x=r.getElementById("entry"); if(x)x.onchange=(e)=>{this.entryId=e.target.value;this.render();};
    r.querySelectorAll("[data-tab]").forEach((b)=>b.onclick=()=>{this.tab=b.dataset.tab;this.render();});
    x=r.getElementById("add"); if(x)x.onclick=()=>this.openAdd();
    x=r.getElementById("add-last"); if(x)x.onclick=()=>this.openAdd("",this.entry().last_telegram.sender_id);
    r.querySelectorAll("[data-edit]").forEach((b)=>b.onclick=()=>this.openEdit(Number(b.dataset.edit)));
    r.querySelectorAll("[data-delete]").forEach((b)=>b.onclick=()=>this.remove(Number(b.dataset.delete)));
    r.querySelectorAll("[data-profile]").forEach((b)=>b.onclick=()=>this.openAdd(b.dataset.profile));
    x=r.getElementById("search"); if(x)x.onchange=(e)=>{this.search=e.target.value;this.render();};
    x=r.getElementById("group"); if(x)x.onchange=(e)=>{this.group=e.target.value;this.render();};
    x=r.getElementById("cancel"); if(x)x.onclick=()=>{this.editing=null;this.render();};
    x=r.getElementById("backdrop"); if(x)x.onclick=(e)=>{if(e.target.id==="backdrop"){this.editing=null;this.render();}};
    x=r.getElementById("f-profile"); if(x)x.onchange=(e)=>{
      var old=this.editing||{}, p=this.catalog().find((z)=>z.key===e.target.value);
      this.editing=Object.assign({},old,{profile_key:e.target.value,device_class:p&&p.default_dc||"",sender_eep:p&&p.sender_eep||"",name:old.name||p&&p.device_type||""});
      this.render();
    };
    x=r.getElementById("use-last"); if(x)x.onclick=()=>{var f=r.getElementById("f-id");if(f)f.value=this.entry().last_telegram.sender_id;};
    x=r.getElementById("save"); if(x)x.onclick=()=>this.save();
    x=r.getElementById("export"); if(x)x.onclick=()=>this.exportYaml();
    x=r.getElementById("copy"); if(x)x.onclick=async()=>{var y=r.getElementById("yaml");if(y&&y.value){await navigator.clipboard.writeText(y.value);this.message="YAML kopiert.";this.render();}};
  }
}

customElements.define("eltako-manager-panel", EltakoManagerPanel);
