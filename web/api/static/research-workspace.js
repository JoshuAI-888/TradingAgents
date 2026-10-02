/* Research workspace: presentation and navigation over the existing screener.
   Existing preset membership, columns, exports and KLine engine remain authoritative. */
function researchExportJSON(value) {
 return JSON.stringify(value,(_key,v)=>typeof v==='number' && !Number.isFinite(v)?{export_unavailable:'nonfinite_number',source_value:String(v)}:v);
}
function researchCSVCell(value) {
 let s=value==null?'':typeof value==='object'?researchExportJSON(value):typeof value==='number' && !Number.isFinite(value)?researchExportJSON({export_unavailable:'nonfinite_number',source_value:String(value)}):String(value);
 if(typeof value==='string' && (/^\s*[=+@-]/.test(s) || /^[\t\r\n]/.test(s)))s="'"+s;
 return /[",\r\n]/.test(s)?'"'+s.replaceAll('"','""')+'"':s;
}
function researchExportRow(row,columns) {
 const result={...row},issues=[];
 for(const field of columns){const value=row[field],kind=SCR_COLS[field]?.[1];
  if(kind==='num' || RESEARCH_CURRENCY_FIELDS.has(field)){
   if(typeof value==='number' && Number.isFinite(value))continue;
   result[field]='Unavailable';if(value!=null)issues.push({field,reason:'invalid_numeric',source_value:value});
  }else if(kind==='bool'){
   result[field]=researchDisplayField(field,value);if(value!=null && result[field]==='Unavailable')issues.push({field,reason:'invalid_flag',source_value:value});
  }
 }
 result.export_value_issues=issues;return result;
}
function researchXMLCell(value) {
 const number=typeof value==='number' && Number.isFinite(value);
 const text=value==null?'':typeof value==='object'?researchExportJSON(value):typeof value==='number' && !Number.isFinite(value)?researchExportJSON({export_unavailable:'nonfinite_number',source_value:String(value)}):String(value);
 const safe=text.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0')).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
 return '<Cell><Data ss:Type="'+(number?'Number':'String')+'">'+safe+'</Data></Cell>';
}
function researchRows() { return scrClientRows() || []; }
function researchVisibleRows() { return window.__homeCtx?.scr?.rows || []; }
function researchKey(r) { return r.code || r.symbol; }
function researchSelect(i, on) {
  const row = researchVisibleRows()[i]; if (!row) return;
  const set = new Set(window.__researchSelected || []);
  on ? set.add(researchKey(row)) : set.delete(researchKey(row));
  window.__researchSelected = [...set]; researchSelectionMount();
}
function researchRemoveSelection(code) {
 window.__researchSelected=(window.__researchSelected || []).filter(k=>k!==code);
 researchSelectionMount();
}
function researchSelectedRows(rows, selected) {
 const keys=new Set(selected || []);
 return rows.filter(r=>keys.has(researchKey(r)));
}
function researchSelectionMount() {
 const el=document.getElementById('research-selection');if(!el)return;
 const selected=window.__researchSelected || [],rows=researchRows();
 const byKey=new Map(rows.map(r=>[researchKey(r),r]));
 el.innerHTML=`<span role="status">${selected.length} selected</span><div class="selection-chips">${selected.map(code=>`<button class="btn ghost selection-chip" aria-label="Remove ${esc(byKey.get(code)?.symbol || code)} from selection" onclick="researchRemoveSelection(${esc(JSON.stringify(code))})">${esc(byKey.get(code)?.symbol || code)} <small>Remove</small></button>`).join('')}</div><button class="btn primary" onclick="researchCompare()" ${selected.length<2 || selected.length>4?'disabled':''}>Compare selected (${selected.length})</button><details class="research-export"><summary class="btn ghost">Export selected</summary><div class="export-options"><button class="btn ghost" onclick="scrExport('csv','selected')">CSV · selected stocks</button><button class="btn ghost" onclick="scrExport('xls','selected')">Excel · selected stocks</button><small>Current loaded cohort and sort · Excel-compatible .xls</small></div></details><button class="btn ghost" onclick="window.__researchSelected=[];researchSelectionMount()">Clear selection</button><span class="faint">Compare 2–4; export any selection</span>`;
 el.hidden=!selected.length;
 researchExploreSelectionMount();
 document.querySelectorAll('.scr-table tr,.mobile-stock,.explore-linked tr').forEach(tr=>{
  const checkbox=tr.querySelector('input[type=checkbox]');if(!checkbox)return;
  const index=Number(checkbox.dataset.researchIndex);const row=checkbox.dataset.researchCode?byKey.get(checkbox.dataset.researchCode):researchVisibleRows()[index];
  const checked=!!row && selected.includes(researchKey(row));checkbox.checked=checked;tr.classList.toggle('research-selected',checked);
 });
}
function researchOriginPersist() {
 const ctx=window.__researchContext;if(!ctx)return;
 const owner=ctx.kind==='shortlists' || ctx.kind==='changes' && ctx.private?window.__researchSession?.user.id:null;
 if((ctx.kind==='shortlists' || ctx.kind==='changes' && ctx.private) && !owner)return;
 try{sessionStorage.setItem('researchOriginV1',JSON.stringify({version:1,owner,context:ctx}));}catch(e){}
}
async function researchOriginRestore() {
 let saved;try{saved=JSON.parse(sessionStorage.getItem('researchOriginV1'));}catch(e){return;}
 if(saved?.version!==1 || !saved.context || typeof saved.context!=='object')return;
 const ctx=saved.context;
 if(ctx.kind==='shortlists' || ctx.kind==='changes' && ctx.private){
  await window.__researchAccountReady;
  if(!saved.owner || saved.owner!==window.__researchSession?.user.id)return;
 }else if(ctx.kind!=null && ctx.kind!=='changes' || saved.owner || !ctx.state || typeof ctx.state!=='object' || Array.isArray(ctx.state))return;
 if(!Array.isArray(ctx.rows) || ctx.rows.length>(ctx.kind==='changes'?40000:20000) || !ctx.rows.every(r=>r && typeof r.code==='string' && /^(US|HK)\.[A-Za-z0-9._-]{1,32}$/.test(r.code)))return;
 const codes=new Set(ctx.rows.map(r=>r.code));
 if(codes.size!==ctx.rows.length || !Array.isArray(ctx.selected) || ctx.selected.length>codes.size || new Set(ctx.selected).size!==ctx.selected.length || !ctx.selected.every(k=>typeof k==='string' && codes.has(k)))return;
 if(ctx.kind==='shortlists'){if(!researchListIDValid(ctx.listID))return;ctx.q=typeof ctx.q==='string'?ctx.q.slice(0,80):'';ctx.offset=Number.isSafeInteger(ctx.offset) && ctx.offset>=0 && ctx.offset<=10000000?ctx.offset:0;ctx.review_status=['all','unreviewed','in_review','reviewed'].includes(ctx.review_status)?ctx.review_status:'all';}
 if(ctx.kind==='changes'){
  if(typeof ctx.private!=='boolean' || !ctx.state || typeof ctx.state!=='object' || Array.isArray(ctx.state) || ctx.state.presentation!=='changes')return;
  const change=ctx.changeState,selection=ctx.changeSelection,selectedCodes=new Set(ctx.selected);
  if(!change || typeof change.key!=='string' || !['new','exited','all'].includes(change.status) || typeof change.q!=='string' || change.q.length>100 || ![1,2].includes(change.direction) || !Number.isSafeInteger(change.offset) || change.offset<0 || change.offset>40000 || !Number.isSafeInteger(change.limit) || change.limit<1 || change.limit>500)return;
  if(!selection || typeof selection.key!=='string' || !Array.isArray(selection.rows) || selection.rows.length!==ctx.selected.length || new Set(selection.rows.map(r=>r?.code)).size!==selection.rows.length || !selection.rows.every(r=>r && codes.has(r.code) && selectedCodes.has(r.code)))return;
 }
 if(!Number.isFinite(ctx.scroll) || ctx.scroll<0)return;
 window.__researchContext=ctx;
}
function researchCaptureContext() {
  window.__researchContext = {state:JSON.parse(JSON.stringify(window.__scr)),hash:location.hash,
    scroll:window.scrollY || 0,tableScroll:document.querySelector('.scr-scroll')?.scrollTop || 0,tableScrollLeft:document.querySelector('.scr-scroll')?.scrollLeft || 0,
    rows:researchRows().map(r=>({code:researchKey(r),symbol:r.symbol})),selected:[...(window.__researchSelected || [])]};
  if(window.__scr.presentation==='changes' && window.__changePayload?.comparable){const d=window.__changePayload,sel=researchChangeSelection(d,researchChangeState());window.__researchContext={...window.__researchContext,kind:'changes',private:d.review_scope==='private_capture_pair',changeState:JSON.parse(JSON.stringify(researchChangeState())),changeSelection:JSON.parse(JSON.stringify(sel)),rows:[...new Map([...d.rows,...sel.rows].map(r=>[r.code,{code:r.code,symbol:r.symbol}])).values()],selected:sel.rows.map(r=>r.code)};}
  researchOriginPersist();
}
function researchOpen(code) {
  if (state.page === 'home') researchCaptureContext();
  if(state.page==='shortlists'){researchListOpenStock(code);return;}
  openStock(code);
}
async function researchReturn() {
  const ctx=window.__researchContext;
  if(ctx?.kind==='shortlists'){window.__researchListID=ctx.listID;window.__researchListOffset=ctx.offset;window.__researchListSearch=ctx.q || '';window.__researchListStatus=ctx.review_status || 'all';await showPage('shortlists');window.scrollTo(0,ctx.scroll || 0);return;}
  if(ctx) {window.__scr=JSON.parse(JSON.stringify(ctx.state));if(ctx.kind==='changes'){window.__changeState=JSON.parse(JSON.stringify(ctx.changeState));window.__researchChangeSelection=JSON.parse(JSON.stringify(ctx.changeSelection));}else window.__researchSelected=[...ctx.selected];}
  scrPersist(); await showPage('home');
  window.scrollTo(0,ctx?.scroll || 0);
  const table=document.querySelector('.scr-scroll');if(table){table.scrollTop=ctx?.tableScroll || 0;table.scrollLeft=ctx?.tableScrollLeft || 0;}
}
function researchBreadcrumb() {
  const ctx=window.__researchContext; if(!ctx)return '';
  const index=ctx.rows.findIndex(r=>r.code===stkState().sym || r.symbol===stkState().sym);
  return `<div class="research-breadcrumb"><button class="btn ghost" onclick="researchReturn()">← Back to ${ctx.kind==='shortlists'?'shortlist':'screen'}</button><span class="faint">${ctx.kind==='shortlists'?'Private research list':esc(ctx.state.market)} · ${ctx.rows.length.toLocaleString()} available matches</span><button class="btn ghost" onclick="researchAdjacent(-1)" ${index<=0?'disabled':''}>Previous stock</button><button class="btn ghost" onclick="researchAdjacent(1)" ${index<0 || index>=ctx.rows.length-1?'disabled':''}>Next stock</button></div>`;
}
function researchAdjacent(delta) {
 const rows=window.__researchContext?.rows || [],i=rows.findIndex(r=>r.code===stkState().sym || r.symbol===stkState().sym);
 if(i>=0 && rows[i+delta])openStock(rows[i+delta].code);
}
function researchCompare() {
  const selected=window.__researchSelected || [];if(selected.length<2 || selected.length>4)return;
  researchCaptureContext();
  const st=cmpState();st.cells=selected.map(code=>({...JSON.parse(JSON.stringify(CMP_DEFAULT.cells[0])),sym:code.replace(/^US\./,'')}));
  st.layout=selected.length===2?'2h':selected.length===3?'1+2':'2x2';st.active=0;st.sync.ticker=false;cmpSave();showPage('compare');
}
function researchMode(mode) {window.__scr.presentation=mode;scrPersist();showPage('home');}
function researchSave() {openFilterModal();scrModalTab('screeners');}
function researchStable(value) {
 if(Array.isArray(value))return value.map(researchStable);
 if(value && typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(k=>[k,researchStable(value[k])]));
 return value;
}
function researchSavedModified(saved,st) {
 if(!saved)return false;
 const defaults={src:'moo',etfs:false,cols:[...VIEW_PRESETS.overview],view:'overview',presentation:'table',preset:null,colFilters:{}};
 const settings={...defaults,...saved.settings};
 const expected={market:saved.market || st.market,watchlistOnly:!!saved.watchlist_only,filters:saved.filters || [],sort:saved.sort || 'market_cap',dir:saved.direction || 2,src:settings.src,etfs:settings.etfs,cols:settings.cols,view:settings.view,presentation:settings.presentation,activePreset:settings.preset || null,colFilters:settings.colFilters || {}};
 const actual=Object.fromEntries(Object.keys(expected).map(k=>[k,st[k] ?? (k==='presentation'?'table':k==='view'?'overview':k==='colFilters'?{}:null)]));
 return JSON.stringify(researchStable(expected))!==JSON.stringify(researchStable(actual));
}
function researchViewLabel(view,st) {
 const name=view[0].toUpperCase()+view.slice(1);
 return view===st.view && VIEW_PRESETS[view] && JSON.stringify(st.cols)!==JSON.stringify(VIEW_PRESETS[view])?name+' · retained columns':name;
}
function researchScreenTitle(st=window.__scr) {
 const saved=(window.__savedScreeners || []).find(s=>s.id===st.savedScreenId),preset=(window.__scrPresets || []).find(p=>p.key===st.activePreset);
 if(st.savedScreenId)return (saved?.name || 'Saved screen')+(saved && researchSavedModified(saved,st)?' · Modified':'');
 if(preset){const modified=st.filters.some(f=>!(preset.filters || []).some(p=>JSON.stringify(p)===JSON.stringify(f))) || Object.keys(st.colFilters || {}).length>0;return preset.name+(modified?' · Modified':'');}
 return st.activePreset?'Screen results':st.filters.length || Object.keys(st.colFilters).length?'Custom screen':'All stocks';
}
function researchSavedMount() {
 const el=document.getElementById('research-saved');if(!el)return;
 el.innerHTML=(window.__savedScreeners || []).map(s=>`<button class="btn ghost saved-screen ${window.__scr.savedScreenId===s.id?'on':''}" onclick="researchLibraryClose(false);scrApplySaved('${esc(s.id)}')">${esc(s.name)}${window.__scr.savedScreenId===s.id && researchSavedModified(s,window.__scr)?' <span class="saved-modified">Modified</span>':''}<small>${esc(s.sort)} ${s.direction===1?'↑':'↓'}</small></button>`).join('') || '<p class="faint saved-empty">Save your criteria to revisit them.</p>';
 researchLibrarySearch(window.__researchLibraryQuery || '');
 const heading=document.querySelector('.desk-title h2') || document.querySelector('.change-context h2');if(heading)heading.textContent=(window.__scr.presentation==='changes'?'Changes in ':'')+researchScreenTitle();
}
function researchSortSet(field, direction) {
 if(!SCR_COLS[field] || ![1,2].includes(Number(direction)))return;
 Object.assign(window.__scr,{sort:field,dir:Number(direction),page:1});scrPersist();showPage('home');
}
function researchLibraryGroups(presets) {
 const groups=[['Value & quality',['buffett','undervalued','pb-lt-1','good-pe','low-pe','high-roe','undervalued-semi','undervalued-tech','undervalued-banks']],['Income',['high-div','best-lt-high-div','blue-chip-div','lt-high-div']],['Growth & established',['blue-chip','growth','high-pe','high-eps']],['Price & technical',['penny','rsi-30','junk','small-growth','speculative']]];
 const used=new Set();const result=groups.map(([name,keys])=>({name,presets:presets.filter(p=>keys.includes(p.key) && !used.has(p.key) && used.add(p.key))})).filter(g=>g.presets.length);
 const other=presets.filter(p=>!used.has(p.key));if(other.length)result.push({name:'Other screens',presets:other});return result;
}
function researchLibraryHTML(st,presets) {
 const call=x=>esc(JSON.stringify(x));
 const card=p=>{const ck=p.key+'|'+st.market,success=window.__presetCache?.[ck],last=window.__presetLastResult?.[ck],cached=last && (!success || last.ts>success.ts)?last:success,payload=cached?.payload;
  const label=payload?.available===false?'Unavailable':payload?.available?payload.rows.length.toLocaleString()+' loaded':'Not loaded';
  return `<button class="preset ${st.activePreset===p.key?'on':''}" data-screen-key="${esc(p.key)}" aria-pressed="${st.activePreset===p.key}" onclick="researchLibraryClose(false);scrApplyPreset(${call(p.key)})" onmouseenter="scrWarmPreset(${call(p.key)},${call(st.market)})" onfocus="scrWarmPreset(${call(p.key)},${call(st.market)})" title="${esc(p.description || p.name)}"><span class="pname">${esc(p.name)}</span><small>${(p.filters || []).length} criteria · ${esc(SCR_COLS[p.sort || 'pct']?.[0] || p.sort || 'Day change')} ${p.direction===1?'ascending':'descending'}</small><span class="library-count" title="Loaded provider results; before additional stock/ETF and custom exclusions. ${cached?.ts?'Retrieved '+new Date(cached.ts).toISOString():'No cached execution'}">${esc(label)}</span></button>`;
 };
 return `<aside class="panel scr-rail research-library" id="research-library" aria-label="Screen library"><div class="library-heading"><h2>Screen library</h2><button class="btn ghost library-close" onclick="researchLibraryClose()">Close screens</button></div><input id="research-library-search" aria-label="Search screens" placeholder="Search all screens…" value="${esc(window.__researchLibraryQuery || '')}" oninput="researchLibrarySearch(this.value)"><button class="btn library-default ${!st.activePreset && !st.savedScreenId && !st.filters.length && !Object.keys(st.colFilters).length?'primary':'ghost'}" onclick="researchLibraryClose(false);scrResetAll()">All stocks<small>${esc(st.market)} · ETFs excluded · Market cap descending</small></button><section class="saved-library"><button class="btn ghost" onclick="researchLibraryClose(false);showPage('shortlists')">Research shortlists</button><h3>My saved screens</h3><div id="research-saved"></div><button class="btn ghost" onclick="researchLibraryClose(false);researchSave()">Manage / save screen</button></section><h3 class="library-recommended-title">Recommended <small>${presets.length} screens</small></h3>${researchLibraryGroups(presets).map(g=>`<details class="library-group" open ontoggle="researchLibraryGroupToggle(this)"><summary>${esc(g.name)} <small>${g.presets.length}</small></summary><div>${g.presets.map(card).join('')}</div></details>`).join('')}<div id="research-library-empty" hidden role="status"><p>No screens match your search.</p><button class="btn ghost" onclick="document.getElementById('research-library-search').value='';researchLibrarySearch('')">Clear search</button></div><p class="library-help">Counts describe cached provider executions, not a live market total. Open a screen for qualified results and coverage.</p></aside>`;
}
function researchLibraryGroupToggle(el) {
 if(window.__researchLibraryQuery)return;
 window.__researchLibraryCollapsed=window.__researchLibraryCollapsed || new Set();
 const name=el.querySelector('summary')?.firstChild?.textContent?.trim();if(!name)return;
 el.open?window.__researchLibraryCollapsed.delete(name):window.__researchLibraryCollapsed.add(name);
}
function researchLibrarySearch(q) {
 window.__researchLibraryQuery=String(q || '');const query=window.__researchLibraryQuery.toLowerCase().trim();
 document.querySelectorAll('.research-library .preset,.research-library .saved-screen').forEach(el=>el.hidden=!!query && !el.textContent.toLowerCase().includes(query));
 document.querySelectorAll('.research-library .library-group').forEach(group=>{const matched=[...group.querySelectorAll('.preset')].some(el=>!el.hidden);group.hidden=!matched;if(query && matched)group.open=true;else if(!query){const name=group.querySelector('summary').firstChild.textContent.trim();group.open=!window.__researchLibraryCollapsed?.has(name);}});
 const empty=document.getElementById('research-library-empty');if(empty)empty.hidden=!query || [...document.querySelectorAll('.research-library .preset,.research-library .saved-screen')].some(el=>!el.hidden);
 const saved=document.getElementById('research-saved');if(saved){const cards=[...saved.querySelectorAll('.saved-screen')];const message=saved.querySelector('.saved-empty');if(message)message.hidden=cards.length>0;}
}
function researchLibraryClose(restore=true) {
 const el=document.getElementById('research-library');el?.classList.remove('library-open');el?.removeAttribute('aria-modal');el?.removeAttribute('role');
 researchModalRelease('library');if(restore && window.__libraryOrigin?.isConnected)window.__libraryOrigin.focus();
}
function researchLibraryOpen() {
 const el=document.getElementById('research-library');if(!el)return;
 window.__libraryOrigin=document.activeElement;el.classList.add('library-open');el.setAttribute('role','dialog');el.setAttribute('aria-modal','true');researchModalIsolate(el,'library');
 el.onkeydown=e=>researchModalKey(e,el,()=>researchLibraryClose());el.querySelector('input')?.focus();
}
function researchModalRelease(key) {
 for(const [el,previous] of window.__researchModalInert?.[key] || [])el.inert=previous;
 if(window.__researchModalInert)delete window.__researchModalInert[key];
}
function researchModalIsolate(el,key) {
 researchModalRelease(key);const changed=[];
 for(let current=el;current?.parentElement;current=current.parentElement){for(const sibling of current.parentElement.children){if(sibling!==current && !['SCRIPT','STYLE','LINK'].includes(sibling.tagName)){changed.push([sibling,sibling.inert]);sibling.inert=true;}}if(current.parentElement===document.body)break;}
 window.__researchModalInert=window.__researchModalInert || {};window.__researchModalInert[key]=changed;
}
function researchModalKey(e,el,close) {
 if(e.key==='Escape'){e.preventDefault();close();return;}
 if(e.key!=='Tab')return;const controls=[...el.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),a[href],summary,[tabindex="0"]')].filter(x=>x.getClientRects().length),first=controls[0],last=controls.at(-1);
 if(e.shiftKey && document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey && document.activeElement===last){e.preventDefault();first?.focus();}
}
function researchMarketHTML(ms,full) {
 const labels={SPY:'S&P 500 proxy',QQQ:'Nasdaq-100 proxy',IWM:'Russell 2000 proxy',VIXY:'VIX futures ETF proxy'};
 const summary=(ms?.indices || []).slice(0,5).map(x=>{const symbol=String(x.symbol || x.code || '').replace(/^US\./,'');const name=labels[symbol] || x.name || symbol;
  return `<span class="market-proxy"><strong>${esc(symbol || x.name)} ${esc(labels[symbol] || '')}</strong><span>${x.last==null?'Unavailable':esc(fmtAuto(x.last))}</span><span class="${x.pct>=0?'g':'r'}">${x.pct==null?'—':esc(researchValue('pct',x.pct))}</span></span>`;
 }).join('');
 return `<details class="research-market"><summary><span>Market context</span>${summary || '<span class="faint">Unavailable</span>'}<small>${ms?.as_of?'As of '+esc(fmtTs(ms.as_of)):'Source time unavailable'}</small></summary><div>${full || '<p>Market context is unavailable. Screen results remain independently available.</p>'}<p class="faint">ETF proxies are context instruments and do not enter stock-only results. VIXY is a futures ETF, not the spot VIX level.</p></div></details>`;
}
function researchDeskHTML({st,scr,execd,ms,msPanel,table,allChips,prog,progPct}) {
 const presets=window.__scrPresets || [],mode=st.presentation || 'table';
 const title=researchScreenTitle(st);
 const source=scr.server_side?'Provider screen · financial basis requested: annual; reported period unverified':scr.universe_loaded?'Stored '+st.market+' universe'+(scr.universe_as_of?(scr.generation_id?' · generation published ':' · cache updated ')+fmtTs(scr.universe_as_of):' · source time unavailable'):'Live fallback slices · universe incomplete';
 const matched=scr.matched ?? (scr.rows || []).length;
 const exportMenu=`<details class="research-export"><summary class="btn ghost">Export</summary><div class="export-options">${[['csv','CSV'],['xls','Excel']].map(([kind,label])=>['page','all'].map(scope=>`<button class="btn ghost" onclick="scrExport('${kind}','${scope}')">${label} · ${scope==='page'?'this page':'available matches'}<small>${Number(scope==='page'?(scr.shown ?? (scr.rows || []).length):matched).toLocaleString()} ${st.etfs?'instruments':'stocks'} · current columns and sort</small></button>`).join('')).join('')}<small>Current columns and sort · Excel-compatible .xls · available matches means loaded qualified results</small></div></details>`;
 const universe=`<details class="research-universe"><summary class="btn ghost">Universe & data</summary><div class="universe-options"><label>Market<select id="scr-market" aria-label="Market" onchange="scrSet('market',this.value)">${['US','HK'].map(m=>`<option ${st.market===m?'selected':''}>${m}</option>`).join('')}</select></label><label>Data<select aria-label="Data source" onchange="scrSet('src',this.value)"><option value="moo" ${st.src!=='yf'?'selected':''}>Moomoo</option><option value="yf" ${st.src==='yf'?'selected':''}>Supplemental factors</option></select></label><label>Provider list<select id="scr-industry" aria-label="Provider list" onchange="scrTaxonomy('plate',this.value)"><option value="">Provider list: All</option></select></label><label>Provider theme<select id="scr-concepts" aria-label="Provider theme" onchange="scrTaxonomy('concepts',this.value)"><option value="">Theme: All</option></select></label><label>Exchange<select id="scr-exchange" aria-label="Exchange" onchange="scrTaxonomy('exchange',this.value)"><option value="">Exchange: All</option></select></label><label>Symbols<input id="scr-tickers" placeholder="NVDA, AAPL" value="${esc((st.filters.find(f=>f.field==='symbol')?.values || []).join(', '))}" onchange="scrTickers(this.value)"></label><label><input type="checkbox" id="scr-wl" ${st.watchlistOnly?'checked':''} onchange="scrSet('watchlistOnly',this.checked)"> Watchlist only</label><label><input type="checkbox" ${st.etfs?'checked':''} onchange="scrSet('etfs',this.checked)"> Include ETFs</label><button class="btn ghost" onclick="scrLoadUniverse(this)" ${window.__scrRefreshJob?'disabled':''}>${scr.universe_loaded?'Refresh full market':'Load full market'}</button><p>Provider lists and themes are vendor classifications. They are not normalized industry or sector classifications. Supplemental factor availability varies by stock; missing fields cannot qualify a filter.</p></div></details>`;
 const pager=(matched>(scr.shown || 0) || st.page>1)?`<div class="pager"><button class="btn ghost" ${st.page<=1?'disabled':''} onclick="scrSet('page',1)">First</button><button class="btn ghost" ${st.page<=1?'disabled':''} onclick="scrPage(-1)">Previous</button><span>Page ${st.page || 1} of ${Math.max(1,Math.ceil(matched/(st.pageSize || 500)))}</span><button class="btn ghost" ${(scr.offset || 0)+(scr.shown || 0)>=matched?'disabled':''} onclick="scrPage(1)">Next</button><button class="btn ghost" ${(scr.offset || 0)+(scr.shown || 0)>=matched?'disabled':''} onclick="scrSet('page',999999)">Last</button><select aria-label="Rows per page" onchange="scrSet('pageSize',Number(this.value))">${[100,250,500,1000,2000].map(n=>`<option value="${n}" ${(st.pageSize || 500)===n?'selected':''}>${n} / page</option>`).join('')}</select></div>`:'';
 return `${researchMarketHTML(ms,msPanel)}<div class="scr-grid research-grid research-desk ${mode==='changes'?'changes-mode':''}">${researchLibraryHTML(st,presets)}<main class="panel scr-main">${mode==='changes'?researchChangeHeader(title,st):`<div class="desk-query"><div class="desk-title"><div><h2>${esc(title)}</h2><p>${esc(st.market)} · ${st.etfs?'Stocks + ETFs':'ETFs excluded'} · ${esc(SCR_COLS[st.sort]?.[0] || st.sort)} ${st.dir===2?'descending':'ascending'}</p></div><div class="research-modes" role="group" aria-label="Result presentation">${['table','explore','changes'].map(v=>`<button class="btn ${mode===v?'primary':'ghost'}" aria-pressed="${mode===v}" onclick="researchMode('${v}')">${v[0].toUpperCase()+v.slice(1)}</button>`).join('')}</div></div><div class="desk-actions"><button class="btn ghost library-open-control" onclick="researchLibraryOpen()">Screens</button><button class="btn ghost" onclick="openFilterModal()">Add filter</button><button class="btn ghost desk-clear" onclick="scrResetAll()" title="All stocks excluding ETFs, sorted by market cap">Clear</button><span class="desk-action-spacer"></span><button class="btn ghost" onclick="researchSave()">Save screen</button>${exportMenu}</div><div class="desk-views"><label>View<select aria-label="Column view" onchange="this.value==='custom'?scrToggleColPick():scrSetView(this.value)">${[...Object.keys(VIEW_PRESETS),'custom'].map(v=>`<option value="${v}" ${(st.view || 'overview')===v?'selected':''}>${esc(researchViewLabel(v,st))}</option>`).join('')}</select></label><label>Sort<select aria-label="Sort results" onchange="researchSortSet(this.value,window.__scr.dir)">${Object.entries(SCR_COLS).map(([k,[label]])=>`<option value="${k}" ${st.sort===k?'selected':''}>${esc(label)}</option>`).join('')}</select></label><select aria-label="Sort direction" onchange="researchSortSet(window.__scr.sort,this.value)"><option value="2" ${st.dir===2?'selected':''}>Descending</option><option value="1" ${st.dir===1?'selected':''}>Ascending</option></select><details class="desk-options"><summary class="btn ghost">More</summary><div><button class="btn ghost" onclick="scrToggleColPick()">Choose columns (${st.cols.length})</button><label>Density<select aria-label="Row density" onchange="researchDensity(this.value)"><option value="comfortable" ${window.__researchDensity!=='compact'?'selected':''}>Comfortable</option><option value="compact" ${window.__researchDensity==='compact'?'selected':''}>Compact</option></select></label>${universe}<details class="research-advanced"><summary>Quick signals</summary><div class="secondary-tools">${Object.keys(SIG_DEFS).map(n=>`<button class="btn ghost" onclick="scrSignal('${n}')" title="${esc(SIG_DEFS[n].title)}">${esc(SIG_DEFS[n].label)}</button>`).join('')}</div></details></div></details></div>${allChips?`<div class="scr-chips" aria-label="Applied criteria">${allChips}</div>`:''}<div class="desk-result-summary" role="status">${mode==='changes'?'Current screen: ':''}${matched.toLocaleString()} ${st.etfs?'instruments':'stocks'}${mode==='changes'?'':mode==='explore'?' · Explore uses loaded matches':' · '+(scr.shown ?? (scr.rows || []).length)+' on this page'} ${scr.possibly_truncated?'· more provider matches may exist':''}</div></div>`}<details class="desk-data-context"><summary>${esc(source)}${st.src==='yf'?' · supplemental factors':''}</summary><p>${st.watchlistOnly?'Watchlist scope. ':''}${scr.stale_hint?'Showing cached data saved '+Math.max(1,Math.round((Date.now()-scr.stale_hint)/60000))+' min ago while updating. ':''}Stored universe reflects provider enumeration. Coverage, instrument types, periods and freshness can differ from the provider app. Exports and Explore use loaded matches; missing numeric evidence is unavailable, not zero.</p></details>${scr.server_fallback_reason?`<div class="delay-note" role="status">${esc(scr.server_fallback_reason)}</div>`:''}${(scr.skipped_filters || []).length?`<div class="delay-note">${scr.skipped_filters.length} criteria lack numeric evidence: ${scr.skipped_filters.map(f=>esc(SCR_FIELDS[f] || f)).join(', ')}</div>`:''}${prog?`<div class="scr-prog"><div class="bar"><i style="width:${(progPct || 5).toFixed(0)}%;background:#3a76dd"></i><i style="width:${100-(progPct || 5)}%;background:#33415a"></i></div><span class="mono faint">${esc(prog.msg)}${prog.status?' · '+esc(prog.status):''}</span></div>`:''}<div id="research-provider-paging"></div><div id="research-presentation"></div><div class="scr-scroll">${table}</div><div id="research-mobile-results" class="research-mobile-results"></div>${pager}<p class="desk-export-scope">${mode==='changes'?'Ticker opens full research. Review evidence compares captures. Export comparison CSV includes the complete filtered capture review; switch to Table for current-screen exports.':'Ticker opens full research. Inspect preserves your screen. Exports: this page or all loaded matches, in the current sort order.'}</p><div id="research-selection" class="research-selection" hidden></div><output id="research-performance" hidden></output></main><aside id="research-inspector" class="research-inspector"></aside></div>`;
}
function researchDensity(value) {
 window.__researchDensity=value==='compact'?'compact':'comfortable';
 document.querySelector('.research-desk')?.classList.toggle('density-compact',window.__researchDensity==='compact');
 try{localStorage.setItem('researchDensity',window.__researchDensity);}catch(e){}
}
function researchMobileMount(limit=40) {
 const el=document.getElementById('research-mobile-results');if(!el)return;
 const rows=researchVisibleRows(),st=window.__scr,call=x=>esc(JSON.stringify(x));
 el.innerHTML=rows.slice(0,limit).map((r,i)=>`<article class="mobile-stock ${window.__researchSelected?.includes(researchKey(r))?'research-selected':''}" data-research-index="${i}"><div class="mobile-stock-heading"><label class="stock-select"><input type="checkbox" data-research-index="${i}" aria-label="Select ${esc(r.symbol)} for comparison" ${window.__researchSelected?.includes(researchKey(r))?'checked':''} onchange="researchSelect(${i},this.checked)"></label><div><a href="#" onclick="event.preventDefault();researchOpen(${call(researchKey(r))})">${esc(r.symbol)}</a><p>${esc(r.name || 'Company name unavailable')}</p></div><div class="mobile-stock-price">${researchMoneyHTML(r,'price')}${researchScreenValuesHTML(r,'price',st)}<small class="${r.pct>=0?'g':'r'}">${esc(researchValue('pct',r.pct))}</small>${researchScreenValuesHTML(r,'pct',st)}</div></div><div class="mobile-stock-metrics"><span>Cap <strong>${researchMoneyHTML(r,'market_cap')}</strong>${researchScreenValuesHTML(r,'market_cap',st)}</span><span>P/E <strong>${esc(researchValue('pe_ttm',r.pe_ttm))}</strong>${researchScreenValuesHTML(r,'pe_ttm',st)}</span><button class="btn ghost" onclick="researchInspect(${i},this)" aria-label="Inspect ${esc(r.symbol)}">Inspect</button></div><details><summary>Row details</summary><dl>${st.cols.filter(k=>!['symbol','name','price','pct','market_cap','pe_ttm'].includes(k)).map(k=>`<dt>${esc(SCR_COLS[k]?.[0] || k)}</dt><dd>${esc(RESEARCH_CURRENCY_FIELDS.has(k)?researchMoneyValue(r,k):researchDisplayField(k,r[k]))}${researchScreenValuesHTML(r,k,st)}</dd>`).join('')}</dl></details></article>`).join('') || '<p>No rows qualify. Use Clear or revise the criteria.</p>';
 if(rows.length>limit)el.innerHTML+=`<button class="btn ghost" onclick="researchMobileMount(${limit+40})">Show next ${Math.min(40,rows.length-limit)} on this page</button><p>${limit} of ${rows.length} page rows displayed. Export this page includes all ${rows.length}.</p>`;
}
function scrWorkspaceMount() {
 researchDisposeInspector();researchModalRelease('library');
 const grid=document.querySelector('.research-desk');if(!grid)return;
 let density=window.__researchDensity;try{density=density || localStorage.getItem('researchDensity');}catch(e){}researchDensity(density);
 grid.classList.toggle('identity-first',window.__scr.cols[0]==='symbol' && window.__scr.cols[1]==='name');
 researchSavedMount();researchLibrarySearch(window.__researchLibraryQuery || '');researchMobileMount();researchSelectionMount();
 researchFrozenColumns();if(typeof ResizeObserver!=='undefined'){window.__deskResize=new ResizeObserver(researchFrozenColumns);window.__deskResize.observe(grid.querySelector('.scr-table'));}
 const st=window.__scr,rows=researchRows(),mode=st.presentation || 'table';grid.classList.toggle('table-mode',mode==='table');grid.classList.toggle('explore-mode',mode==='explore');
 const presentation=document.getElementById('research-presentation'),scroll=grid.querySelector('.scr-scroll');
 if(mode==='explore'){presentation.className='research-explore';researchExploreMount();scroll.hidden=true;document.getElementById('research-mobile-results').hidden=true;grid.querySelector('.pager')?.setAttribute('hidden','');}
 if(mode==='changes'){presentation.className='research-changes';presentation.innerHTML=researchChangesHTML();scroll.hidden=true;document.getElementById('research-mobile-results').hidden=true;grid.querySelector('.pager')?.setAttribute('hidden','');researchLoadChanges();}
 if(st.activePreset){const payload=window.__presetCache?.[st.activePreset+'|'+st.market]?.payload;
  if(payload?.available){document.getElementById('research-provider-paging').innerHTML=researchProviderScopeHTML(payload,rows,st);}
 }
 if(window.__researchInspectCode){const row=researchRows().find(r=>researchKey(r)===window.__researchInspectCode);if(row)researchInspectRow(row);else researchCloseInspector(false);}
}
function researchProviderScopeHTML(payload,rows,st) {
 const warnings=Array.isArray(payload.hydration_warnings)?payload.hydration_warnings:[];
 const unknown=(payload.rows || []).filter(r=>!r.stock_type || ['UNKNOWN','UNKNOW','UNCLASSIFIED','N/A'].includes(String(r.stock_type).toUpperCase())).length;
 const outside=(payload.rows || []).filter(r=>!r.quote_generation_id).length;
 const ck=st.activePreset+'|'+st.market,entry=window.__presetCache?.[ck],busy=!!window.__presetRefresh?.[ck];
 const counts=`${rows.length.toLocaleString()} ${st.etfs?'instrument':'stock'} matches loaded · ${(payload.rows || []).length.toLocaleString()} provider members retrieved${payload.provider_total!=null?' · '+Number(payload.provider_total).toLocaleString()+' provider matches before exclusions/refinements':''}`;
 const refresh=`<button class="btn ghost" id="research-refresh-preset" onclick="researchRefreshPreset()" ${busy?'disabled':''}>${busy?'Refreshing results…':'Refresh results'}</button>`;
 const more=payload.next_key && payload.possibly_truncated?`<button class="btn ghost" id="research-load-more" onclick="researchLoadMore()" ${busy?'disabled':''}>Load next 300 matches</button>`:'';
 const quality=unknown || warnings.length;
 const qualityText=[unknown?`${unknown.toLocaleString()} ${unknown===1?'instrument has':'instruments have'} unknown classification`:'',warnings.length?`${warnings.length} hydration ${warnings.length===1?'warning':'warnings'}`:''].filter(Boolean).join(' · ');
 return `<section class="provider-scope" aria-label="Provider result coverage">
  <div class="provider-scope-head"><p>${counts}</p><div class="provider-scope-actions">${refresh}${more}</div></div>
  <p class="provider-value-context">Main values come from displayed quote/factor data. “Screen” values are provider screening observations; their period may differ. Inspect → Why it matches shows each rule and source. Sort and added filters use display values.</p>
  <div class="provider-scope-meta"><span>Latest provider page retrieved: ${esc(researchCaptureTime(payload.retrieved_at))}</span><details class="provider-scope-details"><summary>Scope &amp; quote sources</summary><div><p>Exports and Explore use loaded matches. While navigating, loaded pages stay retained until Refresh results; refresh replaces them with the first provider page.</p>${payload.quote_generation_id?`<p><strong>Quote display cohort</strong><br>${esc(payload.quote_generation_id)} · ${outside.toLocaleString()} retrieved members outside this cohort. Membership comes from the provider screen; this quote cohort does not freeze provider membership or reporting periods.</p>`:'<p>Quote display cohort unavailable.</p>'}</div></details></div>
  ${quality?`<details class="provider-quality"><summary>${qualityText}</summary><div><p>Unknown classifications are excluded from stock-only results. Captures require complete classification.</p>${warnings.map(w=>`<p>${esc(String(w))}</p>`).join('')}</div></details>`:''}
  ${busy?'<p class="provider-refresh-status" role="status">Previous results retained while refreshing.</p>':''}
  ${entry?.refreshError?`<p class="delay-note" role="status">Refresh failed; previous results retained. ${esc(entry.refreshError)}</p>`:''}<span id="research-page-status" role="status"></span>
 </section>`;
}
function researchExploreState() {
 const st=window.__scr,key=JSON.stringify(researchStable({market:st.market,src:st.src,etfs:st.etfs,watchlist:st.watchlistOnly,preset:st.activePreset,filters:st.filters,colFilters:st.colFilters}));
 if(window.__exploreState?.key!==key)window.__exploreState={key,x:window.__researchAxisX || 'pe_ttm',y:window.__researchAxisY || 'pct',xs:'linear',ys:'linear',trim:false,bounds:null,zoom:false,limit:100};
 return window.__exploreState;
}
function researchExploreSet(key,value) {
 const st=researchExploreState();if(['x','y'].includes(key)){if(!['pe_ttm','pb','market_cap','pct'].includes(value))return;st[key]=value;st.bounds=null;st.zoom=false;}
 else if(['xs','ys'].includes(key)){if(!['linear','log'].includes(value))return;st[key]=value;}
 else if(key==='trim')st.trim=!!value;else if(key==='capCurrency'){if(value!=='' && !/^[A-Z]{3}$/.test(value))return;st.capCurrency=value;st.bounds=null;st.zoom=false;}else if(key==='size'){if(!['uniform','cap'].includes(value))return;st.size=value;}else return;
 st.pointCodes=null;st.plotCode=null;st.preview=false;st.limit=100;researchExploreMount();document.querySelector('[aria-label="'+({x:'X axis',y:'Y axis',xs:'X scale',ys:'Y scale',size:'Plot point size',capCurrency:'Market-cap axis currency'}[key] || 'Central 96% on each axis')+'"]')?.focus();
}
function researchPlottable(r,x,y) {return [x,y].every(k=>typeof r[k]==='number' && Number.isFinite(r[k]) && (!['pe_ttm','pb','market_cap'].includes(k) || r[k]>0));}
function researchExploreCurrencyPass(row,st){return ![st.x,st.y].includes('market_cap') || !!st.capCurrency && researchFieldCurrency(row,'market_cap')===st.capCurrency;}
function researchExploreSelected(rows,st=researchExploreState()) {
 return rows.filter(r=>researchExploreCurrencyPass(r,st) && researchPlottable(r,st.x,st.y) && (!st.bounds || ['x','y'].every(axis=>{const v=Number(r[st[axis]]),b=st.bounds[axis];return (b.min==null || v>=b.min) && (b.max==null || v<=b.max);})));
}
function researchExploreDomain(values,scale,trim) {
 const valid=values.filter(v=>Number.isFinite(v) && (scale!=='log' || v>0)).sort((a,b)=>a-b);if(!valid.length)return null;
 const at=q=>valid[Math.floor(q*(valid.length-1))];let min=at(trim ? .02 : 0),max=at(trim ? .98 : 1);
 if(min===max){const delta=Math.max(Math.abs(min)*.05,.1);min=scale==='log'?Math.max(min/1.1,Number.MIN_VALUE):min-delta;max=scale==='log'?max*1.1:max+delta;}
 return {min,max};
}
function researchExploreModel(rows,st) {
 const numericRows=rows.filter(r=>researchPlottable(r,st.x,st.y)),valid=numericRows.filter(r=>researchExploreCurrencyPass(r,st)),selected=researchExploreSelected(rows,st);
 const scaleEligible=valid.filter(r=>(st.xs!=='log' || Number(r[st.x])>0) && (st.ys!=='log' || Number(r[st.y])>0));
 const domainRows=st.zoom && st.bounds?selected.filter(r=>(st.xs!=='log' || Number(r[st.x])>0) && (st.ys!=='log' || Number(r[st.y])>0)):scaleEligible;
 const xd=researchExploreDomain(domainRows.map(r=>Number(r[st.x])),st.xs,st.trim && !st.zoom),yd=researchExploreDomain(domainRows.map(r=>Number(r[st.y])),st.ys,st.trim && !st.zoom);
 const plotted=xd && yd?scaleEligible.filter(r=>Number(r[st.x])>=xd.min && Number(r[st.x])<=xd.max && Number(r[st.y])>=yd.min && Number(r[st.y])<=yd.max):[];
 return {valid,selected,plotted,xd,yd,missing:rows.length-numericRows.length,currencyExcluded:numericRows.length-valid.length,scaleExcluded:valid.length-scaleEligible.length,outside:scaleEligible.length-plotted.length};
}
function researchExploreBoundsToggle(panel) {
 researchExploreState().formOpen=panel.open;
 if(panel.open)document.querySelectorAll('.explore-action-strip .research-export[open]').forEach(menu=>{menu.open=false;});
}
function researchExploreSelectionText(regionRows) {
 const selected=window.__researchSelected || [],keys=new Set(regionRows.map(researchKey));
 const inside=selected.filter(code=>keys.has(code)).length;
 return `${selected.length} selected for Compare · ${inside} in this scope · ${selected.length-inside} outside. Compare 2–4 stocks; changing the region keeps your selection.`;
}
function researchExploreSelectionMount() {
 const context=document.getElementById('explore-selection-context'),button=document.getElementById('explore-compare');
 if(!context && !button)return;
 const selected=window.__researchSelected || [];
 if(context)context.textContent=researchExploreSelectionText(researchExploreSelected(researchRows(),researchExploreState()));
 if(button){button.textContent=`Compare selected (${selected.length})`;button.disabled=selected.length<2 || selected.length>4;}
}
function researchExploreSector(row,now=Date.now()) {
 const value=row?.sector,origin=row?.display_field_sources?.sector;
 if(typeof row?.code!=='string' || !/^(US|HK)\.[A-Z0-9][A-Z0-9._-]{0,30}$/.test(row.code) || typeof value!=='string' || !value.trim() || value.length>120 || !origin || origin.source!=='yfinance')return 'Unknown';
 const stamp=Date.parse(origin.cache_at),age=now-stamp;
 return Number.isFinite(stamp) && age>=0 && age<=7*86400000?value.trim():'Unknown';
}
function researchExploreSectorColor(sector) {
 if(sector==='Unknown')return '#9aa9bd';
 const colors=['#58a6ff','#ffb86b','#bd93f9','#50d9b2','#f781bf','#d4d66c','#79c9df','#ef8f88'];
 let hash=0;for(const char of sector)hash=(Math.imul(hash,31)+char.charCodeAt(0))>>>0;return colors[hash%colors.length];
}
function researchExploreEncoding(rows,model,now=Date.now()) {
 const groups=new Map(),plotted=new Set(model.plotted.map(researchKey));
 for(const row of rows){const sector=researchExploreSector(row,now),group=groups.get(sector) || {sector,loaded:0,plotted:0,color:researchExploreSectorColor(sector)};group.loaded++;if(plotted.has(researchKey(row)))group.plotted++;groups.set(sector,group);}
 const caps=model.plotted.map(row=>({value:row.market_cap,currency:researchFieldCurrency(row,'market_cap')}));
 const currencies=new Set(caps.map(c=>c.currency).filter(Boolean)),capReady=caps.length>0 && caps.every(c=>typeof c.value==='number' && Number.isFinite(c.value) && c.value>0 && c.currency) && currencies.size===1;
 return {sectors:[...groups.values()].sort((a,b)=>a.sector==='Unknown'?1:b.sector==='Unknown'?-1:a.sector.localeCompare(b.sector)),capReady,currency:capReady?[...currencies][0]:null,maxCap:capReady?Math.max(...caps.map(c=>c.value)):null,capReason:!caps.length?'No plotted stocks.':currencies.size>1?'Plotted market caps use different currencies.':'Every plotted stock needs a positive, identity-attributed market cap in one currency.'};
}
function researchExploreEncodingHTML(rows,model,st) {
 const encoding=researchExploreEncoding(rows,model),known=encoding.sectors.filter(g=>g.sector!=='Unknown').reduce((n,g)=>n+g.loaded,0);
 return `<section class="explore-encoding" aria-label="Plot sectors and sizing"><label>Point size<select aria-label="Plot point size" onchange="researchExploreSet('size',this.value)"><option value="uniform" ${st.size!=='cap'?'selected':''}>Uniform</option><option value="cap" ${st.size==='cap' && encoding.capReady?'selected':''} ${!encoding.capReady?'disabled':''}>Market cap${encoding.currency?' · '+esc(encoding.currency):' · unavailable'}</option></select></label><p>${st.size==='cap' && encoding.capReady?'Size: bounded area by '+esc(encoding.currency)+' market cap · radius 3–12 px.':'Uniform points.'} ${!encoding.capReady?'Cap sizing unavailable: '+esc(encoding.capReason):'Cap sizing requires one attributed currency for all plotted stocks.'}</p><details class="explore-sector-legend"><summary>Sector context · ${known.toLocaleString()}/${rows.length.toLocaleString()} loaded classified</summary><p>Current cached yfinance labels, retrieved within seven days; separate from quote generations and provider lists. Counts: plotted / loaded. Colours can repeat; use labels and stock inspection. Unknown includes absent, stale or unqualified classifications. This does not change screen membership.</p><ul>${encoding.sectors.map(g=>`<li><span class="sector-swatch" style="background:${g.color}" aria-hidden="true"></span><span>${esc(g.sector)}</span><span>${g.plotted.toLocaleString()} / ${g.loaded.toLocaleString()}</span></li>`).join('')}</ul></details></section>`;
}
function researchExploreHTML(rows) {
 const st=researchExploreState(),model=researchExploreModel(rows,st),axes=['pe_ttm','pb','market_cap','pct'];
 const capAxis=[st.x,st.y].includes('market_cap'),currencies=[...new Set(rows.map(r=>researchFieldCurrency(r,'market_cap')).filter(Boolean))].sort();
 const capControl=capAxis?`<label>Market-cap axis currency<select aria-label="Market-cap axis currency" onchange="researchExploreSet('capCurrency',this.value)"><option value="">Choose attributed currency</option>${currencies.map(currency=>`<option value="${currency}" ${st.capCurrency===currency?'selected':''}>${currency}</option>`).join('')}</select></label><p class="explore-currency-note">${currencies.length?'Only the chosen attributed currency can plot or qualify a cap region. Other and unknown currencies are excluded; no conversion.':'No identity-attributed cap currencies are supplied in these loaded rows. Choose another axis; no currency is inferred.'}</p>`:'';
 const field=(a)=>`<label>${a.toUpperCase()} axis<select aria-label="${a.toUpperCase()} axis" onchange="researchExploreSet('${a}',this.value)">${axes.map(k=>`<option value="${k}" ${k===st[a]?'selected':''}>${esc(SCR_COLS[k][0])}</option>`).join('')}<option disabled>Forward P/E · coverage pending</option><option disabled>Revenue growth · coverage pending</option></select></label><label>Scale<select aria-label="${a.toUpperCase()} scale" onchange="researchExploreSet('${a}s',this.value)">${['linear','log'].map(k=>`<option value="${k}" ${st[a+'s']===k?'selected':''}>${k==='log'?'Log (positive only)':'Linear'}</option>`).join('')}</select></label>`;
 const bound=(a,edge)=>`<label>${a.toUpperCase()} ${edge==='min'?'minimum':'maximum'}<input type="number" step="any" id="explore-${a}-${edge}" aria-label="${a.toUpperCase()} ${edge==='min'?'minimum':'maximum'}" value="${st.bounds?.[a]?.[edge] ?? ''}" placeholder="Unbounded"></label>`;
 return `<div class="explore-controls">${field('x')}${field('y')}${capControl}<label><input type="checkbox" aria-label="Central 96% on each axis" ${st.trim?'checked':''} onchange="researchExploreSet('trim',this.checked)">Central 96% on each axis</label></div><p class="faint">${model.plotted.length.toLocaleString()} plotted of ${rows.length.toLocaleString()} loaded matches · ${model.missing} missing/nonmeaningful · ${capAxis?model.currencyExcluded+' outside chosen/attributed cap currency · ':''}${model.scaleExcluded} excluded by log scale · ${model.outside} outside view. Screen exports retain rows outside this view.</p><section class="explore-action-strip" aria-label="Explorer region actions"><div class="explore-region-summary"><strong>${st.bounds?'Region':'Plottable'} results (${model.selected.length.toLocaleString()})</strong><span class="faint">Temporary scope · current screen sort</span></div><button class="btn primary explore-preview-action" onclick="researchExplorePreview()" ${!st.bounds?'disabled':''}>Preview region filters</button><button id="explore-compare" class="btn ghost" onclick="researchCompare()" ${(window.__researchSelected || []).length<2 || (window.__researchSelected || []).length>4?'disabled':''}>Compare selected (${(window.__researchSelected || []).length})</button><details class="research-export"><summary class="btn ghost">Export ${st.bounds?'region':'plottable'} results</summary><div class="export-options"><button class="btn ghost" onclick="scrExport('csv','explore')" ${!model.selected.length?'disabled':''}>CSV · ${st.bounds?'region':'plottable'} results</button><button class="btn ghost" onclick="scrExport('xls','explore')" ${!model.selected.length?'disabled':''}>Excel · ${st.bounds?'region':'plottable'} results</button><small>All ${model.selected.length.toLocaleString()} eligible loaded rows · current sort · Excel-compatible .xls</small></div></details><button class="btn ghost" onclick="researchExploreClear()" ${!st.bounds?'disabled':''}>Clear region</button><button class="btn ghost explore-zoom" onclick="researchExploreZoom()" ${!st.bounds || !model.selected.length?'disabled':''}>${st.zoom?'Reset zoom':'Zoom to region'}</button><span id="explore-selection-context" class="faint" role="status">${researchExploreSelectionText(model.selected)}</span></section><details class="explore-range-panel" ${st.formOpen?'open':''} ontoggle="researchExploreBoundsToggle(this)"><summary>Set region bounds with numbers${st.bounds?' · region applied':''}</summary><form class="explore-range" onsubmit="event.preventDefault();researchExploreApply()"><span>Region bounds · X: ${esc(SCR_COLS[st.x][0])} (${st.x==='market_cap'?'whole '+(st.capCurrency || 'unqualified currency')+' units, not billions':st.x==='pct'?'percentage points':'times'}) · Y: ${esc(SCR_COLS[st.y][0])} (${st.y==='market_cap'?'whole '+(st.capCurrency || 'unqualified currency')+' units, not billions':st.y==='pct'?'percentage points':'times'})</span>${bound('x','min')}${bound('x','max')}${bound('y','min')}${bound('y','max')}<button class="btn primary" type="submit">Apply region</button><p id="explore-range-error" role="alert"></p></form></details>${st.preview?researchExplorePreviewHTML(rows,st):''}${researchExploreEncodingHTML(rows,model,st)}<canvas id="research-scatter" height="300" role="img" tabindex="0" aria-label="${esc(SCR_COLS[st.x][0])}${st.x==='market_cap'?' '+esc(st.capCurrency || 'currency unavailable'):''} versus ${esc(SCR_COLS[st.y][0])}${st.y==='market_cap'?' '+esc(st.capCurrency || 'currency unavailable'):''}. Arrow keys browse plotted coordinates; Enter inspects or opens overlapping stocks. Drag a region or use numeric bounds."></canvas><div id="research-plot-selection" role="status">Arrow keys browse coordinates; Enter opens stocks at that point. Drag a region or use numeric bounds.</div><div id="explore-point-picker"></div><div class="explore-subset-head"><h3>Linked results (${model.selected.length.toLocaleString()})</h3></div><p class="faint">Current screen sort. Region is a temporary research selection; screen criteria and saved definitions are unchanged. ${Math.min(st.limit,model.selected.length)} rows shown below.</p><div class="explore-linked"><table><thead><tr><th>Select</th><th>Symbol</th><th>Company</th><th>${esc(SCR_COLS[st.x][0])}</th><th>${esc(SCR_COLS[st.y][0])}</th><th>Inspect</th></tr></thead><tbody>${model.selected.slice(0,st.limit).map(r=>`<tr><td><label class="stock-select"><input type="checkbox" data-research-code="${esc(researchKey(r))}" aria-label="Select ${esc(r.symbol)} in region" ${(window.__researchSelected || []).includes(researchKey(r))?'checked':''} onchange="researchExploreSelect(${esc(JSON.stringify(researchKey(r)))},this.checked)"></label></td><td><a href="#" onclick="event.preventDefault();researchOpen(${esc(JSON.stringify(researchKey(r)))})">${esc(r.symbol)}</a></td><td>${esc(r.name || 'Unavailable')}</td><td>${esc(researchValue(st.x,r[st.x],st.x==='market_cap'?st.capCurrency:undefined))}</td><td>${esc(researchValue(st.y,r[st.y],st.y==='market_cap'?st.capCurrency:undefined))}</td><td><button class="btn ghost" aria-label="Inspect ${esc(r.symbol)} in region" onclick="researchExploreInspect(${esc(JSON.stringify(researchKey(r)))},this)">Inspect</button></td></tr>`).join('') || '<tr><td colspan="6">No stocks in this region. Clear the region or revise its bounds.</td></tr>'}</tbody></table></div>${model.selected.length>st.limit?'<button class="btn ghost" onclick="researchExploreMore()">Show next 100 region rows</button>':''}`;
}
function researchExploreMount() {
 const target=document.getElementById('research-presentation');if(!target)return;target.innerHTML=researchExploreHTML(researchRows());researchPlot(researchRows());researchExplorePointPicker();researchSelectionMount();
 window.__exploreResize?.disconnect();if(typeof ResizeObserver!=='undefined'){window.__exploreResize=new ResizeObserver(()=>researchPlot(researchRows()));window.__exploreResize.observe(document.getElementById('research-scatter'));}
}
function researchExploreParseBounds(values) {
 const result={x:{},y:{}};for(const a of ['x','y'])for(const edge of ['min','max']){const raw=values[a][edge];const value=raw==null || String(raw).trim()===''?null:Number(raw);if(value!=null && !Number.isFinite(value))throw new Error('Bounds must be finite numbers.');result[a][edge]=value;}
 for(const a of ['x','y'])if(result[a].min!=null && result[a].max!=null && result[a].min>result[a].max)throw new Error(a.toUpperCase()+' minimum must not exceed maximum.');
 return result;
}
function researchExploreApply() {
 try{const values=Object.fromEntries(['x','y'].map(a=>[a,Object.fromEntries(['min','max'].map(edge=>[edge,document.getElementById('explore-'+a+'-'+edge).value]))]));const bounds=researchExploreParseBounds(values);const st=researchExploreState();st.pointCodes=null;st.plotCode=null;st.bounds=Object.values(bounds).some(b=>b.min!=null || b.max!=null)?bounds:null;st.zoom=false;st.limit=100;st.formOpen=false;st.preview=false;researchExploreMount();document.querySelector('.explore-range-panel summary')?.focus({preventScroll:true});}
 catch(e){document.getElementById('explore-range-error').textContent=e.message;}
}
function researchExploreCriteria(st) {
 if(!st.bounds)throw new Error('Select a region first.');
 const bounds=researchExploreParseBounds(st.bounds),rules=new Map();
 for(const axis of ['x','y']){
  const field=st[axis];if(!['pe_ttm','pb','market_cap','pct'].includes(field))throw new Error('This axis is not qualified for screen filters.');
  if(field==='market_cap' && !/^[A-Z]{3}$/.test(st.capCurrency || ''))throw new Error('Choose an attributed market-cap currency before applying this region.');
  const b=bounds[axis],positive=field!=='pct',rule=rules.get(field) || {field};
  if(field==='market_cap')rule.currency=st.capCurrency;
  let min=b.min,max=b.max;
  if(positive && (min==null || min<=0)){min=0;rule.excl_min=true;}
  if(min!=null)rule.min=rule.min==null?min:Math.max(rule.min,min);
  if(max!=null)rule.max=rule.max==null?max:Math.min(rule.max,max);
  if(rule.min>0)delete rule.excl_min;
  if(rule.min!=null && rule.max!=null && (rule.min>rule.max || (rule.min===rule.max && rule.excl_min)))throw new Error('The region has no meaningful intersection for '+SCR_COLS[field][0]+'.');
  // Unbounded numeric criteria still exclude absent/nonfinite axis data.
  rules.set(field,rule);
 }
 return [...rules.values()];
}
function researchExplorePreviewHTML(rows,st) {
 try{
  const rules=researchExploreCriteria(st),selected=researchExploreSelected(rows,st);
  return `<section class="explore-filter-preview" aria-label="Region filter preview"><h3>Apply region as screen filters</h3><div class="explore-preview-rules">${rules.map(f=>`<span>${esc(SCR_COLS[f.field][0])}${f.currency?' · '+esc(f.currency):''}: ${f.min!=null?(f.excl_min?'&gt; ':'≥ ')+esc(researchValue(f.field,f.min)):'no lower bound'} · ${f.max!=null?'≤ '+esc(researchValue(f.field,f.max)):'no upper bound'}</span>`).join('')}</div><p>${selected.length.toLocaleString()} of ${rows.length.toLocaleString()} loaded matches qualify. Adds constraints; retains existing criteria, preset membership and sort. Saved definitions stay unchanged until you save.</p><button class="btn primary" onclick="researchExploreCommit()">Apply filters to screen</button><button class="btn ghost" onclick="researchExploreCancelPreview()">Cancel preview</button><details><summary>Scope, units and missing values</summary><p>Missing/nonfinite values are excluded. Counts may change when new data is retrieved; this does not freeze membership. Market-cap bounds retain the chosen attributed currency; unknown and other currencies cannot qualify. currency is not inferred. Original recommendations stay unchanged.</p></details><p id="explore-commit-error" role="alert"></p></section>`;
 }catch(e){return `<p role="alert">${esc(e.message)}</p>`;}
}
function researchExplorePreview(){const st=researchExploreState();if(!st.bounds)return;st.preview=true;researchExploreMount();document.querySelector('.explore-filter-preview button')?.focus();}
function researchExploreCancelPreview(){researchExploreState().preview=false;researchExploreMount();document.querySelector('.explore-preview-action')?.focus({preventScroll:true});}
function researchExploreCommit(){
 const region=researchExploreState();if(!region.preview)return;
 try{
  const rules=researchExploreCriteria(region),st=window.__scr,eligible=new Set(researchExploreSelected(researchRows(),region).map(researchKey));
  const filters=JSON.parse(JSON.stringify(st.filters || []));
  for(const rule of rules)if(!filters.some(f=>JSON.stringify(researchStable(f))===JSON.stringify(researchStable(rule))))filters.push(rule);
  if(filters.length>40)throw new Error('This screen would exceed 40 criteria. Remove a criterion before applying the region.');
  st.filters=filters;st.page=1;st.presentation='table';
  window.__researchSelected=(window.__researchSelected || []).filter(code=>eligible.has(code));
  scrPersist();showPage('home');
 }catch(e){const el=document.getElementById('explore-commit-error');if(el)el.textContent=e.message;}
}
function researchExploreClear(){const st=researchExploreState();st.bounds=null;st.zoom=false;st.pointCodes=null;st.plotCode=null;st.preview=false;st.limit=100;researchExploreMount();document.querySelector('.explore-range-panel summary')?.focus({preventScroll:true});}
function researchExploreZoom(){const st=researchExploreState();st.zoom=!st.zoom;researchExploreMount();document.querySelector('.explore-zoom')?.focus();}
function researchExploreMore(){researchExploreState().limit+=100;researchExploreMount();}
function researchExploreSelect(code,on){const set=new Set(window.__researchSelected || []);on?set.add(code):set.delete(code);window.__researchSelected=[...set];researchSelectionMount();}
function researchExploreInspect(code,origin){const row=researchRows().find(r=>researchKey(r)===code);if(row){window.__inspectOrigin=origin;researchInspectRow(row,{focus:true});}}
function researchExplorePointGroups(rows,st) {
 const groups=new Map();
 for(const row of researchExploreModel(rows,st).plotted){
  const key=JSON.stringify([Number(row[st.x]),Number(row[st.y])]);
  if(!groups.has(key))groups.set(key,{x:Number(row[st.x]),y:Number(row[st.y]),rows:[]});
  groups.get(key).rows.push(row);
 }
 return [...groups.values()];
}
function researchExplorePointRows() {
 const st=researchExploreState(),codes=new Set(st.pointCodes || []);
 return researchExploreModel(researchRows(),st).plotted.filter(r=>codes.has(researchKey(r)) && st.pointCoordinate && Number(r[st.x])===st.pointCoordinate.x && Number(r[st.y])===st.pointCoordinate.y);
}
function researchExplorePointPicker() {
 const el=document.getElementById('explore-point-picker');if(!el)return;
 const st=researchExploreState(),rows=researchExplorePointRows();
 if(!rows.length){el.innerHTML='';return;}
 const offset=Math.max(0,Math.min(st.pointOffset || 0,Math.floor((rows.length-1)/50)*50));st.pointOffset=offset;
 el.innerHTML=`<section class="explore-point-picker" aria-label="Stocks at plotted coordinate" onkeydown="if(event.key==='Escape'){event.preventDefault();researchExplorePointClose()}"><h3>${rows.length.toLocaleString()} stocks at this coordinate</h3><p>${esc(SCR_COLS[st.x][0])}: ${esc(researchValue(st.x,rows[0][st.x]))} · ${esc(SCR_COLS[st.y][0])}: ${esc(researchValue(st.y,rows[0][st.y]))}. Current screen sort. Choose a company to inspect; selecting it does not change screen filters.</p><button class="btn ghost" onclick="researchExplorePointClose()">Close coordinate stocks</button><ul>${rows.slice(offset,offset+50).map(r=>`<li><label><input type="checkbox" data-research-code="${esc(researchKey(r))}" aria-label="Select ${esc(r.symbol)} at coordinate" ${(window.__researchSelected || []).includes(researchKey(r))?'checked':''} onchange="researchExploreSelect(${esc(JSON.stringify(researchKey(r)))},this.checked)">${esc(r.symbol)} · ${esc(r.name || 'Unavailable')}</label><button class="btn ghost" onclick="researchExploreInspect(${esc(JSON.stringify(researchKey(r)))},this)">Inspect ${esc(r.symbol)} at coordinate</button></li>`).join('')}</ul><div class="explore-point-pages"><button class="btn ghost" onclick="researchExplorePointPage(-1)" ${offset===0?'disabled':''}>Previous coordinate stocks</button><span>${offset+1}–${Math.min(offset+50,rows.length)} of ${rows.length}</span><button class="btn ghost" onclick="researchExplorePointPage(1)" ${offset+50>=rows.length?'disabled':''}>Next coordinate stocks</button></div></section>`;
}
function researchExplorePointOpen(group,origin) {
 const st=researchExploreState();st.plotCode=researchKey(group.rows[0]);
 if(group.rows.length===1){st.pointCodes=null;researchExplorePointPicker();researchExploreInspect(st.plotCode,origin);return;}
 st.pointCoordinate={x:Number(group.rows[0][st.x]),y:Number(group.rows[0][st.y])};st.pointCodes=group.rows.map(researchKey);st.pointOffset=0;researchExplorePointPicker();
 document.getElementById('explore-point-picker')?.scrollIntoView?.({block:'start'});
 document.querySelector('#explore-point-picker button')?.focus();
}
function researchExplorePointClose(){researchExploreState().pointCodes=null;researchExplorePointPicker();document.getElementById('research-scatter')?.focus();}
function researchExplorePointPage(direction){const st=researchExploreState();st.pointOffset=(st.pointOffset || 0)+direction*50;researchExplorePointPicker();document.querySelector('#explore-point-picker button')?.focus();}
function researchExploreKeyboard(groups,st,key) {
 if(!groups.length)return null;
 let index=groups.findIndex(g=>g.rows.some(r=>researchKey(r)===st.plotCode));
 if(key==='Home')index=0;else if(key==='End')index=groups.length-1;
 else if(['ArrowRight','ArrowDown'].includes(key))index=index<0?0:Math.min(index+1,groups.length-1);
 else if(['ArrowLeft','ArrowUp'].includes(key))index=index<0?0:Math.max(index-1,0);
 else if(key==='Enter')index=index<0?0:index;else return null;
 st.plotCode=researchKey(groups[index].rows[0]);return groups[index];
}
function researchPlot(rows) {
 const canvas=document.getElementById('research-scatter');if(!canvas)return;
 const st=researchExploreState(),model=researchExploreModel(rows,st),ctx=canvas.getContext('2d'),w=Math.max(300,canvas.clientWidth),h=300,p=56;canvas.width=w;canvas.height=h;
 ctx.fillStyle='#0d1826';ctx.fillRect(0,0,w,h);ctx.font='11px system-ui';ctx.fillStyle='#b4c8e1';
 if(!model.xd || !model.yd){ctx.fillText([st.x,st.y].includes('market_cap')?'No eligible caps in the chosen attributed currency.':'No finite values for the chosen axes/scale.',p,h/2);return;}
 const transform=(v,scale)=>scale==='log'?Math.log10(v):v,inverse=(v,scale)=>scale==='log'?10**v:v;
 const xlo=transform(model.xd.min,st.xs),xhi=transform(model.xd.max,st.xs),ylo=transform(model.yd.min,st.ys),yhi=transform(model.yd.max,st.ys);
 const pos=(v,axis)=>{const x=axis==='x',lo=x?xlo:ylo,hi=x?xhi:yhi;const ratio=(transform(v,st[axis+'s'])-lo)/(hi-lo);return x?p+ratio*(w-2*p):h-p-ratio*(h-2*p);};
 const value=(v,axis)=>{const x=axis==='x',ratio=x?(v-p)/(w-2*p):(h-p-v)/(h-2*p);return inverse((x?xlo:ylo)+ratio*((x?xhi:yhi)-(x?xlo:ylo)),st[axis+'s']);};
 const encoding=researchExploreEncoding(rows,model),radius=r=>st.size==='cap' && encoding.capReady?Math.max(3,12*Math.sqrt(r.market_cap/encoding.maxCap)):3;
 const points=model.plotted.map(r=>({r,px:pos(Number(r[st.x]),'x'),py:pos(Number(r[st.y]),'y')}));
 const groups=researchExplorePointGroups(rows,st).map(g=>({...g,px:pos(g.x,'x'),py:pos(g.y,'y')}));
 const draw=()=>{ctx.fillStyle='#0d1826';ctx.fillRect(0,0,w,h);for(let i=0;i<=4;i++){const xp=p+i/4*(w-2*p),yp=h-p-i/4*(h-2*p);ctx.strokeStyle='#25364b';ctx.beginPath();ctx.moveTo(xp,p);ctx.lineTo(xp,h-p);ctx.moveTo(p,yp);ctx.lineTo(w-p,yp);ctx.stroke();ctx.fillStyle='#b4c8e1';ctx.textAlign='center';ctx.fillText(researchValue(st.x,value(xp,'x')),xp,h-p+18);ctx.textAlign='right';ctx.fillText(researchValue(st.y,value(yp,'y')),p-6,yp+4);}
 ctx.textAlign='center';ctx.fillText(SCR_COLS[st.x][0]+(st.x==='market_cap'?' · '+st.capCurrency:''),w/2,h-8);ctx.save();ctx.translate(12,h/2);ctx.rotate(-Math.PI/2);ctx.fillText(SCR_COLS[st.y][0]+(st.y==='market_cap'?' · '+st.capCurrency:''),0,0);ctx.restore();
 if(st.bounds){const b=st.bounds;const left=Math.max(p,b.x.min==null?p:pos(b.x.min,'x')),right=Math.min(w-p,b.x.max==null?w-p:pos(b.x.max,'x')),top=Math.max(p,b.y.max==null?p:pos(b.y.max,'y')),bottom=Math.min(h-p,b.y.min==null?h-p:pos(b.y.min,'y'));if([left,right,top,bottom].every(Number.isFinite) && right>=left && bottom>=top){ctx.fillStyle='#268bff22';ctx.fillRect(left,top,right-left,bottom-top);ctx.strokeStyle='#72b9ff';ctx.strokeRect(left,top,right-left,bottom-top);}}
 const selected=new Set(model.selected.map(researchKey));for(const pt of points){ctx.fillStyle=researchExploreSectorColor(researchExploreSector(pt.r));ctx.globalAlpha=.75;ctx.beginPath();ctx.arc(pt.px,pt.py,radius(pt.r),0,Math.PI*2);ctx.fill();if(st.bounds && selected.has(researchKey(pt.r))){ctx.strokeStyle='#fff';ctx.stroke();}}ctx.globalAlpha=1;const active=points.find(pt=>researchKey(pt.r)===st.plotCode);if(active){ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.beginPath();ctx.arc(active.px,active.py,radius(active.r)+4,0,Math.PI*2);ctx.stroke();ctx.lineWidth=1;}};draw();
 const at=e=>{const rect=canvas.getBoundingClientRect();return {x:Math.max(p,Math.min(w-p,(e.clientX-rect.left)*w/rect.width)),y:Math.max(p,Math.min(h-p,(e.clientY-rect.top)*h/rect.height))};};
 const nearest=q=>{let best=null,dist=144;for(const group of groups){const d=(group.px-q.x)**2+(group.py-q.y)**2;if(d<dist){best=group;dist=d;}}return best;};let start=null,lastHover=null;
 const announce=group=>{const el=document.getElementById('research-plot-selection');if(el)el.textContent=group?group.rows.length+' stock'+(group.rows.length===1?'':'s')+' · '+SCR_COLS[st.x][0]+': '+researchValue(st.x,group.x)+' · '+SCR_COLS[st.y][0]+': '+researchValue(st.y,group.y)+' · '+group.rows[0].symbol+' · '+researchExploreSector(group.rows[0])+' · Enter or click to inspect':'Arrow keys browse coordinates; Enter opens stocks at that point. Drag a region or use numeric bounds.';};
 canvas.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();researchExplorePointClose();return;}const group=researchExploreKeyboard(groups,st,e.key);if(!group)return;e.preventDefault();announce(group);draw();if(e.key==='Enter')researchExplorePointOpen(group,canvas);};
 canvas.onfocus=()=>{const group=groups.find(g=>g.rows.some(r=>researchKey(r)===st.plotCode));if(group){announce(group);draw();}};

 canvas.onpointerdown=e=>{if(e.button!==0)return;start=at(e);canvas.setPointerCapture(e.pointerId);};
 canvas.onpointermove=e=>{const q=at(e);if(start){draw();ctx.strokeStyle='#72b9ff';ctx.strokeRect(start.x,start.y,q.x-start.x,q.y-start.y);}else{const group=nearest(q),code=group && researchKey(group.rows[0]);if(code!==lastHover){lastHover=code;announce(group);}}};
 canvas.onpointerup=e=>{if(!start)return;const q=at(e),origin=start;start=null;canvas.releasePointerCapture(e.pointerId);if(Math.hypot(q.x-origin.x,q.y-origin.y)>8){st.pointCodes=null;st.plotCode=null;st.bounds={x:{min:value(Math.min(q.x,origin.x),'x'),max:value(Math.max(q.x,origin.x),'x')},y:{min:value(Math.max(q.y,origin.y),'y'),max:value(Math.min(q.y,origin.y),'y')}};st.zoom=false;st.limit=100;st.formOpen=false;st.preview=false;researchExploreMount();}else{const group=nearest(q);if(group){announce(group);researchExplorePointOpen(group,canvas);draw();}}};
 canvas.onpointercancel=()=>{start=null;draw();};
}
const RESEARCH_RANGES = {
 '1M':{request:'Q',days:31,interval:'Daily'},'3M':{request:'Q',days:93,interval:'Daily'},
 '6M':{request:'6M',days:186,interval:'Daily'},'1Y':{request:'Y',days:366,interval:'Daily'},
 '5Y':{request:'W',days:1827,interval:'Weekly'}
};
const RESEARCH_PERCENT_FIELDS=new Set(['pct','turnover_rate','div_yield','amplitude','bid_ask_ratio','roe','roe_yoy','roa','gross_margin','operating_margin','net_margin','revenue_growth','net_profit_growth','eps_growth','debt_ratio','lt_debt_eq','total_debt_eq','short_float','inst_own','insider_own','payout_ratio','sma20_pos','sma50_pos','sma200_pos','perf_w','perf_m','perf_q','perf_h','perf_y','perf_ytd','vol_w','vol_m','pos_52w']);
const RESEARCH_CURRENCY_FIELDS=new Set(['price','chg','open','high','low','high52','low52','market_cap','float_cap','turnover','eps','div_ttm','target_price','op_ebt']);
function researchFieldCurrency(row,field) {
 if(!RESEARCH_CURRENCY_FIELDS.has(field))return '';
 const code=row?.code,value=row?.[field],o=row?.field_observations?.[field];
 if(typeof code!=='string' || !/^(US|HK)\.[A-Z0-9][A-Z0-9._-]{0,30}$/.test(code) || typeof value!=='number' || !Number.isFinite(value))return '';
 return o && o.code===code && o.field===field && o.unit==='currency' && typeof o.value==='number' && Number.isFinite(o.value) && o.value===value && typeof o.currency==='string' && /^[A-Z]{3}$/.test(o.currency)?o.currency:'';
}
function researchMoneyValue(row,field) {
 const value=researchValue(field,row?.[field]);if(value==='Unavailable')return value;
 const currency=researchFieldCurrency(row,field);
 return currency?currency+' '+value:value+' · currency unavailable';
}
function researchMoneyHTML(row,field) {
 const value=researchValue(field,row?.[field]);if(value==='Unavailable')return esc(value);
 const currency=researchFieldCurrency(row,field);
 return (currency?esc(currency)+' ':'')+esc(value)+(currency?'':' <abbr title="Currency not supplied for this value" aria-label="Currency not supplied for this value">cur?</abbr>');
}
function researchValue(field,value,currency) {
 if(typeof value!=='number' || !Number.isFinite(value))return 'Unavailable';
 const n=Number(value),precision=Math.abs(n)>0 && Math.abs(n)<0.01?Math.min(12,Math.ceil(-Math.log10(Math.abs(n)))+2):2,short=n.toLocaleString('en-US',{maximumFractionDigits:precision});
 if(['price','chg','high52','low52'].includes(field))return fmtAuto(n);
 if(RESEARCH_PERCENT_FIELDS.has(field))return short+'%';
 if(['market_cap','float_cap','turnover'].includes(field)){
  const a=Math.abs(n),scale=a>=1e12?1e12:a>=1e9?1e9:a>=1e6?1e6:a>=1e3?1e3:1;
  return (currency?currency+' ':'')+(n/scale).toLocaleString('en-US',{maximumFractionDigits:2})+({[1e12]:'T',[1e9]:'B',[1e6]:'M',[1e3]:'K'}[scale] || '');
 }
 if(field==='volume')return n.toLocaleString('en-US',{maximumFractionDigits:0})+' shares';
 return short;
}
function researchDisplayField(field,value) {
 if(value==null || value==='')return 'Unavailable';
 const kind=SCR_COLS[field]?.[1];
 if(kind==='bool')return [true,1,'1'].includes(value)?'Yes':[false,0,'0'].includes(value)?'No':'Unavailable';
 if(['text','multi','symbol','date'].includes(kind))return Array.isArray(value)?value.filter(v=>typeof v==='string' || typeof v==='number').join(', ') || 'Unavailable':typeof value==='object'?'Unavailable':String(value);
 return researchValue(field,value);
}
function researchScreenValuesHTML(row,field,st=window.__scr) {
 if(!st.activePreset)return '';
 const original=(window.__scrPresets || []).find(p=>p.key===st.activePreset)?.filters || window.__presetCache?.[st.activePreset+'|'+st.market]?.payload?.filters;
 if(!Array.isArray(original))return '';
 const same=(a,b)=>JSON.stringify(researchStable(a))===JSON.stringify(researchStable(b));
 const criteria=(st.filters || []).filter(f=>f.field===field && original.some(o=>same(o,f)));
 return criteria.map(f=>{
  const e=researchEvidence(row,f,st.activePreset),windowLabel=f.days?' · '+f.days+'-day':'';
  return `<small class="screen-value">Screen${esc(windowLabel)}: ${esc(e.value==='Numeric evidence unavailable'?'Unavailable':e.value)}</small>`;
 }).join('');
}
function researchEvidence(row,filter,preset) {
 const field=filter.field,original=preset?((window.__scrPresets || []).find(p=>p.key===preset)?.filters || window.__presetCache?.[preset+'|'+window.__scr.market]?.payload?.filters):null;
 const same=(a,b)=>JSON.stringify(researchStable(a))===JSON.stringify(researchStable(b));
 const provider=!!preset && (!original || original.some(c=>same(c,filter)));
 const records=provider && Array.isArray(row.criterion_evidence)?row.criterion_evidence.filter(e=>e?.code===row.code && same(e.criterion,filter)):null;
 const record=records?.length===1?records[0]:null;
 const value=provider?(records?record?.value:row.criterion_values?.[field]):row[field];
 const numeric=typeof value==='number' && Number.isFinite(value);
 const terms=[];
 if(filter.min!=null)terms.push((filter.excl_min?'> ':'≥ ')+researchValue(field,filter.min));
 if(filter.max!=null)terms.push((filter.excl_max?'< ':'≤ ')+researchValue(field,filter.max));
 if(filter.values)terms.push(filter.values.join(', '));
 const financial=['roe','roe_yoy','revenue_growth','net_profit_growth','debt_ratio','gross_margin','net_margin','eps','eps_growth','op_ebt','op_profit_growth','div_yield','float_cap'].includes(field);
 const o=provider?null:row.field_observations?.[field],origin=row.display_field_sources?.[field];
 const attributed=o && o.code===row.code && o.field===field && o.value===value;
 const period=attributed && typeof o.period==='string' && o.period?o.period:'Reported period not supplied';
 const basis=filter.days?filter.days+'-day '+(field==='volume'?'average':'window')+' requested':provider && financial?'Annual financial basis requested':field==='pe_ttm'?'TTM definition':field==='forward_pe'?'Forward estimate definition':'No reporting basis supplied';
 const source=provider?'Moomoo screen criterion':({yfinance:'yfinance cached factor',computed_technicals:'Computed technical factor',provider_screen:'Moomoo screen value',stored_generation:'Stored quote generation',legacy_cache:'Stored quote cache',live_snapshot:'Snapshot quote'})[origin?.source] || (attributed && typeof o.source==='string'?o.source:'Source not supplied');
 const stamp=provider?record?.retrieved_at || row.criterion_retrieved_at:origin?.cache_at || origin?.retrieved_at || (attributed?o.observed_at:null);
 const categorical=!provider && Array.isArray(filter.values) && (typeof value==='string' || typeof value==='boolean' || Array.isArray(value));
 let shown=numeric?researchValue(field,value):categorical?researchDisplayField(field,value):'Numeric evidence unavailable';
 if(numeric && RESEARCH_CURRENCY_FIELDS.has(field))shown=provider?shown+' · currency not supplied':researchMoneyValue(row,field);
 const passes=numeric?(filter.min==null || (filter.excl_min?value>filter.min:value>=filter.min)) && (filter.max==null || (filter.excl_max?value<filter.max:value<=filter.max)):null;
 const display=provider?(RESEARCH_CURRENCY_FIELDS.has(field)?researchMoneyValue(row,field):researchDisplayField(field,row[field])):null;
 return {label:SCR_COLS[field]?.[0] || SCR_FIELDS[field] || field,value:shown,display_value:display,threshold:terms.join(' and '),basis,period,source,
  timestamp:stamp?researchCaptureTime(stamp):'Source/retrieval time not supplied',
  status:numeric?(passes?'Supplied value passes these bounds; period/source qualification is separate':'Supplied value does not pass these bounds; review current evidence'):categorical?'Stored classification supplied':provider?'Provider screen membership; criterion value unavailable':'Value unavailable'};
}

function researchCompanyContextHTML(payload,code,now=Date.now()) {
 const qualified=field=>{const value=payload?.fields?.[field],origin=payload?.origins?.[field],stamp=Date.parse(origin?.cache_at),age=now-stamp;return payload?.code===code && typeof value==='string' && value.trim() && origin?.source==='yfinance' && typeof origin.cache_at==='string' && /(Z|[+-]\d{2}:\d{2})$/.test(origin.cache_at) && Number.isFinite(stamp) && age>=0 && age<=7*86400000?value.trim():null;};
 const sector=qualified('sector'),industry=qualified('industry'),site=qualified('website');let url;
 try{const parsed=new URL(site);if(['http:','https:'].includes(parsed.protocol) && !parsed.username && !parsed.password && parsed.hostname)url=parsed;}catch(e){}
 const dates=[['sector','Sector',sector],['industry','Industry',industry],['website','Website',url]].map(([field,label,value])=>value?`<p>${label} · yfinance · retrieved <time datetime="${esc(payload.origins[field].cache_at)}">${esc(researchCaptureTime(payload.origins[field].cache_at))}</time></p>`:`<p>${label}: qualified source/retrieval time unavailable</p>`).join('');
 return `<section class="inspector-company" aria-label="Company context"><h4>Company context</h4><dl><dt>Sector</dt><dd>${esc(sector || 'Unavailable')}</dd><dt>Industry</dt><dd>${esc(industry || 'Unavailable')}</dd><dt>Website</dt><dd>${url?`<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${esc(url.hostname)}</a>`:'Unavailable'}</dd></dl><details class="company-source-details"><summary>Company source &amp; retrieval dates</summary>${dates}<p>Retrieval time is not a financial reporting period. These current cached classifications are separate from provider lists and the screen's quote generation.</p></details></section>`;
}
async function researchCompanyMount(code,gen) {
 const cache=window.__researchCompanyCache || (window.__researchCompanyCache=new Map());let entry=cache.get(code);
 try{
  if(!entry || Date.now()-entry.at>30000){const payload=await api('/api/screener/company-context?code='+encodeURIComponent(code));entry={payload,at:Date.now()};if(payload?.code===code){if(cache.size>=128 && !cache.has(code))cache.delete(cache.keys().next().value);cache.set(code,entry);}}
  if(gen!==window.__inspectGen || window.__researchInspectCode!==code)return;
  const target=document.getElementById('inspect-company');if(target)target.innerHTML=researchCompanyContextHTML(entry.payload,code);
 }catch(e){if(gen===window.__inspectGen && window.__researchInspectCode===code){const target=document.getElementById('inspect-company');if(target)target.textContent='Company context unavailable. Reopen Overview to retry.';}}
}
function researchDisposeInspector() {
 researchModalRelease('inspector');
 window.__inspectGen=(window.__inspectGen || 0)+1;
 window.__inspectResize?.disconnect();window.__inspectResize=null;
 if(window.__inspectChart){try{window.klinecharts.dispose('inspect-chart');}catch(e){}window.__inspectChart=null;}
}
function researchCloseInspector(restore=true) {
 const changeCode=window.__researchChangeCode,changeRow=window.__changePayload?.rows?.find(r=>r.code===changeCode);
 researchDisposeInspector();window.__researchInspectCode=null;window.__researchChangeCode=null;
 document.getElementById('research-inspector')?.classList.remove('open');
 const origin=window.__inspectOrigin;if(restore && origin?.isConnected && origin.getClientRects().length)origin.focus({preventScroll:true});
 else if(restore){const label=changeCode?'Review '+(changeRow?.symbol || changeCode)+' snapshot evidence':'Inspect '+window.__inspectRow?.symbol;[...document.querySelectorAll('button[aria-label]')].find(b=>b.getAttribute('aria-label')===label && b.getClientRects().length)?.focus({preventScroll:true});}
}
function researchInspectorTab(tab) {
 if(!['overview','why','news'].includes(tab))return;
 window.__inspectTab=tab;researchInspectRow(window.__inspectRow,{focusControl:'tab'});
}
function researchInspectorRange(range) {
 if(!RESEARCH_RANGES[range])return;
 window.__inspectRange=range;researchInspectRow(window.__inspectRow,{focusControl:'range'});
}
async function researchInspect(i,origin) {
 const row=researchVisibleRows()[i];if(!row)return;
 window.__inspectOrigin=origin || [...document.querySelectorAll('button[aria-label]')].find(b=>b.getAttribute('aria-label')==='Inspect '+row.symbol && b.getClientRects().length) || document.activeElement;await researchInspectRow(row,{focus:true});
}
function researchQuoteCurrency(row) {
 return typeof row?.currency==='string' && /^(USD|HKD|CNY|CNH|JPY|AUD|CAD|EUR|GBP|CHF|SGD)$/.test(row.currency)?row.currency:'';
}
function researchQuoteProvenance(row) {
 const valid=t=>typeof t==='string' && /(Z|[+-]\d{2}:\d{2})$/.test(t) && Number.isFinite(Date.parse(t));
 const source=row.quote_time_semantics==='provider_snapshot_update' && valid(row.quote_observed_at)?researchCaptureTime(row.quote_observed_at):'Unavailable';
 const cache=row.quote_cache_at || row.updated_at;
 const sources=row.display_field_sources;
 const display=sources?`<details><summary>Displayed value sources</summary><p>Screen membership and rule values are from the provider screening response. Quote fills may have different source times.</p>${['price','pct','market_cap','stock_type'].map(field=>{const origin=sources[field];if(!origin)return '';const label={provider_screen:'Provider screen',stored_generation:'Stored generation',legacy_cache:'Legacy cache',live_snapshot:'Live snapshot',provider_basicinfo:'Provider classification'}[origin.source] || 'Unverified';return `<p>${esc(SCR_COLS[field]?.[0] || field)}: ${esc(label)}${origin.generation_id?' · '+esc(origin.generation_id):''} · ${esc(researchCaptureTime(origin.cache_at || origin.retrieved_at))}</p>`;}).join('')}</details>`:'';
 return `<div class="inspector-provenance"><strong>Data context</strong><p>Provider snapshot updated: ${esc(source)}<br>Cache updated: ${esc(valid(cache)?researchCaptureTime(cache):'Unavailable')}<br>Price currency: ${esc(researchFieldCurrency(row,'price') || 'Not supplied')} · ${sources?'Moomoo screen / quote display':window.__scr.src==='yf'?'Moomoo quotes / supplemental factors':'Moomoo stored quote'}<br>Snapshot update is not last-trade time. Session, adjustment and delay are not verified.</p>${display}</div>`;
}
function researchInspectorKey(event) {
 if(window.matchMedia?.('(max-width:1350px)').matches)researchModalKey(event,document.getElementById('research-inspector'),()=>researchCloseInspector());
 else if(event.key==='Escape'){event.preventDefault();researchCloseInspector();}
}
async function researchInspectRow(row,options={}) {
 const el=document.getElementById('research-inspector');if(!el || !row)return;
 const code=researchKey(row),changed=window.__researchInspectCode!==code;
 if(changed){window.__inspectTab='overview';window.__inspectRange='3M';}
 researchDisposeInspector();const gen=window.__inspectGen;
 window.__researchInspectCode=code;window.__inspectRow=row;
 const tab=window.__inspectTab || 'overview',range=window.__inspectRange || '3M',currency=researchQuoteCurrency(row);
 const privateItem=state.page==='shortlists'?(window.__researchListItems || []).find(r=>r.code===code):null;window.__researchPrivateInspect=!!privateItem;
 const filters=privateItem?[]:scrEffFilters(false),watched=(window.__scr.watchlistSyms || []).includes(row.symbol);
 const call=value=>esc(JSON.stringify(value));
 const tabs=[['overview','Overview'],['why',privateItem?'List context':'Why it matches'],['news','News']];
 const evidence=filters.map(f=>researchEvidence(row,f,window.__scr.activePreset));
 const provenance=researchQuoteProvenance(row);
 const why=privateItem?`<h4>Research shortlist</h4><p>${esc(privateItem.review_status.replaceAll('_',' '))}</p><p>${esc(privateItem.note || 'No note')}</p><p>List membership does not establish qualification for the current screener criteria.</p>`:filters.length?`<div class="inspector-evidence">${evidence.map(e=>`<section><h4>${esc(e.label)}</h4><strong>${esc(e.value)}</strong>${e.display_value!==null?`<p>Table display: ${esc(e.display_value)}. This is separate from the screen criterion observation.</p>`:''}<p>Rule: ${esc(e.threshold || 'Provider definition')}<br>${esc(e.basis)}<br>${esc(e.period)}<br>${esc(e.source)} · ${esc(e.timestamp)}</p><small>${esc(e.status)}</small></section>`).join('')}</div>`:'<p>All stocks — no custom criteria. This stock is in the current stock-only universe.</p>';
 el.classList.add('open');el.setAttribute('role',window.matchMedia?.('(max-width:1350px)').matches?'dialog':'complementary');el.setAttribute('aria-label',row.symbol+' stock inspector');
 if(window.matchMedia?.('(max-width:1350px)').matches)el.setAttribute('aria-modal','true');else el.removeAttribute('aria-modal');
 el.onkeydown=researchInspectorKey;
 el.innerHTML=`<div class="inspector-heading"><div><h2>${esc(row.symbol)}</h2><p>${esc(row.name)}</p></div><button class="btn ghost inspector-close" onclick="researchCloseInspector()">Close preview</button></div><div class="inspector-price">${researchMoneyHTML(row,'price')}<small class="${Number(row.pct)>=0?'g':'r'}">${esc(researchValue('pct',row.pct))}</small></div><div class="inspector-tabs" role="group" aria-label="Inspector section">${tabs.map(([id,label])=>`<button class="btn ${tab===id?'primary':'ghost'}" aria-pressed="${tab===id}" onclick="researchInspectorTab('${id}')">${label}</button>`).join('')}</div><div class="inspector-scroll"><div id="inspector-content">${tab==='overview'?`<dl class="inspector-key-metrics" aria-label="Quote metrics">${['market_cap','pe_ttm','pb','volume','high52','low52'].map(k=>`<dt>${esc(SCR_COLS[k]?.[0] || k)}</dt><dd>${RESEARCH_CURRENCY_FIELDS.has(k)?researchMoneyHTML(row,k):esc(researchValue(k,row[k]))}</dd>`).join('')}</dl><div id="inspect-company" role="status">Loading cached company context…</div><div id="inspect-chart" aria-label="${esc(row.symbol)} price history" style="height:220px"></div><div class="inspector-ranges" role="group" aria-label="Chart range">${Object.keys(RESEARCH_RANGES).map(r=>`<button class="btn ${range===r?'primary':'ghost'}" aria-pressed="${range===r}" onclick="researchInspectorRange('${r}')">${r}</button>`).join('')}</div><p id="inspect-chart-status" role="status">Loading ${range} history…</p><h4>${privateItem?'List context':'Screen context'}</h4><p>${privateItem?'Research shortlist · see List context':filters.length?filters.length+' criteria · see Why it matches':'All stocks — no custom criteria'}</p>`:tab==='why'?why:'<div id="inspect-news" role="status">Loading recent news…</div>'}</div>${provenance}</div><div class="inspector-actions"><button class="btn ghost" onclick="researchShortlistPicker(${call(code)})">Add to shortlist</button><button class="btn ghost" onclick="toggleWatch(${call(row.symbol)})" ${window.__watchPending?.has(row.symbol)?'disabled':''}>${watched?'Remove from watchlist':'Add to watchlist'}</button><button class="btn primary" onclick="researchOpen(${call(code)})">Open full research</button></div><p class="faint">All stock tabs and KLine tools remain in full research.</p>`;
 if(window.matchMedia?.('(max-width:1350px)').matches)researchModalIsolate(el,'inspector');
 if(options.focus)el.querySelector('.inspector-close')?.focus({preventScroll:true});
 if(options.focusControl)el.querySelector(options.focusControl==='tab'?'.inspector-tabs [aria-pressed="true"]':'.inspector-ranges [aria-pressed="true"]')?.focus({preventScroll:true});
 if(tab==='news'){
  try{
   const data=await api('/api/stock/'+encodeURIComponent(code)+'/news?type=news&limit=8');
   if(gen!==window.__inspectGen || window.__researchInspectCode!==code)return;
   const items=data?.news_list || data?.news || [],target=document.getElementById('inspect-news');if(!target)return;
   target.innerHTML=data?.available===false?`<p>${esc(data.reason || 'News unavailable')}</p>`:items.length?items.slice(0,8).map(n=>{
    let url='';try{const u=new URL(n.url);if(['https:','http:'].includes(u.protocol))url=u.href;}catch(e){}
    const title=esc(String(n.title || 'Untitled').replace(/<\/?em>/g,''));
    return `<article class="inspector-news">${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${title}</a>`:title}<small>${n.publish_time?esc(stkTime(Number(n.publish_time)*1000)):'Publication time unavailable'}</small></article>`;
   }).join(''):'<p>No recent news returned by the provider.</p>';
  }catch(e){if(gen===window.__inspectGen)document.getElementById('inspect-news').textContent='News unavailable. Retry by reopening News.';}
  return;
 }
 if(tab!=='overview')return;
 researchCompanyMount(code,gen);
 const config=RESEARCH_RANGES[range];
 try{
  const data=await api('/api/stock/'+encodeURIComponent(code)+'/candles?range='+config.request);
  if(gen!==window.__inspectGen || window.__researchInspectCode!==code)return;
  const target=document.getElementById('inspect-chart'),status=document.getElementById('inspect-chart-status');if(!target || !status)return;
  const bars=researchInspectorBars(data,config.days);
  if(data?.available===false || !bars.length){target.innerHTML='<p>Preview history unavailable. Full research retains chart controls.</p>';status.textContent=data?.reason || 'No valid bars returned';return;}
  const chart=window.klinecharts.init('inspect-chart');window.__inspectChart=chart;klineTheme(chart);chart.setStyles({candle:{tooltip:{showRule:'follow_cross',custom:[{title:'time',value:'{time}'},{title:'close',value:'{close}'}]}}});chart.applyNewData(bars);
  const fit=()=>{if(window.__inspectChart!==chart)return;chart.resize();chart.setBarSpace(Math.max(2,Math.min(12,(target.clientWidth-65)/bars.length)));};fit();
  if(typeof ResizeObserver!=='undefined'){window.__inspectResize=new ResizeObserver(fit);window.__inspectResize.observe(target);}
  const date=t=>new Date(t).toISOString().slice(0,10);
  status.textContent=config.interval+' interval requested · '+date(bars[0].timestamp)+' to '+date(bars.at(-1).timestamp)+' · '+bars.length+' bars · regular session request · adjustment/completeness not supplied';
 }catch(e){if(gen===window.__inspectGen){const target=document.getElementById('inspect-chart-status');if(target)target.textContent='History unavailable. Retry by choosing a range.';}}
}
function researchInspectorBars(data,days) {
 const now=Date.now(),cutoff=now-days*86400000,byTime=new Map();
 for(const b of data?.bars || data?.candles || []){
  const raw=b.time_key ?? b.time ?? b.timestamp ?? b.t;
  const timestamp=typeof raw==='number'?(raw<1e11?raw*1000:raw):Date.parse(raw);
  if([b.open??b.o,b.high??b.h,b.low??b.l,b.close??b.c].some(v=>v==null || v===''))continue;
  const rawVolume=b.volume??b.v;
  const row={timestamp,open:Number(b.open??b.o),high:Number(b.high??b.h),low:Number(b.low??b.l),close:Number(b.close??b.c)};
  if(rawVolume!=null && rawVolume!=='')row.volume=Number(rawVolume);
  if(timestamp>=cutoff && timestamp<=now && [timestamp,row.open,row.high,row.low,row.close].every(Number.isFinite) && row.low>0 && row.low<=Math.min(row.open,row.close) && row.high>=Math.max(row.open,row.close) && row.low<=row.high && (row.volume==null || (Number.isFinite(row.volume) && row.volume>=0)))byTime.set(timestamp,row);
 }
 return [...byTime.values()].sort((a,b)=>a.timestamp-b.timestamp);
}
function researchDefinition() {const s=window.__scr;return {market:s.market,src:s.src || 'moo',etfs:!!s.etfs,watchlist_only:!!s.watchlistOnly,filters:scrEffFilters(),preset:s.activePreset || null};}
function researchErrorMessage(error) {
 const text=String(error?.message || error || 'Request unavailable');
 try{const data=JSON.parse(text);return typeof data.detail==='string'?data.detail:'Please check the requested inputs.';}catch(e){return text;}
}
function researchChangeState() {
 const key=JSON.stringify(researchStable(researchDefinition()));
 if(window.__changeState?.key!==key)window.__changeState={key,status:'new',q:'',sort:'symbol',direction:1,offset:0,limit:100,previous_id:'',current_id:'',history_offset:0,review_status:'all'};
 return window.__changeState;
}
function researchChangeHeader(title,st) {
 return `<div class="change-context"><div class="change-heading"><h2>Changes in ${esc(title)}</h2><div class="research-modes" role="group" aria-label="Result presentation">${['table','explore','changes'].map(v=>`<button class="btn ${v==='changes'?'primary':'ghost'}" aria-pressed="${v==='changes'}" onclick="researchMode('${v}')">${v[0].toUpperCase()+v.slice(1)}</button>`).join('')}</div><button class="btn primary" data-capture onclick="researchSnapshot()" ${window.__snapshotBusy?'disabled':''}>Capture snapshot</button></div><p>${esc(st.market)} · ${st.etfs?'Stocks + ETFs':'ETFs excluded'} · compare captures of the same definition <button class="btn ghost library-open-control" onclick="researchLibraryOpen()">Screens</button><button class="btn ghost" onclick="researchMode('table')">Edit screen</button><button class="btn ghost desk-clear" onclick="scrResetAll()" title="All stocks excluding ETFs, sorted by market cap">Clear</button></p></div>`;
}
function researchChangesHTML() {
 return `<div id="research-change-results" aria-live="polite">Loading snapshot comparison…</div>`;
}
async function researchLoadChanges() {
 const el=document.getElementById('research-change-results');if(!el)return;
 const st=researchChangeState(),authGen=window.__researchAuthGen || 0,gen=(window.__changeGen || 0)+1;window.__changeGen=gen;window.__changeLoading=true;const exportButton=document.querySelector('.change-tools button');if(exportButton)exportButton.disabled=true;
 const qs=new URLSearchParams({definition:JSON.stringify(researchDefinition()),status:st.status,q:st.q,sort:st.sort,direction:st.direction,limit:st.limit,offset:st.offset,history_offset:st.history_offset || 0});
 for(const k of ['previous_id','current_id'])if(st[k])qs.set(k,st[k]);
 try{let d=await api('/api/screener/changes?'+qs);if(d.comparable && window.__researchSession){
  try{d=await researchPrivateAPI('/api/research/pair-reviews?'+researchPairQuery(d,st));}
  catch(e){if(e.status===499)return;d={...d,review_error:researchErrorMessage(e)};}
 }if(authGen!==(window.__researchAuthGen || 0) || gen!==window.__changeGen || document.getElementById('research-change-results')!==el)return;window.__changePayload=d;researchChangesRender(el,d);}
 catch(e){if(gen===window.__changeGen && document.getElementById('research-change-results')===el){researchChangesRender(el,{comparable:false,history:window.__changePayload?.history || [],history_has_more:window.__changePayload?.history_has_more,history_offset:window.__changePayload?.history_offset || 0,scope:window.__changePayload?.scope,reason:'Comparison unavailable: '+researchErrorMessage(e)});}}finally{if(gen===window.__changeGen){window.__changeLoading=false;const button=document.querySelector('.change-tools button');if(button)button.disabled=false;}}
}
function researchChangeSearch(input) {
 const st=researchChangeState();st.q=input.value;st.offset=0;window.__changeLoading=true;const button=document.querySelector('.change-tools button');if(button)button.disabled=true;window.__changeGen=(window.__changeGen || 0)+1;
 clearTimeout(window.__changeSearchTimer);window.__changeSearchTimer=setTimeout(()=>researchLoadChanges(),200);
}
function researchChangeSet(key,value) {
 const st=researchChangeState();if(!['status','q','sort','direction','previous_id','current_id','offset','history_offset','review_status'].includes(key))return;
 if(key==='review_status' && !['all','unreviewed','in_review','reviewed'].includes(value))return;
 st[key]=['direction','offset','history_offset'].includes(key)?Number(value):value;if(!['offset','history_offset'].includes(key))st.offset=0;
 researchLoadChanges();
}
function researchChangeCriteria(definition) {
 const filters=definition?.filters || [];return filters.map((c,i)=>({...c,criterion_key:'c'+i,sort_key:filters.filter(f=>f.field===c.field).length===1?c.field:'c'+i})).filter(c=>c.values==null && (c.min!=null || c.max!=null));
}
function researchChangeCriterionLabel(c) {
 return (SCR_COLS[c.field]?.[0] || SCR_FIELDS[c.field] || c.field)+(c.days?' · '+c.days+'d':'');
}
function researchCaptureClockLabel(clock) {
 return {provider_retrieval:'Provider retrieval',stored_universe:'Stored cache update',generation_publication:'Generation published'}[clock] || 'Time type unverified';
}
function researchCaptureTime(at) {
 if(!at)return 'Time unavailable';const d=new Date(at);if(!Number.isFinite(d.getTime()))return 'Time unavailable';
 return TZ()==='nz'?d.toLocaleString('en-NZ',{timeZone:'Pacific/Auckland',year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})+' NZ time':d.toISOString().slice(0,23).replace('T',' ')+' UTC';
}
function researchChangesRender(el,d) {
 const st=researchChangeState(),history=d.history || [],counts=d.counts || {new:d.added?.length || 0,exited:d.exited?.length || 0,all:(d.added?.length || 0)+(d.exited?.length || 0)+(d.unchanged || 0)};
 const provenanceOpen=!!el.querySelector?.('.change-provenance')?.open,focusHistory=document.activeElement?.getAttribute('data-history-page');
 const criteria=researchChangeCriteria(d.definition),sorts=[['symbol','Symbol'],['name','Company'],['status','Change status'],['market_cap','Captured market cap'],...criteria.flatMap(c=>['before','after'].map(side=>['criterion:'+side+':'+c.sort_key,researchChangeCriterionLabel(c)+' · '+side]))];
 const criterionHeaders=criteria.map(c=>`<th scope="col">${esc(researchChangeCriterionLabel(c))} before</th><th scope="col">${esc(researchChangeCriterionLabel(c))} after</th>`).join('');
 const criterionCells=r=>criteria.map(c=>`<td>${esc(researchDisplayField(c.field,researchCapturedCriterion(r.previous,c)))}</td><td>${esc(researchDisplayField(c.field,researchCapturedCriterion(r.current,c)))}</td>`).join('');
 const date=researchCaptureTime;
 const pairOptions=(key,selected)=>`<label>${key==='previous_id'?'Before':'After'}<select aria-label="${key==='previous_id'?'Previous snapshot':'Current snapshot'}" onchange="researchChangeSet('${key}',this.value)">${history.map(s=>`<option value="${esc(s.id)}" ${s.id===selected?'selected':''}>${esc(date(s.at))} · ${s.members} members · ${esc(s.id.slice(-8))}</option>`).join('')}</select></label>`;
 const historyPager=`<div class="change-history-pager"><span role="status">Retained capture page ${Math.floor((d.history_offset || 0)/100)+1} · ${d.scope==='deployment_owner'?'deployment-shared history':'history'}</span><button class="btn ghost" data-history-page="newer" ${!(d.history_offset>0)?'disabled':''} onclick="researchChangeSet('history_offset',Math.max(0,${(d.history_offset || 0)-100}))">Newer captures</button><button class="btn ghost" data-history-page="older" ${d.history_has_more?'':'disabled'} onclick="researchChangeSet('history_offset',${(d.history_offset || 0)+100})">Older captures</button></div>`;
 const pair=history.length>=2?`<div class="change-pair">${pairOptions('previous_id',d.previous_id || st.previous_id || history.at(-2).id)}${pairOptions('current_id',d.current_id || st.current_id || history.at(-1).id)}</div>`:'';
 if(!d.comparable){if(window.__researchChangeCode)researchCloseInspector(false);el.innerHTML=`${pair}${historyPager}<div class="change-setup"><h4>${history.length?'Baseline / comparison setup':'Start change monitoring'}</h4><p>${esc(d.reason || 'Capture a complete baseline, then another comparable snapshot.')}</p><p class="faint">Captures are retained as immutable records. Legacy deployment history remains shared; verified ownership and scheduled captures are still pending.</p></div>`;return;}
 st.previous_id=d.previous_id;st.current_id=d.current_id;
 const selectedCodes=new Set(researchChangeSelection(d,st).rows.map(r=>r.code));
 const focusTab=document.activeElement?.getAttribute('data-change-tab'),focusPage=document.activeElement?.getAttribute('data-change-page'),focused=document.activeElement?.getAttribute('aria-label'),selection=focused==='Search snapshot matches'?[document.activeElement.selectionStart,document.activeElement.selectionEnd]:null;
 el.innerHTML=`${pair}${researchPairToolsHTML(d,st)}<div id="research-change-selection">${researchChangeSelectionHTML(d,st)}</div><details class="change-provenance"><summary>Complete captured membership · source, definition and retained history</summary>${historyPager}<p>Capture time: ${esc(date(d.previous_at))} → ${esc(date(d.current_at))}. ${esc(researchCaptureClockLabel(d.previous_source_clock))}: ${esc(date(d.previous_source_at))} → ${esc(researchCaptureClockLabel(d.current_source_clock))}: ${esc(date(d.current_source_at))}. Quote source time is not established by these clocks.</p>${d.previous_generation_id || d.current_generation_id?`<p>Stored generations: ${esc(d.previous_generation_id || 'Legacy / unpinned')} → ${esc(d.current_generation_id || 'Legacy / unpinned')}.</p>`:''}<p>All matches is the union of both captures; it is not the current stock universe. Missing numeric evidence does not establish a cause.</p>${d.observation_coverage?.scope==='eligible_stored_universe'?`<p>Eligible observations: ${d.observation_coverage.previous} before · ${d.observation_coverage.current} after, including nonmembers.</p>`:'<p>Legacy captures contain member observations only.</p>'}${researchCriteriaDefinition(d.definition?.filters || [])}</details><div class="change-tabs" role="group" aria-label="Change cohort">${[['new','New matches'],['exited','Exited'],['all','All matches']].map(([key,label])=>`<button class="btn ${st.status===key?'primary':'ghost'}" aria-pressed="${st.status===key}" data-change-tab="${key}" onclick="researchChangeSet('status','${key}')">${label} (${counts[key] || 0})</button>`).join('')}</div><div class="change-tools"><label>Find a stock<input aria-label="Search snapshot matches" maxlength="100" value="${esc(st.q)}" placeholder="Symbol or company" oninput="researchChangeSearch(this)" onkeydown="if(event.key==='Enter'){event.preventDefault();clearTimeout(window.__changeSearchTimer);researchChangeSet('q',this.value)}"></label><label>Sort<select aria-label="Sort snapshot matches" onchange="researchChangeSet('sort',this.value)">${sorts.map(([key,label])=>`<option value="${key}" ${st.sort===key?'selected':''}>${label}</option>`).join('')}</select></label><select aria-label="Snapshot sort direction" onchange="researchChangeSet('direction',this.value)"><option value="1" ${st.direction===1?'selected':''}>Ascending</option><option value="2" ${st.direction===2?'selected':''}>Descending</option></select><button class="btn ghost" onclick="researchChangesExport()">Export comparison CSV</button></div><p role="status">${d.matched.toLocaleString()} matches in this review · ${counts.unchanged || 0} unchanged in the complete pair</p><div class="change-table"><table><thead><tr><th scope="col">Select</th><th>Status</th><th>Symbol</th><th>Company</th><th>Captured cap</th>${criterionHeaders}<th>Review status</th><th>Evidence</th></tr></thead><tbody>${(d.rows || []).map(r=>`<tr><td><label class="change-row-select"><input type="checkbox" data-change-code="${esc(r.code)}" aria-label="Select ${esc(r.symbol || r.code)} from comparison" ${selectedCodes.has(r.code)?'checked':''} onchange="researchChangeSelect(${esc(JSON.stringify(r.code))},this.checked)"></label></td><td>${r.status==='new'?'Entered':r.status==='exited'?'Exited':'Unchanged'}</td><td><a href="#" onclick="event.preventDefault();researchOpen(${esc(JSON.stringify(r.code))})">${esc(r.symbol || r.code)}</a></td><td>${esc(r.name || 'Unavailable')}</td><td>${esc(researchValue('market_cap',(r.current || r.previous)?.metrics?.market_cap))}</td>${criterionCells(r)}<td>${esc(d.review_scope==='private_capture_pair'?researchPairStatusLabel(r.review?.review_status):'Unavailable')}</td><td><button class="btn ghost" aria-label="Review ${esc(r.symbol || r.code)} snapshot evidence" onclick="researchChangeInspect(${esc(JSON.stringify(r.code))},this)">Review evidence</button></td></tr>`).join('') || `<tr><td colspan="${7+criteria.length*2}">No matches in this view. Change tabs or clear the search.</td></tr>`}</tbody></table></div><div class="change-pager"><button class="btn ghost" data-change-page="previous" ${st.offset<=0?'disabled':''} onclick="researchChangeSet('offset',Math.max(0,${st.offset-st.limit}))">Previous review page</button><span>${d.matched?st.offset+1:0}–${Math.min(d.matched,st.offset+(d.rows || []).length)} of ${d.matched}</span><button class="btn ghost" data-change-page="next" ${st.offset+(d.rows || []).length>=d.matched?'disabled':''} onclick="researchChangeSet('offset',${st.offset+st.limit})">Next review page</button></div><p class="faint">Membership changes are distinct from price moves. Before/after criterion evidence may be unavailable; no cause is inferred from missing values. All matches is the union of entered, exited and retained members. Review notes are private to this capture pair. Team review and scheduled captures remain pending.</p>`;
 if(provenanceOpen){const disclosure=el.querySelector('.change-provenance');if(disclosure)disclosure.open=true;}
 if(focusHistory){const target=el.querySelector('[data-history-page="'+focusHistory+'"]');const next=target && !target.disabled?target:el.querySelector('[data-history-page]:not([disabled])');next?.focus();}
 if(focusTab)el.querySelector('[data-change-tab="'+focusTab+'"]')?.focus();if(focusPage){const button=el.querySelector('[data-change-page="'+focusPage+'"]');if(button && !button.disabled)button.focus();}
 if(focused && ['Search snapshot matches','Sort snapshot matches','Snapshot sort direction','Previous snapshot','Current snapshot'].includes(focused)){const target=el.querySelector('[aria-label="'+focused+'"]');target?.focus();if(selection)target?.setSelectionRange(...selection);}
 if(window.__researchChangeCode){if(d.rows.some(r=>r.code===window.__researchChangeCode))researchChangeInspect(window.__researchChangeCode,null,false);else researchCloseInspector(false);}
}
function researchCriterionRule(c) {
 const parts=[];if(Array.isArray(c.values))parts.push(c.values.join(', '));if(c.min!=null)parts.push((c.excl_min?'> ':'≥ ')+researchDisplayField(c.field,c.min));if(c.max!=null)parts.push((c.excl_max?'< ':'≤ ')+researchDisplayField(c.field,c.max));return parts.join(' · ') || 'Provider definition';
}
function researchCriteriaDefinition(criteria) {
 if(!criteria.length)return '<p>No additional criteria in this definition.</p>';
 return `<div class="change-matrix"><table><caption>Screen definition</caption><thead><tr><th scope="col">Criterion</th><th scope="col">Rule</th></tr></thead><tbody>${criteria.map(c=>`<tr><th scope="row">${esc(researchChangeCriterionLabel(c))}</th><td>${esc(researchCriterionRule(c))}</td></tr>`).join('')}</tbody></table></div>`;
}
function researchCapturedCriterion(row,c) {
 const observation=row?.criterion_observations?.[c.criterion_key];return observation?observation.value:c.sort_key===c.field?row?.evidence?.[c.field]:undefined;
}
function researchPairedEvidenceLabel(e) {
 if(e.status==='comparable')return ({rule_entered:'Comparable observations · now meets this rule',rule_exited:'Comparable observations · no longer meets this rule',rule_retained:'Comparable observations · rule result retained'})[e.assessment] || 'Comparable observations';
 return e.previous!=null && e.current!=null?'Both values supplied · comparability unverified':'Paired values unavailable';
}
function researchObservationProvenance(e) {
 return ['previous','current'].map(side=>{const o=e[side+'_observation'];if(!o || !o.observed_at)return '';return `<p class="faint">${side==='previous'?'Before':'After'}: ${esc(o.currency || o.unit || 'Unit unavailable')} · ${esc(({quote_source:'Quote source',computed_bar_time:'Computed bar',financial_report:'Financial report'})[o.clock] || 'Time type unverified')} · ${esc(researchCaptureTime(o.observed_at))}</p>`;}).join('');
}
function researchCriterionMatrix(criteria,evidence,compact=false) {
 const entries=criteria.map((c,i)=>({criterion:c,...(evidence.find(e=>e.criterion_key==='c'+i || (e.criterion && JSON.stringify(researchStable(e.criterion))===JSON.stringify(researchStable(c))) || (!e.criterion_key && !e.criterion && e.field===c.field && criteria.filter(f=>f.field===c.field).length===1)) || {field:c.field,status:'unavailable_pair'})}));
 if(!entries.length)return '<p>No numeric criteria in this definition.</p>';
 const rule=researchCriterionRule;
 if(compact)return entries.map(e=>`<section class="change-evidence"><h4>${esc(SCR_COLS[e.field]?.[0] || SCR_FIELDS[e.field] || e.field)}</h4><p>Rule: ${esc(rule(e.criterion))}</p><table class="change-observation"><thead><tr><th scope="col">Before</th><th scope="col">After</th></tr></thead><tbody><tr><td>${esc(researchDisplayField(e.field,e.previous))}</td><td>${esc(researchDisplayField(e.field,e.current))}</td></tr></tbody></table><p>${esc(e.period || 'Period not supplied')} · ${esc(e.source || 'Source not supplied')} · ${esc(researchPairedEvidenceLabel(e))}</p>${researchObservationProvenance(e)}</section>`).join('');
 return `<div class="change-matrix"><table><caption>Captured criteria and paired observations</caption><thead><tr><th scope="col">Criterion</th><th scope="col">Rule</th><th scope="col">Before</th><th scope="col">After</th><th scope="col">Evidence</th></tr></thead><tbody>${entries.map(e=>`<tr><th scope="row">${esc(SCR_COLS[e.field]?.[0] || SCR_FIELDS[e.field] || e.field)}</th><td>${esc(rule(e.criterion))}</td><td>${esc(researchDisplayField(e.field,e.previous))}</td><td>${esc(researchDisplayField(e.field,e.current))}</td><td>${esc(e.period || 'Period not supplied')} · ${esc(e.source || 'Source not supplied')} · ${esc(researchPairedEvidenceLabel(e))}</td></tr>`).join('')}</tbody></table></div>`;
}
function researchChangeInspect(code,origin,focus=true) {
 const d=window.__changePayload,r=d?.rows?.find(x=>x.code===code),el=document.getElementById('research-inspector');if(!r || !el)return;
 researchDisposeInspector();window.__researchChangeCode=code;window.__researchInspectCode=null;window.__inspectOrigin=origin || window.__inspectOrigin;
 const modal=matchMedia('(max-width:1350px)').matches;el.classList.add('open');el.setAttribute('role',modal?'dialog':'complementary');el.setAttribute('aria-label',(r.symbol || code)+' snapshot evidence');if(modal){el.setAttribute('aria-modal','true');researchModalIsolate(el,'inspector');}else el.removeAttribute('aria-modal');
 const date=t=>t?fmtTs(t)+(TZ()==='nz'?' NZ time':''):'Time unavailable';
 el.innerHTML=`<div class="inspector-heading"><div><h2>${esc(r.symbol || code)}</h2><p>${esc(r.name || '')} · ${r.status==='new'?'Entered':r.status==='exited'?'Exited':'Unchanged'}</p></div><button class="btn ghost inspector-close" onclick="researchCloseInspector()">Close preview</button></div><div class="inspector-scroll">${researchPairFormHTML(d,r)}<h3>Snapshot evidence</h3><p>${esc(date(d.previous_at))} → ${esc(date(d.current_at))}</p><p>${esc(r.reason)}</p>${researchCriterionMatrix(d.definition?.filters || (r.evidence || []).map(e=>e.criterion || {field:e.field}),r.evidence || [],true)}<p class="faint">Eligible-universe captures retain nonmember observations. Legacy or missing observations cannot establish a numeric crossing; supplied values require compatible provenance. These are captured observations; full research loads the current stock view.</p></div><div class="inspector-actions"><button class="btn ghost" onclick="researchShortlistPicker(${esc(JSON.stringify(code))})">Add to shortlist</button><button class="btn primary" onclick="researchOpen(${esc(JSON.stringify(code))})">Open full research</button></div>`;
 el.onkeydown=e=>researchModalKey(e,el,()=>researchCloseInspector());if(focus)el.querySelector('.inspector-close')?.focus({preventScroll:true});
}
function researchChangesCSV(d,rows) {
 const cell=researchCSVCell;
 const header=['definition_json','previous_id','current_id','previous_at','current_at','previous_source_at','current_source_at','code','symbol','name','status','reason','previous_metrics','current_metrics','criterion_evidence','previous_source_clock','current_source_clock','capture_scope','observation_scope','previous_eligible_observations','current_eligible_observations','previous_generation_id','current_generation_id','export_scope',...(d.review_scope==='private_capture_pair'?['review_scope','review_revision_hash','review_revision','review_status','private_note']:[])];
 return '\ufeff'+[header.map(cell).join(','),...rows.map(r=>[d.definition,d.previous_id,d.current_id,d.previous_at,d.current_at,d.previous_source_at,d.current_source_at,r.code,r.symbol,r.name,r.status,r.reason,r.previous?.metrics,r.current?.metrics,r.evidence,d.previous_source_clock || 'unverified',d.current_source_clock || 'unverified',d.scope || 'unverified',d.observation_coverage?.scope || 'unverified',d.observation_coverage?.previous,d.observation_coverage?.current,d.previous_generation_id,d.current_generation_id,d.export_scope || 'all_filtered',...(d.review_scope==='private_capture_pair'?[d.review_scope,d.review_revision_hash,r.review?.revision,r.review?.review_status,r.review?.note]:[])].map(cell).join(','))].join('\n');
}
async function researchChangesExport(scope='all') {
 if(window.__changeLoading){alert('Wait for the requested comparison to finish loading.');return;}const st={...researchChangeState()},pair=window.__changePayload,authGen=window.__researchAuthGen || 0,changeGen=window.__changeGen;if(!pair?.comparable)return;
 const selection=scope==='selected'?researchChangeSelection(pair,st).rows.map(r=>r.code):null;if(selection && !selection.length){alert('Select comparison stocks to export.');return;}
 const button=[...document.querySelectorAll('.change-tools button')].find(b=>b.textContent==='Export comparison CSV');if(button)button.disabled=true;
 try{const qs=new URLSearchParams({definition:JSON.stringify(pair.definition || researchDefinition()),previous_id:pair.previous_id,current_id:pair.current_id,status:st.status,q:st.q,sort:st.sort,direction:st.direction,limit:500,offset:0});if(pair.review_scope==='private_capture_pair')qs.set('review_status',st.review_status || 'all');let rows=[],expected=null,reviewHash=null;
 for(let offset=0;offset<40000;offset+=500){qs.set('offset',offset);const data=pair.review_scope==='private_capture_pair'?await researchPrivateAPI('/api/research/pair-reviews?'+qs):await api('/api/screener/changes?'+qs);if(authGen!==(window.__researchAuthGen || 0) || changeGen!==window.__changeGen)throw new Error('Account or comparison changed. Retry export.');if(pair.review_scope==='private_capture_pair'){if(reviewHash!==null && reviewHash!==data.review_revision_hash)throw new Error('Review revisions changed during export. Retry.');reviewHash=data.review_revision_hash;if(selection && reviewHash!==pair.review_revision_hash)throw new Error('Review revisions changed since selection. Reload and select again.');if(!reviewHash)throw new Error('Review revisions are unconfirmed.');}if(!data.comparable || data.previous_id!==pair.previous_id || data.current_id!==pair.current_id)throw new Error('The comparison pair is no longer available.');if(expected!=null && expected!==data.matched)throw new Error('The review cohort changed during export.');expected=data.matched;rows.push(...data.rows);if(rows.length>=expected)break;if(!data.rows.length)throw new Error('Comparison export is incomplete.');}
 if(rows.length!==expected || new Set(rows.map(r=>r.code)).size!==rows.length)throw new Error('Comparison export identities are incomplete or duplicated.');
 if(selection){const selectedCodes=new Set(selection);rows=rows.filter(r=>selectedCodes.has(r.code));if(rows.length!==selection.length)throw new Error('Selected identities are no longer in this review. Reload and select again.');}
 const blob=new Blob([researchChangesCSV({...pair,export_scope:scope==='selected'?'selected':'all_filtered',review_revision_hash:reviewHash || pair.review_revision_hash},rows)],{type:'text/csv;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='screen_comparison_'+pair.previous_id+'_'+pair.current_id+(scope==='selected'?'_selected':'')+'.csv';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),30000);
 }catch(e){alert('Comparison export unavailable: '+e.message);}finally{if(button?.isConnected)button.disabled=false;}
}
function researchViewedGeneration() {
 const s=window.__scr,ds=window.__scrDataset;
 if(s.activePreset || s.watchlistOnly || !ds || ds.key!==[s.market,s.etfs?1:0,s.src || 'moo'].join('|'))return null;
 return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(ds.generationId || '')?ds.generationId:null;
}
function researchCaptureRequest(definition) {
 const key=JSON.stringify(researchStable(definition));let pending=window.__captureRequest;
 if(!pending){try{const saved=JSON.parse(sessionStorage.getItem('researchCaptureRequestV1') || 'null');if(saved?.key===key && /^[0-9a-f-]{36}$/i.test(saved.id || ''))pending=saved;}catch(e){}}
 if(pending?.key!==key)pending={key,id:crypto.randomUUID(),generation_id:researchViewedGeneration()};window.__captureRequest=pending;
 try{sessionStorage.setItem('researchCaptureRequestV1',JSON.stringify(pending));}catch(e){}
 return pending;
}
function researchCaptureConfirmed(request) {
 if(window.__captureRequest!==request)return;window.__captureRequest=null;
 try{sessionStorage.removeItem('researchCaptureRequestV1');}catch(e){}
}
async function researchSnapshot() {
 const el=document.getElementById('research-change-results');if(!el || window.__snapshotBusy)return;const definition=researchDefinition(),request=researchCaptureRequest(definition);window.__snapshotBusy=true;const button=document.querySelector('[data-capture]');if(button)button.disabled=true;el.textContent='Capturing and validating complete membership…';
 try{await api('/api/screener/snapshots',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':request.id,...(request.generation_id?{'X-Screener-Generation':request.generation_id}:{})},body:JSON.stringify(definition)});researchCaptureConfirmed(request);if(document.getElementById('research-change-results')!==el)return;const st=researchChangeState();st.previous_id='';st.current_id='';st.offset=0;st.history_offset=0;await researchLoadChanges();}catch(e){if(document.getElementById('research-change-results')===el)el.innerHTML=`<p>Capture unavailable: ${esc(researchErrorMessage(e))}</p><button class="btn primary" onclick="researchSnapshot()">Retry capture</button><button class="btn ghost" onclick="researchLoadChanges()">Return to comparison</button>`;}finally{window.__snapshotBusy=false;if(button?.isConnected)button.disabled=false;}
}

async function researchRefreshPreset() {
 const st=window.__scr,key=st.activePreset,market=st.market,ck=key+'|'+market,entry=window.__presetCache?.[ck];
 if(!key || !entry?.payload?.available || window.__presetRefresh?.[ck] || window.__presetPagePending?.has(ck))return;
 entry.retained=true;delete entry.refreshError;
 const pending=window.__presetRefresh || (window.__presetRefresh={});pending[ck]=true;
 const visible=()=>state.page==='home' && window.__scr.activePreset===key && window.__scr.market===market;
 try {
  if(visible())await showPage('home');
  const payload=await api('/api/screener/execute?key='+encodeURIComponent(key)+'&market='+encodeURIComponent(market)+'&limit=300&refresh=true');
  if(!payload?.available)throw new Error(payload?.reason || 'Provider screen unavailable');
  if(window.__presetCache?.[ck]!==entry)return;
  window.__presetCache[ck]={ts:Date.now(),retained:true,payload};
  if(visible()){
   window.__scr.page=1;
   const available=new Set(scrPresetRows(payload).map(researchKey));
   window.__researchSelected=(window.__researchSelected || []).filter(code=>available.has(code));
   scrPersist();
  }
 }catch(e){if(window.__presetCache?.[ck]===entry)entry.refreshError=e.message || 'Provider request failed';}
 finally {delete pending[ck];if(visible())await showPage('home');}
}
async function researchLoadMore() {
 const s=window.__scr,key=s.activePreset,market=s.market,ck=key+'|'+market,entry=(window.__presetCache || {})[ck];
 const current=entry?.payload;if(!key || !current?.next_key || window.__presetRefresh?.[ck] || window.__presetPagePending?.has(ck))return;
 const paging=window.__presetPagePending || (window.__presetPagePending=new Set());paging.add(ck);
 const button=document.getElementById('research-load-more');if(button){button.disabled=true;button.textContent='Loading next provider page…';}
 try{const next=await api('/api/screener/execute?key='+encodeURIComponent(key)+'&market='+encodeURIComponent(market)+'&limit=300&next_key='+encodeURIComponent(current.next_key)+(current.quote_generation_id?'&quote_generation_id='+encodeURIComponent(current.quote_generation_id):''));
  if(!next.available)throw new Error(next.reason || 'Provider page unavailable');
  if((next.quote_generation_id || null)!==(current.quote_generation_id || null))throw new Error('Quote display cohort changed; previous results retained. Refresh this screen.');
  if(window.__scr.activePreset!==key || window.__scr.market!==market || window.__presetCache?.[ck]!==entry)return;
  const byCode=new Map(current.rows.map(r=>[r.code,r]));next.rows.forEach(r=>byCode.set(r.code,r));
  if(byCode.size===current.rows.length && next.possibly_truncated)throw new Error('Provider returned duplicate membership; previous results retained');
  const hydration_warnings=[...new Set([...(current.hydration_warnings || []),...(next.hydration_warnings || [])])];
  window.__presetCache[ck]={ts:Date.now(),retained:true,payload:{...next,rows:[...byCode.values()],hydration_warnings,result_limit:byCode.size}};
  await showPage('home');
 }catch(e){if(window.__scr.activePreset!==key || window.__scr.market!==market || window.__presetCache?.[ck]!==entry)return;if(button){button.disabled=false;button.textContent='Retry next page';}const el=document.getElementById('research-page-status');if(el)el.textContent=e.message;}finally{paging.delete(ck);}
}
function researchSearchClose() {
 clearTimeout(window.__researchSearchTimer);window.__researchSearchGen=(window.__researchSearchGen || 0)+1;
 const el=document.getElementById('research-global-results');if(el)el.hidden=true;
 document.getElementById('research-global-search')?.setAttribute('aria-expanded','false');
}
function researchSearchInput(q) {
 clearTimeout(window.__researchSearchTimer);
 const query=String(q || '').trim();if(!query){researchSearchClose();return;}
 window.__researchSearchTimer=setTimeout(()=>researchSearchRun(query),180);
}
function researchSearchUniverse(market) {
 const ds=window.__scrDataset;
 if(ds?.key===market+'|0|moo' || ds?.key===market+'|0|yf')return Promise.resolve({rows:ds.rows,at:ds.ts});
 const cached=window.__researchSearchUniverse?.[market];if(cached && Date.now()-cached.at<300000)return Promise.resolve(cached);
 window.__researchSearchRequests=window.__researchSearchRequests || {};
 if(window.__researchSearchRequests[market])return window.__researchSearchRequests[market];
 const qs=new URLSearchParams({market,watchlist_only:0,src:'moo',sort:'market_cap',direction:2,limit:20000,filters:JSON.stringify([{field:'stock_type',values:['STOCK']}])});
 return window.__researchSearchRequests[market]=api('/api/screener?'+qs).then(d=>{
  if(d.available===false)throw new Error(d.reason || 'Universe unavailable');
  const result={rows:d.rows || [],at:Date.now(),truncated:!!d.possibly_truncated};
  window.__researchSearchUniverse=window.__researchSearchUniverse || {};window.__researchSearchUniverse[market]=result;return result;
 }).finally(()=>delete window.__researchSearchRequests[market]);
}
async function researchSearchRun(q) {
 const gen=window.__researchSearchGen=(window.__researchSearchGen || 0)+1,market=window.__scr.market,el=document.getElementById('research-global-results');if(!el)return;
 el.hidden=false;document.getElementById('research-global-search')?.setAttribute('aria-expanded','true');
 const needle=q.toLowerCase(),call=x=>esc(JSON.stringify(x));
 const presets=(window.__scrPresets || []).filter(p=>p.name.toLowerCase().includes(needle)).slice(0,5),saved=(window.__savedScreeners || []).filter(p=>p.name.toLowerCase().includes(needle)).slice(0,5);
 const screens=presets.map(p=>`<button onclick="researchSearchClose();scrApplyPreset(${call(p.key)})">${esc(p.name)}<small>Recommended screen</small></button>`).concat(saved.map(s=>`<button onclick="researchSearchClose();scrApplySaved(${call(s.id)})">${esc(s.name)}<small>Saved screen</small></button>`)).join('');
 el.innerHTML=screens+'<p role="status">Searching the '+esc(market)+' stock universe…</p>';
 try{
  const data=await researchSearchUniverse(market);if(gen!==window.__researchSearchGen || market!==window.__scr.market)return;
  const rows=stkMatches(q,data.rows,8);
  el.innerHTML=screens+rows.map(r=>`<button onclick="researchSearchClose();researchOpen(${call(researchKey(r))})">${esc(r.symbol)} <span>${esc(r.name || '')}</span><small>Open full research</small></button>`).join('')+`<p>${data.rows.length.toLocaleString()} ${esc(market)} stocks searched${data.truncated?' · loaded subset':''}. ${!screens && !rows.length?'No matches. Try the full symbol or company name.':''}</p>`;
 }catch(e){if(gen===window.__researchSearchGen)el.innerHTML=screens+'<p role="status">Stock search unavailable. Screen matches above remain available.</p>';}
}
function researchSearchKey(e) {
 const el=document.getElementById('research-global-results');if(e.key==='Escape'){researchSearchClose();document.getElementById('research-global-search')?.focus();return;}
 const buttons=[...el.querySelectorAll('button')];
 if(e.key==='ArrowDown' || e.key==='ArrowUp'){e.preventDefault();const index=buttons.indexOf(document.activeElement),next=e.key==='ArrowDown'?(index+1)%buttons.length:(index<=0?buttons.length-1:index-1);buttons[next]?.focus();}
 if(e.key==='Enter' && document.activeElement===document.getElementById('research-global-search')){e.preventDefault();if(buttons.length)buttons[0].click();else researchSearchRun(e.target.value);}
}
function researchTimingRecord(name,start,meta={}) {
 const elapsed=(window.performance?.now() ?? Date.now())-start;
 const entries=window.__researchTiming || (window.__researchTiming=[]);entries.push({name,ms:Math.round(elapsed*100)/100,...meta});if(entries.length>200)entries.shift();
 const out=document.getElementById('research-performance');if(out)out.textContent=JSON.stringify(entries);
}
function researchRenderSource() {
 const st=window.__scr,preset=st.activePreset && window.__presetCache?.[st.activePreset+'|'+st.market];
 if(preset && Date.now()-preset.ts<60000)return 'preset-cache';
 const ds=window.__scrDataset;if(!st.activePreset && ds?.key===[st.market,st.etfs?1:0,st.src || 'moo'].join('|') && Date.now()-ds.ts<60000)return 'dataset-memory';
 return 'uncached-or-persisted';
}
function researchResponsivePanels() {
 const inspector=document.getElementById('research-inspector');
 if(inspector?.classList.contains('open')){
  const modal=window.matchMedia('(max-width:1350px)').matches;
  inspector.setAttribute('role',modal?'dialog':'complementary');
  if(modal){inspector.setAttribute('aria-modal','true');researchModalIsolate(inspector,'inspector');if(!inspector.contains(document.activeElement)){window.__inspectOrigin=window.__inspectOrigin || document.activeElement;inspector.querySelector('.inspector-close')?.focus({preventScroll:true});}}
  else{inspector.removeAttribute('aria-modal');researchModalRelease('inspector');}
 }
 if(window.matchMedia('(min-width:1001px)').matches && document.getElementById('research-library')?.classList.contains('library-open'))researchLibraryClose(false);
}
if(window.matchMedia){window.matchMedia('(max-width:1350px)').addEventListener?.('change',researchResponsivePanels);window.matchMedia('(min-width:1001px)').addEventListener?.('change',researchResponsivePanels);}
function researchDisposeDesk() {window.__deskResize?.disconnect();window.__deskResize=null;window.__exploreResize?.disconnect();window.__exploreResize=null;}
function researchFrozenColumns() {
 const grid=document.querySelector('.research-desk'),table=grid?.querySelector('.scr-table');if(!table)return;
 const select=table.querySelector('th:first-child')?.getBoundingClientRect().width || 44,no=table.querySelector('th:nth-child(2)')?.getBoundingClientRect().width || 34,symbol=table.querySelector('th[data-field="symbol"]')?.getBoundingClientRect().width || 112;
 grid.style.setProperty('--frozen-number-left',select+'px');grid.style.setProperty('--frozen-symbol-left',(select+no)+'px');grid.style.setProperty('--frozen-name-left',(select+no+symbol)+'px');
}

function researchPairQuery(pair,st,extra={}) {
 return new URLSearchParams({definition:JSON.stringify(pair.definition || researchDefinition()),previous_id:pair.previous_id,current_id:pair.current_id,
  status:st.status,q:st.q,sort:st.sort,direction:st.direction,limit:st.limit,offset:st.offset,history_offset:st.history_offset || 0,review_status:st.review_status || 'all',...extra});
}
function researchPairStatusLabel(status) {return {unreviewed:'Unreviewed',in_review:'In review',reviewed:'Reviewed'}[status] || 'Unavailable';}
function researchPairToolsHTML(d,st) {
 if(!window.__researchSession)return '<p class="pair-review-tools">Sign in to keep private notes and review status for this capture pair. <button class="btn ghost" onclick="researchPairSignIn()">Sign in to review</button></p>';
 if(d.review_error)return `<p class="delay-note" role="status">Private review unavailable: ${esc(d.review_error)} <button class="btn ghost" onclick="researchLoadChanges()">Retry private review</button></p>`;
 if(d.review_scope!=='private_capture_pair')return '';
 return `<div class="pair-review-tools"><label>My review<select aria-label="Filter my pair review" onchange="researchChangeSet('review_status',this.value)">${['all','unreviewed','in_review','reviewed'].map(status=>`<option value="${status}" ${(st.review_status || 'all')===status?'selected':''}>${status==='all'?'All review states':researchPairStatusLabel(status)}</option>`).join('')}</select></label><button class="btn ghost" onclick="researchPairNext()">Next unreviewed</button><span id="research-pair-queue-status" role="status">Private notes · this capture pair only · CSV includes notes</span></div>`;
}
function researchPairDraftKey(d,code) {return JSON.stringify([window.__researchSession?.user.id,researchChangeState().key,d.previous_id,d.current_id,code]);}
function researchPairFormHTML(d,r) {
 if(d.review_scope!=='private_capture_pair' || !r.review)return '';
 const key=researchPairDraftKey(d,r.code),saved=r.review,draft=(window.__researchPairDrafts ||= {})[key] || {...saved,owner:d.owner_id,key,code:r.code};
 window.__researchPairDrafts[key]=draft;window.__researchPairDraftKey=key;
 return `<section class="pair-review-editor"><h3>My review of this pair</h3><form data-pair-review onsubmit="event.preventDefault();researchPairSave(this)" oninput="researchPairDraftUpdate(this)" onchange="researchPairDraftUpdate(this)"><label>Review status<select name="review_status" aria-label="Pair review status">${['unreviewed','in_review','reviewed'].map(status=>`<option value="${status}" ${draft.review_status===status?'selected':''}>${researchPairStatusLabel(status)}</option>`).join('')}</select></label><label>Private note<textarea name="note" aria-label="Private pair review note" maxlength="4000" rows="4">${esc(draft.note || '')}</textarea></label><div class="pair-review-actions"><button class="btn primary" type="submit">Save pair review</button><button class="btn ghost" type="button" onclick="researchPairReload(this.form)">Reload saved review</button><button class="btn ghost" type="button" onclick="researchPairNext()">Next unreviewed</button></div><p role="status">${esc(draft.message || 'Draft stays in this tab until saved. Closing the preview keeps it; signing out clears it.')}</p>${draft.latest?`<details><summary>Latest saved review · revision ${draft.latest.revision}</summary><p>${esc(researchPairStatusLabel(draft.latest.review_status))}</p><p>${esc(draft.latest.note)}</p></details>`:''}</form></section>`;
}
function researchPairDraftUpdate(form) {
 const draft=window.__researchPairDrafts?.[window.__researchPairDraftKey];if(!draft)return;
 draft.note=form.elements.note.value;draft.review_status=form.elements.review_status.value;
}
async function researchPairSave(form) {
 researchPairDraftUpdate(form);const key=window.__researchPairDraftKey,draft=window.__researchPairDrafts?.[key],pair=window.__changePayload;
 if(!draft || !pair || draft.owner!==window.__researchSession?.user.id)return;
 const submitted={note:draft.note,review_status:draft.review_status},gen=window.__researchAuthGen || 0,button=form.querySelector('button[type=submit]'),status=form.querySelector('[role=status]');button.disabled=true;status.textContent='Saving pair review…';
 try{const result=await researchPrivateAPI('/api/research/pair-reviews',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({definition:pair.definition,previous_id:pair.previous_id,current_id:pair.current_id,code:draft.code,revision:draft.revision,note:draft.note,review_status:draft.review_status})});
  if(gen!==(window.__researchAuthGen || 0))return;
  const edited=draft.note!==submitted.note || draft.review_status!==submitted.review_status;
  draft.revision=result.review.revision;draft.latest=edited?result.review:null;draft.message=edited?'Submitted review saved. Your newer edits are still unsaved.':'Pair review saved.';
  const row=pair.rows.find(r=>r.code===draft.code);if(row)row.review=result.review;
  if(form.isConnected){const el=document.getElementById('research-change-results');if(el)await researchLoadChanges();else status.textContent=draft.message;}
 }catch(e){if(gen!==(window.__researchAuthGen || 0))return;draft.message=e.status===409?'This review changed. Your draft is kept. Reload the saved review, compare it with your draft, then save again.':researchErrorMessage(e);if(form.isConnected)status.textContent=draft.message;}
 finally{if(button.isConnected)button.disabled=false;}
}
async function researchPairReload(form) {
 researchPairDraftUpdate(form);const key=window.__researchPairDraftKey,draft=window.__researchPairDrafts?.[key],pair=window.__changePayload;
 if(!draft || !pair)return;const gen=window.__researchAuthGen || 0,status=form.querySelector('[role=status]');status.textContent='Loading saved review; keeping your draft…';
 try{const d=await researchPrivateAPI('/api/research/pair-reviews?'+researchPairQuery(pair,researchChangeState(),{code:draft.code,status:'all',q:'',offset:0,limit:1,review_status:'all'}));
  if(gen!==(window.__researchAuthGen || 0) || window.__researchPairDraftKey!==key)return;
  const saved=d.rows.find(r=>r.code===draft.code)?.review;if(!saved)throw Error('Saved pair review is unavailable.');
  draft.latest=saved;draft.revision=saved.revision;draft.message='Latest saved review loaded below. Your draft is kept; saving will replace this revision.';
  researchChangeInspect(draft.code,null,false);
 }catch(e){if(gen===(window.__researchAuthGen || 0) && form.isConnected)status.textContent=researchErrorMessage(e);}
}
async function researchPairNext() {
 const pair=window.__changePayload;if(pair?.review_scope!=='private_capture_pair')return;
 const st=researchChangeState(),gen=(window.__changeGen || 0)+1,authGen=window.__researchAuthGen || 0;window.__changeGen=gen;window.__changeLoading=true;
 const status=document.querySelector('#research-inspector form[data-pair-review] [role=status]') || document.getElementById('research-pair-queue-status');if(status)status.textContent='Finding next unreviewed stock…';
 try{const d=await researchPrivateAPI('/api/research/pair-reviews?'+researchPairQuery(pair,st,{review_status:'unreviewed',next_review:true,...(window.__researchChangeCode?{next_code:window.__researchChangeCode}:{}),offset:0}));
  if(gen!==window.__changeGen || authGen!==(window.__researchAuthGen || 0))return;
  if(!d.next_review_code){if(status)status.textContent='No unreviewed stocks in this comparison and search.';return;}
  st.review_status='unreviewed';st.offset=d.offset;window.__changePayload=d;window.__researchChangeCode=null;
  const el=document.getElementById('research-change-results');if(el){researchChangesRender(el,d);researchChangeInspect(d.next_review_code,null,true);}
 }catch(e){if(gen===window.__changeGen && status)status.textContent=researchErrorMessage(e);}
 finally{if(gen===window.__changeGen)window.__changeLoading=false;}
}

function researchPairSignIn(){window.__researchPendingPairReview=true;researchAccountOpen();}

function researchChangeSelectionKey(d,st) {
 return JSON.stringify([d.review_scope==='private_capture_pair'?window.__researchSession?.user.id:null,researchStable(d.definition),d.previous_id,d.current_id,
  st.status,st.q,st.sort,st.direction,st.review_status || 'all',d.review_revision_hash || null]);
}
function researchChangeSelection(d=window.__changePayload,st=researchChangeState()) {
 const key=researchChangeSelectionKey(d || {},st);
 if(window.__researchChangeSelection?.key!==key)window.__researchChangeSelection={key,rows:[],message:window.__researchChangeSelection?.rows?.length?'Selection cleared because the pair, query, account or review revisions changed.':''};
 return window.__researchChangeSelection;
}
function researchChangeSelect(code,on) {
 if(window.__changeLoading)return;const d=window.__changePayload,row=d?.rows.find(r=>r.code===code);if(!row)return;
 const selection=researchChangeSelection(),rows=new Map(selection.rows.map(r=>[r.code,r]));
 if(on)rows.set(code,{code,symbol:row.symbol});else rows.delete(code);selection.rows=[...rows.values()];selection.message='';researchChangeSelectionMount();
}
function researchChangeSelectPage(on) {
 if(window.__changeLoading)return;const d=window.__changePayload;if(!d?.comparable)return;
 const selection=researchChangeSelection(),rows=new Map(selection.rows.map(r=>[r.code,r]));
 for(const r of d.rows)if(on)rows.set(r.code,{code:r.code,symbol:r.symbol});else rows.delete(r.code);
 selection.rows=[...rows.values()];selection.message='';researchChangeSelectionMount();
}
function researchChangeSelectionHTML(d,st) {
 const selection=researchChangeSelection(d,st),n=selection.rows.length;
 return `<div class="change-selection-tools"><button class="btn ghost" onclick="researchChangeSelectPage(true)">Select this review page</button><button class="btn ghost" onclick="researchChangeSelectPage(false)">Deselect this page</button><span role="status">${n} selected across review pages${selection.message?' · '+esc(selection.message):''}</span>${n?`<button class="btn ghost" onclick="researchChangeCompare()" ${n<2 || n>4?'disabled':''}>Compare selected (${n})</button><button class="btn ghost" onclick="researchChangeBulkPicker()">Add selected to shortlist</button><button class="btn ghost" onclick="researchChangesExport('selected')">Export selected comparison CSV</button><button class="btn ghost" onclick="researchChangeClearSelection()">Clear review selection</button>`:''}<span class="faint">Compare 2–4 · exports use this pair and current sort</span></div>`;
}
function researchChangeSelectionMount() {
 const d=window.__changePayload,st=researchChangeState(),el=document.getElementById('research-change-selection');if(!d || !el)return;
 const active=document.activeElement,action=el.contains?.(active)?active?.getAttribute('onclick'):null;
 el.innerHTML=researchChangeSelectionHTML(d,st);if(action){const target=[...el.querySelectorAll('button')].find(b=>b.getAttribute('onclick')===action);(target || el.querySelector('button'))?.focus({preventScroll:true});}const codes=new Set(researchChangeSelection(d,st).rows.map(r=>r.code));
 document.querySelectorAll('input[data-change-code]').forEach(input=>input.checked=codes.has(input.dataset.changeCode));
}
function researchChangeClearSelection(){researchChangeSelection().rows=[];researchChangeSelectionMount();}
function researchChangeCompare() {
 if(window.__changeLoading)return;const rows=researchChangeSelection().rows;if(rows.length<2 || rows.length>4)return;
 researchCaptureContext();const st=cmpState();st.cells=rows.map(r=>({...JSON.parse(JSON.stringify(CMP_DEFAULT.cells[0])),sym:r.code.replace(/^US\./,'')}));
 st.layout=rows.length===2?'2h':rows.length===3?'1+2':'2x2';st.active=0;st.sync.ticker=false;cmpSave();showPage('compare');
}
async function researchChangeBulkPicker() {
 if(window.__changeLoading)return;if(!window.__researchSession){researchPairSignIn();return;}
 const pair=window.__changePayload,selection=researchChangeSelection();if(!pair?.comparable || !selection.rows.length)return;
 const bulk={owner:window.__researchSession.user.id,key:selection.key,codes:selection.rows.map(r=>r.code),done:[],failures:[],pair:[pair.previous_id,pair.current_id]};
 window.__researchChangeBulk=bulk;
 const el=researchDialogOpen('<div class="dialog-heading"><h2>Add selected comparison stocks</h2><button class="btn ghost" onclick="researchDialogClose()">Close</button></div><p role="status">Loading your shortlists…</p>');el.setAttribute('data-change-bulk','');
 try{const d=await researchPrivateAPI('/api/research/lists');if(window.__researchDialog!==el || window.__researchChangeBulk!==bulk)return;
  el.innerHTML=`<div class="dialog-heading"><h2>Add ${bulk.codes.length} selected ${bulk.codes.length===1?'stock':'stocks'}</h2><button class="btn ghost" onclick="researchDialogClose()">Close</button></div><p>Pair ${esc(pair.previous_id)} → ${esc(pair.current_id)}. Existing shortlist notes and review status are preserved. Each addition is confirmed separately; failed additions can be retried.</p>${d.lists.length?`<label>Shortlist<select aria-label="Shortlist for comparison selection">${d.lists.map(r=>`<option value="${esc(r.id)}">${esc(r.name)}</option>`).join('')}</select></label><button class="btn primary" onclick="researchChangeBulkAdd()">Add selected stocks</button>`:'<p>Create a shortlist before adding stocks.</p>'}${d.possibly_truncated?'<p>Only the first 500 shortlists are shown. Manage shortlists to locate another list.</p>':''}<button class="btn ghost" onclick="researchDialogClose();showPage('shortlists')">Manage shortlists</button><p role="status"></p><div id="research-change-bulk-failures"></div>`;researchDialogLabel(el);el.querySelector('select,button')?.focus();
 }catch(e){if(window.__researchDialog===el)el.querySelector('[role=status]').textContent=researchErrorMessage(e);}
}
async function researchChangeBulkAdd() {
 const bulk=window.__researchChangeBulk,el=window.__researchDialog;if(!bulk || !el || bulk.running)return;if(window.__changeLoading){el.querySelector('[role=status]').textContent='Wait for the comparison to finish loading.';return;}
 const selection=researchChangeSelection();if(bulk.owner!==window.__researchSession?.user.id || bulk.key!==selection.key){el.querySelector('[role=status]').textContent='Comparison or account changed. Close and select again.';return;}
 const list=el.querySelector('select').value;if(!researchListIDValid(list)){el.querySelector('[role=status]').textContent='Select a valid shortlist.';return;}if(bulk.list && bulk.list!==list){el.querySelector('[role=status]').textContent='This operation belongs to the original shortlist. Close and start again for a different list.';return;}
 bulk.list=list;bulk.running=true;const button=el.querySelector('button.primary'),status=el.querySelector('[role=status]'),gen=window.__researchAuthGen || 0;
 button.disabled=true;el.querySelector('select').disabled=true;const confirmed=new Set(bulk.done),remaining=bulk.codes.filter(code=>!confirmed.has(code));bulk.failures=[];
 try{for(let i=0;i<remaining.length;i+=4){if(gen!==(window.__researchAuthGen || 0) || window.__researchDialog!==el || bulk.key!==researchChangeSelection().key)break;
   const batch=remaining.slice(i,i+4),results=await Promise.allSettled(batch.map(code=>researchPrivateAPI('/api/research/lists/'+encodeURIComponent(list)+'/items',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code})})));
   if(gen!==(window.__researchAuthGen || 0))return;
   results.forEach((result,j)=>{if(result.status==='fulfilled' && result.value.item?.code===batch[j])bulk.done.push(batch[j]);else bulk.failures.push({code:batch[j],message:result.status==='rejected'?researchErrorMessage(result.reason):'Addition was not confirmed.'});});
   if(window.__researchDialog===el)status.textContent=bulk.done.length+' of '+bulk.codes.length+' additions confirmed · '+bulk.failures.length+' failed';
  }
  if(window.__researchDialog===el){const unstarted=bulk.codes.length-bulk.done.length-bulk.failures.length;status.textContent=bulk.done.length+' of '+bulk.codes.length+' additions confirmed · '+bulk.failures.length+' failed'+(unstarted?' · '+unstarted+' not started':'')+'. Existing notes and status retained.';
   el.querySelector('#research-change-bulk-failures').innerHTML=bulk.failures.length?'<ul>'+bulk.failures.map(f=>'<li>'+esc(f.code)+': '+esc(f.message)+'</li>').join('')+'</ul>':'';button.textContent=bulk.done.length===bulk.codes.length?'All additions confirmed':'Retry unconfirmed additions';}
 }finally{bulk.running=false;if(button.isConnected)button.disabled=bulk.done.length===bulk.codes.length;}
}
