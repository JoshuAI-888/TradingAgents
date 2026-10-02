/* Research workspace: presentation and navigation over the existing screener.
   Existing preset membership, columns, exports and KLine engine remain authoritative. */
function researchRows() { return scrClientRows() || []; }
function researchVisibleRows() { return window.__homeCtx?.scr?.rows || []; }
function researchKey(r) { return r.code || r.symbol; }
function researchSelect(i, on) {
  const row = researchVisibleRows()[i]; if (!row) return;
  const set = new Set(window.__researchSelected || []);
  on ? set.add(researchKey(row)) : set.delete(researchKey(row));
  window.__researchSelected = [...set]; researchSelectionMount();
}
function researchSelectionMount() {
  const el = document.getElementById('research-selection'); if (!el) return;
  const selected = window.__researchSelected || [];
  el.innerHTML = `<span>${selected.length} selected</span><button class="btn primary" onclick="researchCompare()" ${selected.length < 2 || selected.length > 4 ? 'disabled' : ''}>Compare selected</button><button class="btn ghost" onclick="window.__researchSelected=[];showPage('home')">Clear selection</button><span class="faint">Choose 2–4 stocks</span>`;
  el.hidden = !selected.length;
}
function researchCaptureContext() {
  window.__researchContext = {state:JSON.parse(JSON.stringify(window.__scr)),hash:location.hash,
    scroll:window.scrollY || 0,tableScroll:document.querySelector('.scr-scroll')?.scrollTop || 0,
    rows:researchRows().map(r=>({code:researchKey(r),symbol:r.symbol})),selected:[...(window.__researchSelected || [])]};
}
function researchOpen(code) {
  if (state.page === 'home') researchCaptureContext();
  openStock(code);
}
async function researchReturn() {
  const ctx=window.__researchContext;
  if(ctx) {window.__scr=JSON.parse(JSON.stringify(ctx.state));window.__researchSelected=[...ctx.selected];}
  scrPersist(); await showPage('home');
  window.scrollTo(0,ctx?.scroll || 0);
  const table=document.querySelector('.scr-scroll');if(table)table.scrollTop=ctx?.tableScroll || 0;
}
function researchBreadcrumb() {
  const ctx=window.__researchContext; if(!ctx)return '';
  const index=ctx.rows.findIndex(r=>r.code===stkState().sym || r.symbol===stkState().sym);
  return `<div class="research-breadcrumb"><button class="btn ghost" onclick="researchReturn()">← Back to screen</button><span class="faint">${esc(ctx.state.market)} · ${ctx.rows.length.toLocaleString()} available matches</span><button class="btn ghost" onclick="researchAdjacent(-1)" ${index<=0?'disabled':''}>Previous stock</button><button class="btn ghost" onclick="researchAdjacent(1)" ${index<0 || index>=ctx.rows.length-1?'disabled':''}>Next stock</button></div>`;
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
function researchLibrarySearch(q) {
 q=q.toLowerCase();document.querySelectorAll('.research-library .preset').forEach(el=>el.hidden=!el.textContent.toLowerCase().includes(q));
}
function researchSavedMount() {
 const el=document.getElementById('research-saved');if(!el)return;
 el.innerHTML=(window.__savedScreeners || []).map(s=>`<button class="btn ghost saved-screen ${window.__scr.savedScreenId===s.id?'on':''}" onclick="scrApplySaved('${esc(s.id)}')">${esc(s.name)}<small>${esc(s.sort)} ${s.direction===1?'↑':'↓'}</small></button>`).join('') || '<p class="faint">Save your criteria to revisit them.</p>';
}
function scrWorkspaceMount() {
 window.__inspectGen=(window.__inspectGen || 0)+1;
 if(window.__inspectChart){try{window.klinecharts.dispose('inspect-chart');}catch(e){}window.__inspectChart=null;}
 const grid=document.querySelector('.scr-grid'), main=document.querySelector('.scr-main');if(!grid || !main)return;
 grid.classList.add('research-grid');
 const rail=grid.querySelector('.scr-rail') || [...grid.children].find(x=>x!==main);
 if(rail){rail.classList.add('research-library');grid.insertBefore(rail,main);
   const heading=rail.querySelector('h3');if(heading)heading.innerHTML='Recommended <small>22 screens</small>';
   const intro=document.createElement('div');intro.className='library-intro';intro.innerHTML=`<input aria-label="Search recommended screens" placeholder="Search recommended screens…" oninput="researchLibrarySearch(this.value)"><button class="btn ${window.__scr.activePreset?'ghost':'primary'}" onclick="scrResetAll()">All stocks · ETFs excluded</button>`;rail.prepend(intro);
   const saved=document.createElement('section');saved.className='saved-library';saved.innerHTML='<h4>My saved screens</h4><div id="research-saved"></div><button class="btn ghost" onclick="researchSave()">Manage / save screen</button>';rail.append(saved);researchSavedMount();
 }
 const st=window.__scr,rows=researchRows(),mode=st.presentation || 'table';
 const h=main.querySelector('h3');if(h){h.firstChild.textContent=(st.activePreset ? (window.__scrPresets || []).find(p=>p.key===st.activePreset)?.name || 'Screen results' : st.savedScreenId ? (window.__savedScreeners || []).find(s=>s.id===st.savedScreenId)?.name || 'Saved screen' : st.filters.length || Object.keys(st.colFilters).length ? 'Custom screen' : 'All stocks')+' ';}
 const railNote=[...(rail?.querySelectorAll('.faint') || [])].find(e=>e.textContent.includes('Top-3 from')); if(railNote)railNote.remove();
 const top=document.createElement('div');top.className='research-top';top.innerHTML=`<div class="research-modes" role="group" aria-label="Result presentation">${['table','explore','changes'].map(v=>`<button class="btn ${mode===v?'primary':'ghost'}" aria-pressed="${mode===v}" onclick="researchMode('${v}')">${v[0].toUpperCase()+v.slice(1)}</button>`).join('')}</div><span class="faint">${esc(st.market)} · ${st.etfs?'Stocks + ETFs':'ETFs excluded'} · ${esc(SCR_COLS[st.sort]?.[0] || st.sort)} ${st.dir===2?'descending':'ascending'}</span><button class="btn ghost" onclick="researchSave()">Save screen</button>`;main.insertBefore(top,h);
 const exportGroup=main.querySelector('.expgrp');if(exportGroup){const menu=document.createElement('details');menu.className='research-export';menu.innerHTML='<summary class="btn ghost">Export ↓</summary><div class="export-options">'+exportGroup.innerHTML.replace('CSV · all','CSV · available matches').replace('Excel · all','Excel · available matches')+'<small>Excel-compatible .xls · respects filters, columns and sort</small></div>';exportGroup.replaceWith(menu);}
 const tpl=[...main.querySelectorAll('.scr-toolbar')];
 // Retain every control, with secondary templates and technical shortcuts on demand.
 const advanced=document.createElement('details');advanced.className='research-advanced';advanced.innerHTML='<summary>Quick signals & column templates</summary>';
 tpl.filter((t,i)=>i>0).forEach(t=>{t.classList.add('secondary-tools');advanced.append(t);});
 if(advanced.children.length>1)tpl[0].after(advanced);
 const tools=tpl[0]; if(tools){const more=document.createElement('details');more.className='research-universe';more.innerHTML='<summary class="btn ghost">Universe & data</summary><div class="universe-options"></div>';
   const box=more.lastElementChild;
   [...tools.children].filter(el=>el.tagName==='SELECT' || el.tagName==='INPUT' || el.tagName==='LABEL').forEach(el=>box.append(el));
   tools.prepend(more);
 }
 if(st.activePreset){const payload=(window.__presetCache || {})[st.activePreset+'|'+st.market]?.payload;
   if(payload?.next_key && payload.possibly_truncated){const paging=document.createElement('div');paging.className='research-provider-paging';paging.innerHTML=`<p class="faint">${rows.length.toLocaleString()} stock matches loaded${payload.provider_total!=null?' · '+Number(payload.provider_total).toLocaleString()+' provider matches before instrument exclusions':''}. Exports and Explore use loaded matches.</p><button class="btn ghost" id="research-load-more" onclick="researchLoadMore()">Load next 300 matches</button><span id="research-page-status" role="status"></span>`;main.append(paging);}
 }
 const sel=document.createElement('div');sel.id='research-selection';sel.className='research-selection';main.append(sel);researchSelectionMount();
 const scroll=main.querySelector('.scr-scroll');if(mode==='explore'){const plot=document.createElement('section');plot.className='research-explore';plot.innerHTML=researchExploreHTML(rows);scroll.before(plot);researchPlot(rows);}
 if(mode==='changes'){const pane=document.createElement('section');pane.id='research-changes';pane.className='research-changes';pane.innerHTML='<h3>Changes in this screen</h3><p class="faint">Compare complete snapshots with the same criteria. A first capture establishes the baseline.</p><button class="btn primary" onclick="researchSnapshot()">Capture snapshot</button><div id="research-change-results" aria-live="polite"></div>';scroll.before(pane);scroll.hidden=true;const pager=main.querySelector('.pager');if(pager)pager.hidden=true;researchLoadChanges();}
 const inspector=document.createElement('aside');inspector.id='research-inspector';inspector.className='research-inspector';inspector.innerHTML='<h3>Inspect a stock</h3><p class="faint">Use Inspect beside a row to see quote data and screen context without leaving your place.</p><p class="faint">Ticker links open the full research page with every chart and financial control.</p>';grid.append(inspector);
 if(window.__researchInspectCode){const i=researchVisibleRows().findIndex(r=>researchKey(r)===window.__researchInspectCode);if(i>=0)researchInspect(i);}
}
function researchExploreHTML(rows) {
 const x=window.__researchAxisX || 'pe_ttm',y=window.__researchAxisY || 'pct',axes=['pe_ttm','pb','market_cap','pct'];
 const selector=(key,value)=>`<select aria-label="${key} axis" onchange="window.__researchAxis${key}=this.value;showPage('home')">${axes.map(k=>`<option value="${k}" ${k===value?'selected':''}>${esc(SCR_COLS[k][0])}</option>`).join('')}</select>`;
 const valid=rows.filter(r=>researchPlottable(r,x,y));
 return `<div class="explore-head"><h3>Explore the same results</h3><label>X ${selector('X',x)}</label><label>Y ${selector('Y',y)}</label></div><p class="faint">${valid.length.toLocaleString()} of ${rows.length.toLocaleString()} available matches plotted · ${rows.length-valid.length} missing or nonmeaningful. Click a point to inspect. Full results remain below.</p><canvas id="research-scatter" height="300" role="img" aria-label="Linked scatter plot of screen results"></canvas><div id="research-plot-selection" aria-live="polite"></div>`;
}
function researchPlottable(r,x,y) {return [x,y].every(k=>r[k]!=null && Number.isFinite(Number(r[k])) && (k!=='pe_ttm' || Number(r[k])>0));}
function researchPlot(rows) {
 const canvas=document.getElementById('research-scatter');if(!canvas)return;
 const ctx=canvas.getContext('2d'),x=window.__researchAxisX || 'pe_ttm',y=window.__researchAxisY || 'pct';
 const data=rows.filter(r=>researchPlottable(r,x,y));canvas.width=Math.max(300,canvas.clientWidth);const w=canvas.width,h=300,p=40;
 ctx.fillStyle='#0d1826';ctx.fillRect(0,0,w,h);if(!data.length){ctx.fillStyle='#adbed2';ctx.fillText('No valid data for these axes',p,p);return;}
 const xs=data.map(r=>Number(r[x])),ys=data.map(r=>Number(r[y]));const xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);
 ctx.strokeStyle='#34465b';ctx.beginPath();ctx.moveTo(p,p);ctx.lineTo(p,h-p);ctx.lineTo(w-p,h-p);ctx.stroke();ctx.fillStyle='#adbed2';ctx.font='12px sans-serif';ctx.fillText(fmtMag(xmin),p,h-15);ctx.fillText(fmtMag(xmax),w-90,h-15);ctx.fillText(fmtMag(ymax),2,p+4);ctx.fillText(fmtMag(ymin),2,h-p);
 const points=data.map(r=>({r,px:p+(Number(r[x])-xmin)/(xmax-xmin || 1)*(w-2*p),py:h-p-(Number(r[y])-ymin)/(ymax-ymin || 1)*(h-2*p)}));
 ctx.fillStyle='#48a0ff';ctx.globalAlpha=.65;for(const pt of points){ctx.beginPath();ctx.arc(pt.px,pt.py,3,0,Math.PI*2);ctx.fill();}ctx.globalAlpha=1;
 canvas.onclick=e=>{const rect=canvas.getBoundingClientRect(),px=(e.clientX-rect.left)*w/rect.width,py=e.clientY-rect.top;let best=null,dist=144;for(const pt of points){const d=(pt.px-px)**2+(pt.py-py)**2;if(d<dist){best=pt;dist=d;}}if(best){researchInspectRow(best.r);document.getElementById('research-plot-selection').textContent=best.r.symbol+' · '+SCR_COLS[x][0]+': '+fmtMag(best.r[x])+' · '+SCR_COLS[y][0]+': '+fmtMag(best.r[y]);}};
}
async function researchInspect(i) { const r=researchVisibleRows()[i];if(r)await researchInspectRow(r); }
async function researchInspectRow(r) {
 const el=document.getElementById('research-inspector');if(!el)return;
 const code=researchKey(r);window.__researchInspectCode=code;const gen=window.__inspectGen=(window.__inspectGen || 0)+1;
 const filters=window.__scr.filters || [],preset=window.__scr.activePreset;
 if(window.__inspectChart){try{window.klinecharts.dispose('inspect-chart');}catch(e){}window.__inspectChart=null;}
 el.classList.add('open');el.innerHTML=`<button class="btn ghost inspector-close" onclick="window.__researchInspectCode=null;this.parentElement.classList.remove('open')">Close preview</button><h2>${esc(r.symbol)}</h2><p>${esc(r.name)}</p><div class="inspector-price">${fmtAuto(r.price)} <small>${r.pct==null?'—':Number(r.pct).toFixed(2)+'%'}</small></div><div id="inspect-chart" style="height:220px"></div><h4>Screen context</h4>${filters.length?'<ul>'+filters.map(f=>`<li>${esc(fldStr(f))}<small>${preset ? (r.criterion_values?.[f.field]==null ? 'Provider-qualified; numeric evidence unavailable' : 'Provider value: '+esc(fmtMag(r.criterion_values[f.field]))+(f.days?' · '+f.days+'-day average':'')) : r[f.field]==null?'Value unavailable': 'Stored value: '+esc(fmtMag(r[f.field]))}</small></li>`).join('')+'</ul>':'<p class="faint">All stocks — no custom criteria.</p>'}<dl>${['market_cap','pe_ttm','pb','volume'].map(k=>`<dt>${esc(SCR_COLS[k][0])}</dt><dd>${r[k]==null?'—':esc(fmtMag(r[k]))}</dd>`).join('')}</dl><p class="faint">Stored quote · ${esc(r.update_time || r.updated_at || r.data_date || 'source time unavailable')}<br>Snapshot data; not a streaming feed.</p><button class="btn primary" onclick="researchOpen('${esc(code)}')">Open full research →</button><p class="faint">Overview · Options · Financials · Analysis · Company · News · Comments</p>`;
 if(window.__inspectChart){try{window.klinecharts.dispose('inspect-chart');}catch(e){}}
 const data=await api('/api/stock/'+encodeURIComponent(code)+'/candles?range=3M').catch(()=>null);if(gen!==window.__inspectGen || !document.getElementById('inspect-chart'))return;
 const bars=data?.bars || data?.candles || [];
 if(!bars.length){document.getElementById('inspect-chart').innerHTML='<p class="faint">Preview history unavailable. Open full research for chart sessions and intervals.</p>';return;}
 const c=window.klinecharts.init('inspect-chart');window.__inspectChart=c;klineTheme(c);
 c.applyNewData(bars.map(b=>({timestamp:typeof (b.time_key || b.time || b.timestamp || b.t)==='number' ? (b.time_key || b.time || b.timestamp || b.t) : Date.parse(b.time_key || b.time || b.timestamp || b.t),open:Number(b.open??b.o),high:Number(b.high??b.h),low:Number(b.low??b.l),close:Number(b.close??b.c),volume:Number(b.volume??b.v)||0})).filter(b=>Number.isFinite(b.timestamp)&&Number.isFinite(b.close)));
}
function researchDefinition() {const s=window.__scr;return {market:s.market,src:s.src || 'moo',etfs:!!s.etfs,watchlist_only:!!s.watchlistOnly,filters:scrEffFilters(),preset:s.activePreset || null};}
async function researchLoadChanges() {
 const el=document.getElementById('research-change-results');if(!el)return;
 try{const d=await api('/api/screener/changes?definition='+encodeURIComponent(JSON.stringify(researchDefinition())));if(document.getElementById('research-change-results')!==el)return;researchChangesRender(el,d);}catch(e){el.textContent='Snapshot history unavailable: '+e.message;}
}
function researchChangesRender(el,d) {
 if(!d.comparable){el.innerHTML=`<p class="faint">${esc(d.reason || 'Capture the first complete baseline, then another comparable snapshot.')}</p>`;return;}
 el.innerHTML=`<p class="faint">${esc(d.previous_at)} → ${esc(d.current_at)} · complete available-data snapshots</p><h4>${d.added.length} newly qualifying · ${d.exited.length} exited · ${d.unchanged} unchanged</h4>${[['Newly qualifying',d.added],['Exited',d.exited]].map(([title,rows])=>`<h4>${title}</h4>${rows.map(r=>`<button class="btn ghost" onclick="researchOpen('${esc(r.code)}')">${esc(r.symbol)} · ${esc(r.name || '')}</button>`).join('') || '<p class="faint">None</p>'}`).join('')}<p class="faint">Membership changes do not establish a buy/sell recommendation. Full research retains the evidence and chart tools.</p>`;
}
async function researchSnapshot() {
 const el=document.getElementById('research-change-results');el.textContent='Capturing and validating complete membership…';
 try{await api('/api/screener/snapshots',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(researchDefinition())});await researchLoadChanges();}catch(e){el.textContent='Capture unavailable: '+e.message;}
}

async function researchLoadMore() {
 const s=window.__scr,key=s.activePreset,market=s.market,ck=key+'|'+market,entry=(window.__presetCache || {})[ck];
 const current=entry?.payload;if(!key || !current?.next_key)return;
 const button=document.getElementById('research-load-more');if(button){button.disabled=true;button.textContent='Loading next provider page…';}
 try{const next=await api('/api/screener/execute?key='+encodeURIComponent(key)+'&market='+encodeURIComponent(market)+'&limit=300&next_key='+encodeURIComponent(current.next_key));
  if(!next.available)throw new Error(next.reason || 'Provider page unavailable');
  if(window.__scr.activePreset!==key || window.__scr.market!==market)return;
  const byCode=new Map(current.rows.map(r=>[r.code,r]));next.rows.forEach(r=>byCode.set(r.code,r));
  if(byCode.size===current.rows.length && next.possibly_truncated)throw new Error('Provider returned duplicate membership; previous results retained');
  window.__presetCache[ck]={ts:Date.now(),payload:{...next,rows:[...byCode.values()],result_limit:byCode.size}};
  await showPage('home');
 }catch(e){if(button){button.disabled=false;button.textContent='Retry next page';}const el=document.getElementById('research-page-status');if(el)el.textContent=e.message;}
}
