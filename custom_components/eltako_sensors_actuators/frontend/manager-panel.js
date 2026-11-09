const DOMAIN = "eltako_sensors_actuators";

class EltakoManagerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:"open"});
    this._hass=null; this.data=null; this.entryId=""; this.tab="devices";
    this.search=""; this.group=""; this.editing=null; this.message=""; this.loading=false;
    this.importText=""; this.importFilename=""; this.importFormat="auto"; this.preview=null; this.replaceImport=false;
    this.learning=false; this.learnEvents=[]; this.learnUnsub=null;
  }
  set hass(v){this._hass=v;if(!this.data&&!this.loading)this.load();}
  set narrow(v){this._narrow=v} set route(v){this._route=v} set panel(v){this._panel=v}
  disconnectedCallback(){this.stopLearning();}
  esc(v){return String(v==null?"":v).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;")}
  async load(keep){if(!this._hass)return;this.loading=true;if(!keep)this.message="";this.render();try{this.data=await this._hass.callWS({type:DOMAIN+"/manager/get"});var e=this.data.entries||[];if(!this.entryId||!e.some(x=>x.entry_id===this.entryId))this.entryId=e[0]?.entry_id||"";}catch(err){this.message="Fehler beim Laden: "+(err?.message||err)}this.loading=false;this.render()}
  entry(){return (this.data?.entries||[]).find(x=>x.entry_id===this.entryId)||null}
  catalog(){return this.data?.catalog?.devices||[]}
  categoryForGroup(group){
    var g=String(group||"");
    if(["Taster / Schalter","Kontakt"].includes(g))return "Taster & Kontakte";
    if(["Bewegungsmelder","Rauch / Hitze","Wasser"].includes(g))return "Sicherheit & Präsenz";
    if(["Temperatur / Feuchte","Luftqualität","Wetterstation"].includes(g))return "Sensoren & Wetter";
    if(["Raumregler / Klima","Heizung / Stellantrieb"].includes(g))return "Heizung & Klima";
    if(["Licht / Dimmer","Licht / RGBW","Licht / Relais"].includes(g))return "Licht & Schalten";
    if(g==="Jalousie / Rollladen")return "Beschattung";
    if(g==="Lüftung")return "Lüftung";
    if(g==="Zähler")return "Energie & Zähler";
    if(g==="Funk-Modul")return "Funk- & Busmodule";
    return g||"Sonstige";
  }
  categoryOrder(){return ["Taster & Kontakte","Sicherheit & Präsenz","Sensoren & Wetter","Heizung & Klima","Licht & Schalten","Beschattung","Lüftung","Energie & Zähler","Funk- & Busmodule","Sonstige"]}
  categories(){return [...new Set(this.catalog().map(x=>this.categoryForGroup(x.group)))].sort((a,b)=>this.categoryOrder().indexOf(a)-this.categoryOrder().indexOf(b))}
  groups(){return [...new Set(this.catalog().map(x=>x.group).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"de"))}
  filteredCatalog(){var q=this.search.trim().toLowerCase();return this.catalog().filter(x=>(!this.group||this.categoryForGroup(x.group)===this.group)&&(!q||[x.label,x.device_type,x.eep_out,x.group,this.categoryForGroup(x.group),x.eltako,x.key].filter(Boolean).some(v=>String(v).toLowerCase().includes(q))))}
  canProgram(d){return !!(d&&d.sender_id&&["light","switch","cover","fan","climate"].includes(String(d.platform||"").toLowerCase()))}
  isSeries14(d){return !!(d&&(d.bus_address||d.bus_base_id||d.raw?.bus_address||d.raw?.bus_base_id))}
  profile(key){return this.catalog().find(x=>x.key===key)}
  profileShortName(p){
    if(!p)return "Gerät";
    return String(p.device_type||p.eltako||p.label||p.key||"Gerät").split(",")[0].trim();
  }
  style(){return [
    ":host{display:block;min-height:100%;color:var(--primary-text-color);background:var(--primary-background-color);font-family:Roboto,sans-serif}",
    "*{box-sizing:border-box}.page{max-width:1550px;margin:auto;padding:22px}.top{display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin-bottom:18px}",
    "h1{font-size:28px;margin:0 0 4px}h2,h3{margin-top:0}.sub,.muted{color:var(--secondary-text-color)}",
    ".actions,.tabs,.filters{display:flex;gap:8px;align-items:center;flex-wrap:wrap}button,a.btn,select,input,textarea{font:inherit;border:1px solid var(--divider-color);border-radius:10px;background:var(--card-background-color);color:var(--primary-text-color)}",
    "button,a.btn{padding:10px 14px;cursor:pointer;text-decoration:none}button.primary{background:var(--primary-color);color:white;border-color:var(--primary-color)}button.danger{color:var(--error-color)}button:disabled{opacity:.5;cursor:default}",
    "select,input,textarea{padding:10px 12px;min-height:42px}textarea{width:100%;min-height:240px;font-family:monospace}.tabs{border-bottom:1px solid var(--divider-color);gap:0;margin-bottom:18px}.tab{border:0;border-radius:0;background:transparent;border-bottom:3px solid transparent}.tab.active{border-bottom-color:var(--primary-color);color:var(--primary-color);font-weight:600}",
    ".card,.stat,.profile{background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:14px}.card{padding:18px;margin-bottom:14px}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:16px}.stat{padding:16px}.big{font-size:26px;font-weight:700}.small{color:var(--secondary-text-color);font-size:13px}",
    "table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px 8px;border-bottom:1px solid var(--divider-color);vertical-align:middle}th{font-size:12px;color:var(--secondary-text-color);text-transform:uppercase}.right{text-align:right}.scroll{overflow:auto}",
    ".mono{font-family:monospace}.badge{display:inline-block;padding:4px 8px;border-radius:999px;background:var(--secondary-background-color);font-size:12px}.warn{color:var(--warning-color,#e18b00)}.empty{text-align:center;padding:38px;color:var(--secondary-text-color)}",
    ".catalog{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}.profile{padding:15px}.profile h3{font-size:16px;margin:0 0 7px}.meta{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}.msg{padding:11px 14px;border-radius:10px;background:var(--secondary-background-color);margin-bottom:14px}.category-section{margin:0 0 24px}.category-head{display:flex;align-items:center;justify-content:space-between;margin:4px 2px 10px}.category-head h2{font-size:19px;margin:0}.category-count{color:var(--secondary-text-color);font-size:13px}",
    ".modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;padding:18px;z-index:10}.modal{width:min(760px,100%);max-height:92vh;overflow:auto;background:var(--card-background-color);border-radius:16px;padding:22px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}label{display:flex;flex-direction:column;gap:6px;color:var(--secondary-text-color);font-size:13px}.full{grid-column:1/-1}.footer{display:flex;justify-content:flex-end;gap:8px;margin-top:20px}",
    ".last,.learn-event{padding:10px 12px;border-radius:10px;background:var(--secondary-background-color);display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px}.learn-live{border:2px solid var(--primary-color)}.import-drop{border:2px dashed var(--divider-color);padding:18px;border-radius:12px;text-align:center}",
    ".split{display:grid;grid-template-columns:1fr 1fr;gap:14px}.preview-select{min-width:260px;max-width:500px}.tiny{font-size:12px}.green{color:var(--success-color,#2e9d55)}",
    "@media(max-width:800px){.page{padding:12px}.grid,.split{grid-template-columns:1fr}h1{font-size:23px}.right{white-space:nowrap}}"
  ].join("")}
  render(){var e=this.entry(),entries=this.data?.entries||[],devices=e?.devices||[];var h="<style>"+this.style()+"</style><div class='page'>";
    h+="<div class='top'><div><h1>ELTAKO Gerätekonfiguration</h1><div class='sub'>EEDTOY direkt in Home Assistant · "+this.esc(this.data?.beta||"0.2.0-beta.4")+" · Katalog "+this.esc(this.data?.catalog?.source_version||"?")+"</div></div><div class='actions'>";
    if(entries.length){h+="<select id='entry'>";entries.forEach(x=>h+="<option value='"+this.esc(x.entry_id)+"'"+(x.entry_id===this.entryId?" selected":"")+">"+this.esc(x.title||x.gateway_type||"ELTAKO")+" · "+this.esc(x.port||"")+"</option>");h+="</select>"}
    h+="<a class='btn' href='/eltako-diagnostics'>Funk-/Bus-Diagnose</a><button id='refresh'>Aktualisieren</button></div></div>";
    if(this.message)h+="<div class='msg'>"+this.esc(this.message)+"</div>";
    if(this.loading&&!this.data)h+="<div class='card empty'>Konfiguration wird geladen …</div>";
    if(!this.loading&&!entries.length)h+="<div class='card empty'>Noch kein ELTAKO-Gateway eingerichtet.</div>";
    if(e){h+="<div class='stats'><div class='stat'><div class='big'>"+devices.length+"</div><div class='small'>konfigurierte Geräte</div></div><div class='stat'><div class='big'>"+this.catalog().length+"</div><div class='small'>EEDTOY-Profile</div></div><div class='stat'><div class='big'>"+this.esc(e.gateway_type||"auto")+"</div><div class='small'>Gateway</div></div><div class='stat'><div class='big'>"+(this.data?.areas?.length||0)+"</div><div class='small'>HA-Räume</div></div></div>";
      h+="<div class='tabs'>"+this.tabButton("devices","Geräte")+this.tabButton("learn","Lernmodus")+this.tabButton("catalog","Gerätekatalog")+this.tabButton("import","Import")+this.tabButton("export","Export")+"</div>";
      if(this.tab==="devices")h+=this.renderDevices(e);if(this.tab==="learn")h+=this.renderLearn(e);if(this.tab==="catalog")h+=this.renderCatalog();if(this.tab==="import")h+=this.renderImport();if(this.tab==="export")h+=this.renderExport();
    }h+="</div>";if(this.editing)h+=this.renderModal(e);if(this.profileEditing)h+=this.renderProfileModal();this.shadowRoot.innerHTML=h;this.bind()}
  tabButton(id,label){return "<button class='tab "+(this.tab===id?"active":"")+"' data-tab='"+id+"'>"+label+"</button>"}
  renderDevices(e){var ds=e.devices||[],h="<div class='card'><div class='top' style='margin-bottom:10px'><div><strong>Geräte an diesem Gateway</strong><div class='muted'>Direkt bearbeiten, einlernen und programmieren – ohne externen YAML-Editor.</div></div><button class='primary' id='add'>+ Gerät hinzufügen</button></div>";
    if(e.last_telegram?.sender_id)h+="<div class='last'><div><span class='muted'>Zuletzt empfangen:</span> <span class='mono'>"+this.esc(e.last_telegram.sender_id)+"</span> <span class='badge'>"+this.esc(e.last_telegram.eep||"EEP unbekannt")+"</span></div><button id='add-last'>Als Gerät übernehmen</button></div>";
    if(!ds.length)return h+"<div class='empty'>Noch keine Geräte konfiguriert.</div></div>";
    h+="<div class='scroll'><table><thead><tr><th>Name</th><th>ID</th><th>EEP</th><th>Typ</th><th>Raum</th><th></th></tr></thead><tbody>";
    ds.forEach((d,i)=>{
      var program=this.canProgram(d)?("<button class='primary' data-program='"+i+"'>"+(this.isSeries14(d)?"Sender programmieren":"Einlernen")+"</button> "):"";
      h+="<tr><td><strong>"+this.esc(d.name||"ELTAKO Gerät")+"</strong><div class='muted'>"+this.esc(d.platform||"")+(d.sender_id?" · Sender "+this.esc(d.sender_id):"")+"</div></td><td class='mono'>"+this.esc(d.id||"")+"</td><td><span class='badge'>"+this.esc(d.eep||"")+"</span></td><td>"+this.esc(d.device_type||d.profile_key||"")+"</td><td>"+this.esc(d.area||"—")+"</td><td class='right'>"+program+"<button data-edit='"+i+"'>Bearbeiten</button> <button class='danger' data-delete='"+i+"'>Löschen</button></td></tr>";
    });
    return h+"</tbody></table></div></div>"}
  renderLearn(e){var h="<div class='card "+(this.learning?"learn-live":"")+"'><div class='top'><div><h3>Lernmodus</h3><div class='muted'>Telegramme des ausgewählten Gateways live empfangen und als neues Gerät übernehmen.</div></div><div class='actions'><button class='primary' id='learn-start' "+(this.learning?"disabled":"")+">Lernmodus starten</button><button id='learn-stop' "+(!this.learning?"disabled":"")+">Stoppen</button><button id='learn-clear'>Liste leeren</button></div></div>";
    h+="<p class='tiny muted'>Jetzt Sensor/Taster betätigen oder Teach-in/LRN auslösen. Eigene Gateway-Statusmeldungen werden ignoriert. Bei unbekanntem EEP schlägt die Oberfläche passende RORG-Profile vor.</p>";
    if(!this.learnEvents.length)return h+"<div class='empty'>Noch kein Telegramm im Lernmodus empfangen.</div></div>";
    this.learnEvents.slice().reverse().forEach((x,rev)=>{var idx=this.learnEvents.length-1-rev,p=x.profile_suggestions||[],best=p[0]||"";h+="<div class='learn-event'><div><strong class='mono'>"+this.esc(x.physical_sender_id||x.sender_id)+"</strong> <span class='badge'>"+this.esc(x.eep||x.decoded?.detected_eep||this.orgLabel(x.decoded?.org))+"</span><div class='tiny muted'>"+this.esc(x.decoded?.telegram_type||"Telegramm")+" · Vorschläge: "+this.esc(p.slice(0,4).map(k=>this.profile(k)?.device_type||k).join(", ")||"manuell auswählen")+"</div></div><button data-learn-add='"+idx+"' data-best='"+this.esc(best)+"'>Gerät anlegen</button></div>"});return h+"</div>"}
  orgLabel(org){var n=Number(org);return n===5?"F6/RPS":n===6?"A5/4BS":n===7?"D5/1BS":"EEP unbekannt"}
  renderCatalog(){
    var list=this.filteredCatalog(),h="<div class='card'><div class='top' style='margin-bottom:10px'><div><strong>Gerätekatalog</strong><div class='muted'>Mitgelieferte und eigene updatefeste Geräteprofile.</div></div><button class='primary' id='new-profile'>+ Eigenes Geräteprofil</button></div><div class='filters'><input id='search' style='flex:1;min-width:240px' placeholder='Gerät, EEP, Kategorie oder Typ suchen …' value='"+this.esc(this.search)+"'><select id='group'><option value=''>Alle Kategorien</option>";
    this.categories().forEach(g=>h+="<option value='"+this.esc(g)+"'"+(g===this.group?" selected":"")+">"+this.esc(g)+"</option>");
    h+="</select><span class='muted'>"+list.length+" Profile</span></div></div>";
    var categories=this.categoryOrder().filter(cat=>list.some(p=>this.categoryForGroup(p.group)===cat));
    categories.forEach(cat=>{
      var items=list.filter(p=>this.categoryForGroup(p.group)===cat);
      h+="<section class='category-section'><div class='category-head'><h2>"+this.esc(cat)+"</h2><span class='category-count'>"+items.length+" Geräteprofile</span></div><div class='catalog'>";
      items.forEach(p=>{
          h+="<div class='profile'><h3>"+this.esc(this.profileShortName(p))+"</h3><div class='muted'>"+this.esc(p.group||"")+"</div><div class='meta'><span class='badge'>"+this.esc(p.eep_out||"")+"</span><span class='badge'>"+this.esc(p.platform||"")+"</span>"+(p.needs_sender?"<span class='badge'>Sender-ID</span>":"")+(p.custom?"<span class='badge custom-badge'>Eigenes Profil</span>":"")+"</div><div class='profile-actions'><button class='primary' data-profile='"+this.esc(p.key)+"'>Hinzufügen</button><button data-clone-profile='"+this.esc(p.key)+"'>Duplizieren</button>"+(p.custom?"<button data-edit-profile='"+this.esc(p.key)+"'>Bearbeiten</button><button class='danger' data-delete-profile='"+this.esc(p.key)+"'>Löschen</button>":"")+"</div></div>";
        });
      h+="</div></section>";
    });
    if(!categories.length)h+="<div class='card empty'>Keine passenden Geräteprofile gefunden.</div>";
    return h;
  }
  renderImport(){var p=this.preview,h="<div class='card'><h3>Konfiguration importieren</h3><p class='muted'>Unterstützt: PCT14 XML, MiniSafe2 E-Mail/TXT/JSON und EEDTOY/Home-Assistant-YAML. Das Format kann automatisch erkannt werden.</p><div class='split'><label>Format<select id='import-format'><option value='auto'>Automatisch erkennen</option><option value='pct14'>PCT14 XML</option><option value='minisafe2'>MiniSafe2</option><option value='eedtoy_yaml'>EEDTOY YAML</option></select></label><label>Datei<input id='import-file' type='file' accept='.xml,.txt,.json,.yaml,.yml'></label></div><label style='margin-top:12px'>Oder Inhalt einfügen<textarea id='import-text' placeholder='PCT14 XML, MiniSafe2-Konfiguration oder EEDTOY YAML …'>"+this.esc(this.importText)+"</textarea></label><div class='actions' style='margin-top:10px'><button class='primary' id='import-preview'>Import prüfen</button></div></div>";
    if(!p)return h;
    h+="<div class='card'><div class='top'><div><h3>Import-Vorschau</h3><div class='muted'>Format: "+this.esc(p.format)+" · "+(p.rows?.length||0)+" Geräte"+(p.summary?.base_id?" · Base-ID "+this.esc(p.summary.base_id):"")+"</div></div><label style='flex-direction:row;align-items:center'><input id='replace-import' type='checkbox' "+(this.replaceImport?"checked":"")+"> Vorhandene Geräte ersetzen</label></div>";
    if(p.unsupported?.length)h+="<div class='msg warn'><strong>Nicht automatisch zugeordnet:</strong> "+this.esc(p.unsupported.join(", "))+"</div>";
    h+="<div class='scroll'><table><thead><tr><th>✓</th><th>Name / ID</th><th>Profil</th><th>Raum</th><th>Hinweis</th></tr></thead><tbody>";
    (p.rows||[]).forEach((row,i)=>{h+="<tr><td><input type='checkbox' data-row-check='"+i+"' "+(row.selected!==false?"checked":"")+"></td><td><strong>"+this.esc(row.name||"Gerät")+"</strong><div><input class='mono' data-row-id='"+i+"' value='"+this.esc(row.id||"")+"' placeholder='EnOcean-ID' style='width:150px;min-height:34px;padding:6px'></div></td><td><select class='preview-select' data-row-profile='"+i+"'><option value=''>Profil auswählen …</option>";this.catalog().forEach(pro=>h+="<option value='"+this.esc(pro.key)+"'"+(pro.key===row.profile_key?" selected":"")+">"+this.esc(this.profileShortName(pro))+"</option>");h+="</select></td><td><input data-row-area='"+i+"' value='"+this.esc(row.area||"")+"' placeholder='"+this.esc(row.area_hint||"Raum")+"'></td><td class='"+(row.warning?"warn":"green")+"'>"+this.esc(row.warning||"bereit")+"</td></tr>"});h+="</tbody></table></div><div class='footer'><button id='import-cancel'>Vorschau verwerfen</button><button class='primary' id='import-apply'>Ausgewählte Geräte übernehmen</button></div></div>";return h}
  renderExport(){return "<div class='card'><h3>Backup / Kompatibilität</h3><p class='muted'>Die direkte HA-Konfiguration kann weiterhin als EEDTOY-kompatibles YAML gesichert werden.</p><div class='actions'><button class='primary' id='export'>YAML erzeugen</button><button id='copy'>YAML kopieren</button></div><textarea id='yaml' readonly placeholder='Hier erscheint der Export …'></textarea></div>"}
  renderModal(e){var d=this.editing||{},p=this.profile(d.profile_key),h="<div class='modal-bg' id='backdrop'><div class='modal'><h2>"+(d.index==null?"Gerät hinzufügen":"Gerät bearbeiten")+"</h2><div class='grid'><label class='full'>Geräteprofil<select id='f-profile'><option value=''>Profil auswählen …</option>";this.catalog().forEach(x=>h+="<option value='"+this.esc(x.key)+"'"+(x.key===d.profile_key?" selected":"")+">"+this.esc(this.profileShortName(x))+"</option>");h+="</select></label><label>Name<input id='f-name' value='"+this.esc(d.name||p?.device_type||"")+"'></label><label>EnOcean-ID<div class='actions'><input style='flex:1' class='mono' id='f-id' value='"+this.esc(d.id||"")+"' placeholder='FE-FE-AD-C8'>"+(e?.last_telegram?.sender_id?"<button id='use-last'>Letzte ID</button>":"")+"</div></label><label>Raum<input id='f-area' list='areas' value='"+this.esc(d.area||"")+"'><datalist id='areas'>";(this.data?.areas||[]).forEach(a=>h+="<option value='"+this.esc(a.name)+"'></option>");h+="</datalist></label><label>Device Class<select id='f-class'><option value=''>Automatisch / keine</option>";(p?.device_classes||[]).forEach(dc=>h+="<option value='"+this.esc(dc)+"'"+(dc===(d.device_class||p?.default_dc)?" selected":"")+">"+this.esc(dc)+"</option>");h+="</select></label>";if(p?.needs_sender)h+="<label>Sender-ID<input class='mono' id='f-sender' value='"+this.esc(d.sender_id||"")+"' placeholder='FF-xx-xx-xx'></label><label>Sender-EEP<input id='f-sender-eep' value='"+this.esc(d.sender_eep||p.sender_eep||"")+"' readonly></label>";h+="<div class='full card' style='margin:0;padding:12px'><strong>"+this.esc(p?(p.label||p.device_type):"Noch kein Profil gewählt")+"</strong><div class='muted'>EEP: "+this.esc(p?.eep_out||"—")+" · Plattform: "+this.esc(p?.platform||"—")+(p?.teach_in_telegram?" · Teach-in: "+this.esc(p.teach_in_telegram):"")+"</div></div></div><div class='footer'><button id='cancel'>Abbrechen</button><button class='primary' id='save'>Speichern</button></div></div></div>";return h}
  renderProfileModal(){
    var p=this.profileEditing||{},isEdit=!!p.key;
    var groups=["Taster / Schalter","Kontakt","Bewegungsmelder","Rauch / Hitze","Wasser","Temperatur / Feuchte","Luftqualität","Raumregler / Klima","Heizung / Stellantrieb","Lüftung","Zähler","Wetterstation","Licht / Dimmer","Licht / RGBW","Licht / Relais","Jalousie / Rollladen","Funk-Modul","Sonstige"];
    var h="<div class='modal-bg' id='profile-backdrop'><div class='modal'><h2>"+(isEdit?"Eigenes Geräteprofil bearbeiten":"Eigenes Geräteprofil anlegen")+"</h2><div class='grid'>";
    h+="<label>Kurzname<input id='p-device-type' value='"+this.esc(p.device_type||"")+"' placeholder='z. B. FWS81'></label>";
    h+="<label>EEP<input id='p-eep' value='"+this.esc(p.eep_out||"")+"' placeholder='F6-05-01'></label>";
    h+="<label>Kategorie<select id='p-group'>";groups.forEach(g=>h+="<option value='"+this.esc(g)+"'"+(g===(p.group||"Sonstige")?" selected":"")+">"+this.esc(g)+"</option>");h+="</select></label>";
    h+="<label>Plattform<select id='p-platform'>";["binary_sensor","sensor","light","switch","cover","fan","climate"].forEach(v=>h+="<option value='"+v+"'"+(v===(p.platform||"sensor")?" selected":"")+">"+v+"</option>");h+="</select></label>";
    h+="<label>Device Class<input id='p-default-dc' value='"+this.esc(p.default_dc||"")+"' placeholder='z. B. moisture'></label>";
    h+="<label>Device Family<input id='p-family' value='"+this.esc(p.device_family||"")+"' placeholder='optional'></label>";
    h+="<label style='flex-direction:row;align-items:center;margin-top:24px'><input id='p-needs-sender' type='checkbox' "+(p.needs_sender?"checked":"")+"> Sender-ID erforderlich</label>";
    h+="<label>Sender-EEP<input id='p-sender-eep' value='"+this.esc(p.sender_eep||"")+"' placeholder='A5-38-08'></label>";
    h+="<label class='full'>Teach-in-Telegramm<input id='p-teach' value='"+this.esc(p.teach_in_telegram||"")+"' placeholder='optional, z. B. E0-40-0D-80'></label>";
    h+="</div><div class='footer'><button id='profile-cancel'>Abbrechen</button><button class='primary' id='profile-save'>Profil speichern</button></div></div></div>";
    return h;
  }
  openNewProfile(source){
    var p=source?Object.assign({},source):{};
    delete p.key;p.custom=true;
    p.label=p.device_type||p.label||"";
    this.profileEditing=p;this.render();
  }
  openEditProfile(key){var p=this.profile(key);if(p&&p.custom){this.profileEditing=Object.assign({},p);this.render()}}
  async saveProfile(){
    var p=this.profileEditing||{},payload={
      label:this.value("p-device-type"),device_type:this.value("p-device-type"),
      eep_out:this.value("p-eep"),group:this.value("p-group"),
      platform:this.value("p-platform"),default_dc:this.value("p-default-dc"),
      device_family:this.value("p-family"),
      needs_sender:!!this.shadowRoot.getElementById("p-needs-sender")?.checked,
      sender_eep:this.value("p-sender-eep"),teach_in_telegram:this.value("p-teach")
    };
    try{
      await this._hass.callWS({type:DOMAIN+"/manager/save_profile",profile:payload,...(p.key?{key:p.key}:{})});
      this.profileEditing=null;this.message="Eigenes Geräteprofil gespeichert.";await this.load(true);
    }catch(err){this.message="Profil konnte nicht gespeichert werden: "+(err?.message||err);this.render()}
  }
  async deleteProfile(key){
    var p=this.profile(key);if(!p||!p.custom)return;
    if(!confirm("Eigenes Geräteprofil „"+this.profileShortName(p)+"“ wirklich löschen?"))return;
    try{await this._hass.callWS({type:DOMAIN+"/manager/delete_profile",key});this.message="Eigenes Geräteprofil gelöscht.";await this.load(true)}
    catch(err){this.message="Profil konnte nicht gelöscht werden: "+(err?.message||err);this.render()}
  }
  openAdd(key,id,extra){var p=this.profile(key||"");this.editing=Object.assign({index:null,profile_key:key||"",id:id||"",name:p?.device_type||"",area:"",device_class:p?.default_dc||"",sender_id:"",sender_eep:p?.sender_eep||""},extra||{});this.render()}
  openEdit(i){var d=this.entry()?.devices?.[i];if(d){this.editing=Object.assign({},d,{index:i,profile_key:d.profile_key||d.raw?.profile_key||""});this.render()}}
  value(id){return this.shadowRoot.getElementById(id)?.value||""}
  async save(){if(!this.editing)return;var profile=this.value("f-profile");if(!profile){this.message="Bitte zuerst ein Geräteprofil auswählen.";this.render();return}var req={type:DOMAIN+"/manager/save_device",entry_id:this.entryId,device:{profile_key:profile,name:this.value("f-name"),id:this.value("f-id"),area:this.value("f-area"),device_class:this.value("f-class"),sender_id:this.value("f-sender"),sender_eep:this.value("f-sender-eep")}};if(this.editing.index!=null)req.index=this.editing.index;try{await this._hass.callWS(req);this.editing=null;this.message="Gerät gespeichert. Integration wird neu geladen.";await new Promise(r=>setTimeout(r,700));await this.load(true)}catch(err){this.message=err?.message||String(err);this.render()}}
  async remove(i){var d=this.entry()?.devices?.[i];if(!d||!confirm("„"+(d.name||d.id)+"“ wirklich löschen?"))return;try{await this._hass.callWS({type:DOMAIN+"/manager/delete_device",entry_id:this.entryId,index:i});this.message="Gerät gelöscht. Integration wird neu geladen.";await new Promise(r=>setTimeout(r,700));await this.load(true)}catch(err){this.message=err?.message||String(err);this.render()}}
  async exportYaml(){try{var x=await this._hass.callWS({type:DOMAIN+"/manager/export_yaml",entry_id:this.entryId}),b=this.shadowRoot.getElementById("yaml");if(b)b.value=x.yaml||""}catch(err){this.message=err?.message||String(err);this.render()}}
  async startLearning(){if(this.learning||!this._hass)return;try{this.learnUnsub=await this._hass.connection.subscribeMessage(ev=>{this.learnEvents.push(ev);if(this.learnEvents.length>50)this.learnEvents.shift();this.render()}, {type:DOMAIN+"/manager/learn",entry_id:this.entryId});this.learning=true;this.message="Lernmodus aktiv – Gerät jetzt betätigen.";this.render()}catch(err){this.message="Lernmodus konnte nicht gestartet werden: "+(err?.message||err);this.render()}}
  async stopLearning(){if(this.learnUnsub){try{await this.learnUnsub()}catch(_e){}this.learnUnsub=null}this.learning=false;if(this.shadowRoot)this.render()}
  async previewImport(){this.importText=this.value("import-text");this.importFormat=this.value("import-format")||"auto";if(!this.importText.trim()){this.message="Bitte eine Datei wählen oder Importtext einfügen.";this.render();return}try{this.preview=await this._hass.callWS({type:DOMAIN+"/manager/import_preview",text:this.importText,filename:this.importFilename,format:this.importFormat});this.message="Import geprüft. Bitte Zuordnungen kontrollieren.";this.render()}catch(err){this.message="Importfehler: "+(err?.message||err);this.render()}}
  syncPreviewInputs(){if(!this.preview)return;this.preview.rows.forEach((row,i)=>{var c=this.shadowRoot.querySelector("[data-row-check='"+i+"']"),id=this.shadowRoot.querySelector("[data-row-id='"+i+"']"),p=this.shadowRoot.querySelector("[data-row-profile='"+i+"']"),a=this.shadowRoot.querySelector("[data-row-area='"+i+"']");if(c)row.selected=c.checked;if(id)row.id=id.value;if(p)row.profile_key=p.value;if(a)row.area=a.value});this.replaceImport=!!this.shadowRoot.getElementById("replace-import")?.checked}
  async applyImport(){this.syncPreviewInputs();try{var res=await this._hass.callWS({type:DOMAIN+"/manager/apply_import",entry_id:this.entryId,rows:this.preview.rows,replace:this.replaceImport});this.preview=null;this.message=res.added+" Gerät(e) übernommen, "+res.skipped+" übersprungen."+(res.errors?.length?" "+res.errors.join(" | "):"");await new Promise(r=>setTimeout(r,800));this.tab="devices";await this.load(true)}catch(err){this.message="Übernahme fehlgeschlagen: "+(err?.message||err);this.render()}}
  async programDevice(i){
    var d=this.entry()?.devices?.[i];if(!d)return;
    var series14=this.isSeries14(d);
    var text=series14
      ?"Sender-ID "+(d.sender_id||"")+" jetzt in "+(d.name||d.device_type||"Series-14-Aktor")+" schreiben?\n\nDafür wird ein aktives FAM14/FGW14-USB verwendet und der RS485-Bus kurz exklusiv übernommen."
      :(d.name||d.device_type||"Aktor")+" jetzt in den physischen Einlernmodus bringen.\n\nDanach OK drücken – Home Assistant sendet das Lerntelegramm mit Sender-ID "+(d.sender_id||"")+".";
    if(!confirm(text))return;
    this.message=series14?"Sender-ID wird in den Series-14-Aktor geschrieben …":"Lerntelegramm wird gesendet …";this.render();
    try{
      var res=await this._hass.callWS({type:DOMAIN+"/manager/program_device",entry_id:this.entryId,index:i});
      if(res.mode==="series14"){
        var counts=res.result?.counts||{};
        this.message="Series-14-Programmierung abgeschlossen: "+(counts.updated||0)+" geschrieben, "+(counts.exists||0)+" bereits vorhanden, "+(counts.error||0)+" Fehler.";
      }else{
        this.message=res.command==="arm_fks_hora_teach_in"
          ?"Einlernen vorbereitet. Das Ventil muss jetzt sein bidirektionales Lerntelegramm senden."
          :"Lerntelegramm wurde mit Sender-ID "+(res.sender_id||d.sender_id||"")+" gesendet.";
      }
    }catch(err){this.message="Einlernen/Programmieren fehlgeschlagen: "+(err?.message||err)}
    this.render();
  }
  bind(){var r=this.shadowRoot,x;r.getElementById("refresh")?.addEventListener("click",()=>this.load());r.getElementById("entry")?.addEventListener("change",e=>{this.stopLearning();this.entryId=e.target.value;this.render()});r.querySelectorAll("[data-tab]").forEach(b=>b.onclick=()=>{this.tab=b.dataset.tab;this.render()});r.getElementById("add")?.addEventListener("click",()=>this.openAdd());r.getElementById("add-last")?.addEventListener("click",()=>this.openAdd("",this.entry()?.last_telegram?.sender_id||""));r.querySelectorAll("[data-edit]").forEach(b=>b.onclick=()=>this.openEdit(Number(b.dataset.edit)));r.querySelectorAll("[data-delete]").forEach(b=>b.onclick=()=>this.remove(Number(b.dataset.delete)));r.querySelectorAll("[data-program]").forEach(b=>b.onclick=()=>this.programDevice(Number(b.dataset.program)));r.querySelectorAll("[data-profile]").forEach(b=>b.onclick=()=>this.openAdd(b.dataset.profile));r.getElementById("new-profile")?.addEventListener("click",()=>this.openNewProfile());r.querySelectorAll("[data-clone-profile]").forEach(b=>b.onclick=()=>this.openNewProfile(this.profile(b.dataset.cloneProfile)));r.querySelectorAll("[data-edit-profile]").forEach(b=>b.onclick=()=>this.openEditProfile(b.dataset.editProfile));r.querySelectorAll("[data-delete-profile]").forEach(b=>b.onclick=()=>this.deleteProfile(b.dataset.deleteProfile));
    x=r.getElementById("search");if(x)x.onchange=e=>{this.search=e.target.value;this.render()};x=r.getElementById("group");if(x)x.onchange=e=>{this.group=e.target.value;this.render()};
    r.getElementById("learn-start")?.addEventListener("click",()=>this.startLearning());r.getElementById("learn-stop")?.addEventListener("click",()=>this.stopLearning());r.getElementById("learn-clear")?.addEventListener("click",()=>{this.learnEvents=[];this.render()});r.querySelectorAll("[data-learn-add]").forEach(b=>b.onclick=()=>{var ev=this.learnEvents[Number(b.dataset.learnAdd)],best=b.dataset.best||"";this.openAdd(best,ev?.physical_sender_id||ev?.sender_id||"")});
    r.getElementById("import-file")?.addEventListener("change",async e=>{var f=e.target.files?.[0];if(f){this.importFilename=f.name;this.importText=await f.text();this.render()}});r.getElementById("import-preview")?.addEventListener("click",()=>this.previewImport());r.getElementById("import-cancel")?.addEventListener("click",()=>{this.preview=null;this.render()});r.getElementById("import-apply")?.addEventListener("click",()=>this.applyImport());
    r.getElementById("profile-cancel")?.addEventListener("click",()=>{this.profileEditing=null;this.render()});r.getElementById("profile-backdrop")?.addEventListener("click",e=>{if(e.target.id==="profile-backdrop"){this.profileEditing=null;this.render()}});r.getElementById("profile-save")?.addEventListener("click",()=>this.saveProfile());r.getElementById("cancel")?.addEventListener("click",()=>{this.editing=null;this.render()});r.getElementById("backdrop")?.addEventListener("click",e=>{if(e.target.id==="backdrop"){this.editing=null;this.render()}});r.getElementById("f-profile")?.addEventListener("change",e=>{var old=this.editing||{},p=this.profile(e.target.value);this.editing=Object.assign({},old,{profile_key:e.target.value,device_class:p?.default_dc||"",sender_eep:p?.sender_eep||"",name:old.name||p?.device_type||""});this.render()});r.getElementById("use-last")?.addEventListener("click",()=>{var f=r.getElementById("f-id");if(f)f.value=this.entry()?.last_telegram?.sender_id||""});r.getElementById("save")?.addEventListener("click",()=>this.save());r.getElementById("export")?.addEventListener("click",()=>this.exportYaml());r.getElementById("copy")?.addEventListener("click",async()=>{var y=r.getElementById("yaml");if(y?.value){await navigator.clipboard.writeText(y.value);this.message="YAML kopiert.";this.render()}});
  }
}
customElements.define("eltako-manager-panel",EltakoManagerPanel);
