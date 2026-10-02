/* Private research: tab-scoped sessions, owner generations and durable lists.
   Public screener state/presets remain independent of account state. */
function researchAuthError(message,status=0){const e=new Error(message);e.status=status;return e;}
async function researchAuthFetch(path,opts={}) {
 const r=await fetch(path,{...opts,cache:'no-store'});
 if(!r.ok)throw researchAuthError(researchErrorMessage({message:await r.text()}),r.status);
 return r.json();
}
function researchSessionValid(s) {
 return !!s && typeof s.access_token==='string' && typeof s.refresh_token==='string' &&
  s.access_token.length>0 && s.access_token.length<=8192 && s.refresh_token.length>0 && s.refresh_token.length<=8192 &&
  Number.isFinite(s.expires_at) && /^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(s.user?.id || '');
}
function researchAccountButton() {
 const b=document.getElementById('research-account-button');if(b)b.textContent=window.__researchSession?'Account':'Sign in';
}
function researchDialogClose(keepDraft=true) {
 const el=window.__researchDialog;if(!el)return;
 if(keepDraft && el.querySelector('form[data-review]') && window.__researchReviewDraft){const form=el.querySelector('form[data-review]'),d=window.__researchReviewDraft;
  (window.__researchNoteDrafts ||= {})[d.list+'|'+d.code]={...d,note:form.elements.note.value,review_status:form.elements.review_status.value};}
 if(el.querySelector('input[name=password]'))window.__researchPendingAdd=null;
 window.__researchDialog=null;
 el.close?.();el.remove();if(window.__researchDialogOrigin?.isConnected)window.__researchDialogOrigin.focus();
}
function researchDialogLabel(el) {
 const title=el.querySelector('h2');if(title){title.id='research-dialog-title';el.setAttribute('aria-labelledby',title.id);el.removeAttribute('aria-label');}else{el.removeAttribute('aria-labelledby');el.setAttribute('aria-label','Research dialog');}
}
function researchDialogOpen(html) {
 researchDialogClose();const el=document.createElement('dialog');el.className='research-dialog';el.innerHTML=html;
 researchDialogLabel(el);
 window.__researchDialogOrigin=document.activeElement;window.__researchDialog=el;document.body.appendChild(el);
 el.addEventListener('cancel',e=>{e.preventDefault();researchDialogClose();});el.showModal();
 (el.querySelector('input,textarea') || el.querySelector('button'))?.focus();return el;
}
function researchPrivateClear(close=true) {
 const previousOwner=window.__researchSession?.user.id;
 if(close || previousOwner){try{sessionStorage.removeItem('researchListNavigationV1');const origin=JSON.parse(sessionStorage.getItem('researchOriginV1'));if(origin?.owner)sessionStorage.removeItem('researchOriginV1');}catch(e){}}
 window.__researchNavigationOwner=null;
 for(const url of window.__researchExportURLs || [])URL.revokeObjectURL(url);window.__researchExportURLs=new Set();
 window.__researchAuthGen=(window.__researchAuthGen || 0)+1;window.__researchListGen=(window.__researchListGen || 0)+1;
 window.__researchSession=null;window.__researchLists=[];window.__researchListItems=[];window.__researchCurrentList=null;window.__researchListID=null;
 window.__researchListOffset=0;window.__researchListsArchived=false;window.__researchUndo=null;window.__researchReviewDraft=null;window.__researchNoteDrafts={};window.__researchPendingAdd=null;
 window.__researchListSearch='';window.__researchListStatus='all';window.__researchReviewCursor=null;clearTimeout(window.__researchListSearchTimer);
 if(window.__researchContext?.kind==='shortlists')window.__researchContext=null;
 if(window.__researchPrivateInspect){researchCloseInspector(false);document.getElementById('research-inspector')?.replaceChildren();window.__researchPrivateInspect=false;}
 if(typeof state!=='undefined' && state.page==='shortlists'){const page=document.getElementById('page');if(page)page.innerHTML='<section class="panel"><h2>Private research cleared</h2><button class="btn ghost" onclick="researchAccountOpen()">Sign in</button></section>';}
 if(close || window.__researchDialog?.querySelector('form[data-review]'))researchDialogClose(false);
 try{sessionStorage.removeItem('researchAuthSessionV1');}catch(e){}
 researchAccountButton();
}
function researchSessionSet(s) {
 if(!researchSessionValid(s))throw researchAuthError('Authentication returned an unusable session.');
 if(window.__researchSession?.user.id!==s.user.id)researchPrivateClear(false);
 window.__researchSession=s;try{sessionStorage.setItem('researchAuthSessionV1',JSON.stringify(s));}catch(e){}
 researchAccountButton();
}
async function researchRefreshSession() {
 if(window.__researchRefresh)return window.__researchRefresh;
 const previous=window.__researchSession,gen=window.__researchAuthGen || 0;if(!previous)throw researchAuthError('Sign in to continue.',401);
 const pending=(async()=>{
  try{const s=await researchAuthFetch('/api/research/auth/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({refresh_token:previous.refresh_token})});
   if(gen!==(window.__researchAuthGen || 0))throw researchAuthError('Account changed. Please retry.',499);
   if(!researchSessionValid(s) || s.user.id!==previous.user.id){researchPrivateClear();throw researchAuthError('Session identity changed. Sign in again.',401);}
   researchSessionSet(s);return s;
  }catch(e){if(e.status===401 && gen===(window.__researchAuthGen || 0))researchPrivateClear();throw e;}
 })();window.__researchRefresh=pending;
 try{return await pending;}finally{if(window.__researchRefresh===pending)window.__researchRefresh=null;}
}
async function researchPrivateAPI(path,opts={}) {
 let s=window.__researchSession;if(!s)throw researchAuthError('Sign in to access your shortlists.',401);
 const gen=window.__researchAuthGen || 0,owner=s.user.id;
 if(s.expires_at<=Date.now()/1000+30)s=await researchRefreshSession();
 const run=()=>{if(gen!==(window.__researchAuthGen || 0) || owner!==window.__researchSession?.user.id)throw researchAuthError('Account changed. Please retry.',499);return researchAuthFetch(path,{...opts,headers:{...(opts.headers || {}),Authorization:'Bearer '+window.__researchSession.access_token}});};
 let data;try{data=await run();}catch(e){if(e.status!==401)throw e;if(gen!==(window.__researchAuthGen || 0))throw researchAuthError('Account changed. Please retry.',499);await researchRefreshSession();data=await run();}
 if(gen!==(window.__researchAuthGen || 0) || owner!==window.__researchSession?.user.id)throw researchAuthError('Account changed. Please retry.',499);
 return data;
}
async function researchAccountInit() {
 pages.shortlists=researchListsPage;
 let s;try{s=JSON.parse(sessionStorage.getItem('researchAuthSessionV1'));}catch(e){}
 if(researchSessionValid(s))researchSessionSet(s);
 researchAccountButton();
 if(!window.__researchSession)return;
 try{const d=await researchPrivateAPI('/api/research/session');if(d.owner_id!==window.__researchSession?.user.id)researchPrivateClear();}
 catch(e){if(e.status===401)researchPrivateClear();window.__researchAccountMessage=e.status===499?'':e.message;}
}
function researchAccountOpen() {
 const s=window.__researchSession;
 if(s){researchDialogOpen(`<div class="dialog-heading"><h2>Research account</h2><button class="btn ghost" onclick="researchDialogClose()">Close</button></div><p>${esc(s.user.email || 'Signed in')}</p><p>Shortlists and notes belong to this account. Saved screen definitions and watchlists currently use the deployment's shared workspace.</p><button class="btn primary" onclick="researchDialogClose();showPage('shortlists')">Open shortlists</button><button class="btn ghost" onclick="researchSignOut()">Sign out of this session</button><p id="research-auth-status" role="status"></p>`);return;}
 researchDialogOpen(`<div class="dialog-heading"><h2>Sign in to research</h2><button class="btn ghost" onclick="researchDialogClose()">Close</button></div><p>Use your existing account to keep private shortlists and review notes. Screening remains available.</p><form onsubmit="event.preventDefault();researchSignIn(this)"><label>Email<input name="email" type="email" required maxlength="320" autocomplete="username"></label><label>Password<input name="password" type="password" required maxlength="1024" autocomplete="current-password"></label><button class="btn primary" type="submit">Sign in</button></form><p id="research-auth-status" role="status">${esc(window.__researchAccountMessage || '')}</p>${window.__researchPendingLogout?'<button class="btn ghost" onclick="researchRetrySignOut()">Retry server sign-out</button>':''}<p class="faint">Session retained for this tab. Passwords and research notes are not saved to browser storage.</p>`);
}
async function researchSignIn(form) {
 const el=window.__researchDialog,gen=window.__researchAuthGen || 0,button=form.querySelector('button[type=submit]'),status=el.querySelector('[role=status]');
 button.disabled=true;status.textContent='Signing in…';
 const password=form.elements.password.value;form.elements.password.value='';
 try{const s=await researchAuthFetch('/api/research/auth/sign-in',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:form.elements.email.value,password})});
  if(window.__researchDialog!==el || gen!==(window.__researchAuthGen || 0)){researchAuthFetch('/api/research/auth/sign-out',{method:'POST',headers:{Authorization:'Bearer '+s.access_token}}).catch(()=>{});return;}
  const pending=window.__researchPendingAdd;researchSessionSet(s);window.__researchAccountMessage='';researchDialogClose();window.__researchPendingAdd=null;if(pending)await researchShortlistPicker(pending);else await showPage('shortlists');
 }catch(e){if(window.__researchDialog===el)status.textContent=e.message;}finally{if(button.isConnected)button.disabled=false;}
}
async function researchSignOut() {
 const token=window.__researchSession?.access_token;researchPrivateClear();window.__researchAccountMessage='';
 if(state.page==='shortlists')showPage('shortlists');
 if(!token)return;
 try{await researchAuthFetch('/api/research/auth/sign-out',{method:'POST',headers:{Authorization:'Bearer '+token}});window.__researchPendingLogout=null;}
 catch(e){window.__researchPendingLogout=token;window.__researchAccountMessage='Private data cleared here. Server sign-out could not be confirmed. Retry sign-out.';researchAccountOpen();}
}
async function researchRetrySignOut() {
 const token=window.__researchPendingLogout;if(!token)return;
 try{await researchAuthFetch('/api/research/auth/sign-out',{method:'POST',headers:{Authorization:'Bearer '+token}});window.__researchPendingLogout=null;window.__researchAccountMessage='Server sign-out confirmed.';}
 catch(e){window.__researchAccountMessage='Server sign-out is still unavailable. Please retry.';}researchAccountOpen();
}
function researchListIDValid(id){return typeof id==='string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);}
function researchListNavigationRestore() {
 const owner=window.__researchSession?.user.id;if(!owner || window.__researchNavigationOwner===owner)return;
 window.__researchNavigationOwner=owner;
 let saved;try{saved=JSON.parse(sessionStorage.getItem('researchListNavigationV1'));}catch(e){}
 const requested=window.__researchRouteList;
 if(saved?.version===1 && saved.owner===owner && researchListIDValid(saved.listID) && (!requested || requested===saved.listID)){
  window.__researchListID=saved.listID;
  window.__researchListOffset=Number.isSafeInteger(saved.offset) && saved.offset>=0 && saved.offset<=10000000?saved.offset:0;
  window.__researchListSearch=typeof saved.q==='string'?saved.q.slice(0,80):'';
  window.__researchListStatus=['all','unreviewed','in_review','reviewed'].includes(saved.status)?saved.status:'all';
  window.__researchListsArchived=saved.archived===true;
 }
 if(requested && requested!==window.__researchListID){window.__researchListID=requested;window.__researchListOffset=0;window.__researchListSearch='';window.__researchListStatus='all';}
 window.__researchRouteList=null;
}
function researchListNavigationPersist() {
 const owner=window.__researchSession?.user.id;if(!owner || !researchListIDValid(window.__researchListID))return;
 try{sessionStorage.setItem('researchListNavigationV1',JSON.stringify({version:1,owner,listID:window.__researchListID,offset:window.__researchListOffset || 0,q:window.__researchListSearch || '',status:window.__researchListStatus || 'all',archived:window.__researchListsArchived===true}));}catch(e){}
 const hash='#/shortlists/'+encodeURIComponent(window.__researchListID);if(state.page==='shortlists' && location.hash!==hash)history.replaceState(null,'',hash);
}
function researchListChoice(id) {window.__researchListID=id;window.__researchListOffset=0;window.__researchReviewCursor=null;showPage('shortlists');}
function researchListQuote(item) {const r=item.quote;return r?.code===item.code?r:{code:item.code,symbol:item.code.split('.').slice(1).join('.'),name:'Quote unavailable'};}
function researchListQuery(extra={}) {
 return new URLSearchParams({q:window.__researchListSearch || '',review_status:window.__researchListStatus || 'all',...extra}).toString();
}
function researchListActions(item,list) {
 const r=researchListQuote(item),code=esc(JSON.stringify(item.code)),disabled=list.active?'':'disabled';
 return `<div class="shortlist-row-actions"><button class="btn ghost" aria-label="Inspect ${esc(r.symbol)}" onclick="researchListInspect(${code},this)">Inspect</button><button class="btn ghost" aria-label="Review ${esc(r.symbol)} notes" onclick="researchReviewOpen(${code})" ${disabled}>Review</button><button class="btn ghost" aria-label="Remove ${esc(r.symbol)} from shortlist" onclick="researchListRemove(${code})" ${disabled}>Remove</button></div>`;
}
function researchListPrice(item) {
 const r=researchListQuote(item),currency=r.currency || (item.code.startsWith('US.')?'USD':item.code.startsWith('HK.')?'HKD':'');
 return `${esc(currency)} ${esc(researchValue('price',r.price))}<small>${esc(researchValue('pct',r.pct))}</small><small>${item.quote_cache_at?'Cache updated '+esc(fmtTs(item.quote_cache_at)):'Quote cache time unavailable'}</small>`;
}
function researchListIdentity(item) {
 const r=researchListQuote(item);return `<a href="#" onclick="event.preventDefault();researchListOpenStock(${esc(JSON.stringify(item.code))})">${esc(r.symbol)}</a><small>${esc(r.name)}</small><small>${esc(item.code)}</small>`;
}
function researchListRow(item,list) {
 return `<tr><td>${researchListIdentity(item)}</td><td>${researchListPrice(item)}</td><td>${esc(item.review_status.replaceAll('_',' '))}</td><td>${esc(item.note?.slice(0,100) || 'No note')}</td><td>${researchListActions(item,list)}</td></tr>`;
}
function researchListCard(item,list) {
 return `<article class="shortlist-card"><div class="shortlist-card-heading"><div>${researchListIdentity(item)}</div><div>${researchListPrice(item)}</div></div><p>Review: ${esc(item.review_status.replaceAll('_',' '))}</p><p>${esc(item.note?.slice(0,100) || 'No note')}</p>${researchListActions(item,list)}</article>`;
}
function researchListSearch(input) {
 clearTimeout(window.__researchListSearchTimer);
 if(input.value.length>80 || /[\x00-\x1f\x7f]/.test(input.value)){document.getElementById('research-list-status').textContent='Use up to 80 visible characters for ticker or company search.';return;}
 window.__researchListSearch=input.value;window.__researchListOffset=0;window.__researchReviewCursor=null;
 const value=input.value,caret=input.selectionStart,list=window.__researchListID,gen=window.__researchListGen;
 window.__researchListSearchTimer=setTimeout(async()=>{if(state.page!=='shortlists' || window.__researchListID!==list || window.__researchListGen!==gen || window.__researchListSearch!==value)return;
  await showPage('shortlists');if(state.page!=='shortlists' || window.__researchListID!==list || window.__researchListSearch!==value)return;
  const next=document.getElementById('research-list-search');if(next){next.focus();next.setSelectionRange(caret,caret);}},220);
}
function researchListStatus(value) {
 if(!['all','unreviewed','in_review','reviewed'].includes(value))return;
 window.__researchListStatus=value;window.__researchListOffset=0;window.__researchReviewCursor=null;showPage('shortlists');
}
async function researchNextUnreviewed() {
 const id=window.__researchListID,gen=window.__researchListGen;if(!id || !window.__researchCurrentList?.active)return;
 const base='/api/research/lists/'+encodeURIComponent(id)+'/items?',query={limit:1,offset:0,review_status:'unreviewed'},after=window.__researchReviewCursor;
 try{let d=await researchPrivateAPI(base+researchListQuery({...query,...(after?{after_code:after}:{})}));
  if(!d.items.length && after)d=await researchPrivateAPI(base+researchListQuery(query));
  if(gen!==window.__researchListGen || id!==window.__researchListID)return;
  if(!d.items.length){document.getElementById('research-list-status').textContent='No unreviewed stocks match this search.';return;}
  researchReviewOpen(d.items[0].code,d.items[0]);
 }catch(e){if(gen===window.__researchListGen){const el=document.getElementById('research-list-status');if(el)el.textContent=e.message;}}
}
async function researchListsPage() {
 await window.__researchAccountReady;
 researchListNavigationRestore();
 const gen=(window.__researchListGen || 0)+1;window.__researchListGen=gen;
 if(!window.__researchSession)return `<section class="panel research-lists-empty"><h2>Research shortlists</h2><p>Keep named lists, notes and review status independently of screens and watchlists.</p><button class="btn primary" onclick="researchAccountOpen()">Sign in to open shortlists</button><button class="btn ghost" onclick="showPage('home')">Back to screener</button></section>`;
 try{const d=await researchPrivateAPI('/api/research/lists?include_archived='+(window.__researchListsArchived?'true':'false'));
  if(gen!==window.__researchListGen)return '';
  window.__researchLists=d.lists;
  const list=d.lists.find(r=>r.id===window.__researchListID) || d.lists.find(r=>r.active) || d.lists[0];
  window.__researchListID=list?.id || null;
  const data=list?await researchPrivateAPI('/api/research/lists/'+encodeURIComponent(list.id)+'/items?'+researchListQuery({offset:window.__researchListOffset || 0,limit:100})):null;
  if(gen!==window.__researchListGen)return '';
  window.__researchListItems=data?.items || [];window.__researchCurrentList=data?.list || list;
  const current=window.__researchCurrentList,items=window.__researchListItems;
  researchListNavigationPersist();
  return `<div class="research-lists-layout"><aside class="panel shortlist-library"><label>Shortlist<select aria-label="Choose shortlist" onchange="researchListChoice(this.value)">${d.lists.map(r=>`<option value="${esc(r.id)}" ${r.id===current?.id?'selected':''}>${esc(r.name)}${r.active?'':' · Archived'}</option>`).join('') || '<option>No shortlists yet</option>'}</select></label><details class="shortlist-library-actions"><summary>Manage lists</summary><button class="btn primary" onclick="researchListCreateOpen()">New shortlist</button><label><input type="checkbox" ${window.__researchListsArchived?'checked':''} onchange="window.__researchListsArchived=this.checked;showPage('shortlists')"> Show archived</label><button class="btn ghost" onclick="showPage('home')">Back to screener</button></details>${d.possibly_truncated?'<p>First 500 lists loaded. More lists may exist.</p>':''}</aside><main class="panel shortlist-main"><div class="shortlist-heading"><div><h2>${esc(current?.name || 'Start your research list')}</h2><p>${esc(current?.description || 'Private to your account · separate from watchlists and saved screens')}</p></div>${current?`<details class="shortlist-heading-actions"><summary>List actions</summary><button class="btn ghost" onclick="researchListEditOpen()">Edit shortlist</button><button class="btn ghost" onclick="researchListExport()">Export full shortlist CSV</button></details>`:''}</div>${current && !current.active?'<p class="delay-note">Archived shortlist. Restore it from Edit shortlist to add or review stocks.</p>':''}${current?`<div class="shortlist-tools"><label>Find stock<input id="research-list-search" aria-label="Find shortlist stock" maxlength="80" value="${esc(window.__researchListSearch || '')}" placeholder="Ticker or company name" oninput="researchListSearch(this)"></label><label>Review status<select aria-label="Filter shortlist review status" onchange="researchListStatus(this.value)">${['all','unreviewed','in_review','reviewed'].map(v=>`<option value="${v}" ${v===(window.__researchListStatus || 'all')?'selected':''}>${v==='all'?'All reviews':v.replaceAll('_',' ')}</option>`).join('')}</select></label><button class="btn ghost" onclick="researchNextUnreviewed()" ${current.active?'':'disabled'}>Next unreviewed</button></div>`:''}<p id="research-list-status" role="status">${items.length} stocks on this page${data?.has_more?' · more stocks available':''}${window.__researchListSearch || (window.__researchListStatus || 'all')!=='all'?' · filtered review':''}</p>${window.__researchUndo?.list===current?.id?'<button class="btn ghost" onclick="researchListUndo()">Undo last removal</button>':''}<div class="shortlist-table"><table><thead><tr><th>Stock</th><th>Stored price</th><th>Review</th><th>Note</th><th>Actions</th></tr></thead><tbody>${items.map(item=>researchListRow(item,current)).join('')}</tbody></table></div><div class="shortlist-mobile">${items.map(item=>researchListCard(item,current)).join('')}</div>${current && !items.length?'<p>No stocks in this review. Change stock/status filters or add stocks through Inspect → Add to shortlist. Company names use stored quotes; try the ticker if its name is unavailable.</p>':''}<div class="pager"><button class="btn ghost" onclick="researchListPage(-1)" ${(window.__researchListOffset || 0)<=0?'disabled':''}>Previous shortlist page</button><button class="btn ghost" onclick="researchListPage(1)" ${data?.has_more?'':'disabled'}>Next shortlist page</button></div></main><aside id="research-inspector" class="research-inspector"></aside></div>`;
 }catch(e){if(gen!==window.__researchListGen || e.status===499)return '';return `<section class="panel"><h2>Shortlists unavailable</h2><p>${esc(e.message)}</p><button class="btn ghost" onclick="showPage('shortlists')">Retry shortlists</button><button class="btn ghost" onclick="researchAccountOpen()">Account</button></section>`;}
}
function researchListPage(delta) {window.__researchListOffset=Math.max(0,(window.__researchListOffset || 0)+delta*100);showPage('shortlists');}
function researchListCreateOpen() {researchListForm(null);}
function researchListEditOpen() {researchListForm(window.__researchCurrentList);}
function researchListForm(list) {
 researchDialogOpen(`<div class="dialog-heading"><h2>${list?'Edit shortlist':'New shortlist'}</h2><button class="btn ghost" onclick="researchDialogClose()">Close</button></div><form onsubmit="event.preventDefault();researchListSave(this,${list?'true':'false'})"><label>Name<input name="name" required maxlength="80" value="${esc(list?.name || '')}"></label><label>Description<textarea name="description" maxlength="500">${esc(list?.description || '')}</textarea></label>${list?`<label><input name="active" type="checkbox" ${list.active?'checked':''}> Active (uncheck to archive; notes remain recoverable)</label>`:''}<button class="btn primary" type="submit">Save shortlist</button></form><p role="status"></p>${list?'<button class="btn ghost" onclick="researchListLatest()">Load latest shortlist to compare</button><div id="research-latest-list"></div>':''}`);
}
async function researchListSave(form,edit) {
 const el=window.__researchDialog,list=window.__researchCurrentList,status=el.querySelector('[role=status]'),button=form.querySelector('button[type=submit]');button.disabled=true;
 try{const body={name:form.elements.name.value,description:form.elements.description.value};if(edit){body.revision=list.revision;body.active=form.elements.active.checked;}
  const data=await researchPrivateAPI('/api/research/lists'+(edit?'/'+encodeURIComponent(list.id):''),{method:edit?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(window.__researchDialog!==el)return;window.__researchListID=data.list.id;window.__researchListOffset=0;researchDialogClose();await showPage('shortlists');
 }catch(e){if(window.__researchDialog===el)status.textContent=e.message+(e.status===409?' Your draft is retained. Load the latest shortlist to compare before saving.':'');}finally{if(button.isConnected)button.disabled=false;}
}
async function researchListLatest() {
 const el=window.__researchDialog,id=window.__researchCurrentList?.id;if(!id)return;
 try{const d=await researchPrivateAPI('/api/research/lists/'+encodeURIComponent(id));if(window.__researchDialog!==el)return;
  window.__researchCurrentList=d.list;el.querySelector('#research-latest-list').innerHTML=`<h3>Latest shortlist · revision ${d.list.revision}</h3><p>${esc(d.list.name)}</p><p>${esc(d.list.description)}</p><p>${d.list.active?'Active':'Archived'} · Your draft is unchanged. Save applies it to this revision.</p>`;
 }catch(e){if(window.__researchDialog===el)el.querySelector('[role=status]').textContent=e.message;}
}
async function researchShortlistPicker(code) {
 if(!window.__researchSession){window.__researchPendingAdd=code;researchAccountOpen();return;}
 const el=researchDialogOpen('<div class="dialog-heading"><h2>Add to shortlist</h2><button class="btn ghost" onclick="researchDialogClose()">Close</button></div><p role="status">Loading your lists…</p>');
 try{const d=await researchPrivateAPI('/api/research/lists');if(window.__researchDialog!==el)return;
  el.innerHTML=`<div class="dialog-heading"><h2>Add ${esc(code)} to shortlist</h2><button class="btn ghost" onclick="researchDialogClose()">Close</button></div><p>Existing notes and review status are preserved.</p>${d.lists.length?`<label>Shortlist<select id="research-shortlist-choice">${d.lists.map(r=>`<option value="${esc(r.id)}">${esc(r.name)}</option>`).join('')}</select></label><button class="btn primary" onclick="researchShortlistAdd(${esc(JSON.stringify(code))})">Add stock</button>`:'<p>Create a shortlist to start keeping research.</p>'}<button class="btn ghost" onclick="researchDialogClose();showPage('shortlists')">Manage shortlists</button><p role="status"></p>`;researchDialogLabel(el);el.querySelector('select,button')?.focus();
 }catch(e){if(window.__researchDialog===el)el.querySelector('[role=status]').textContent=e.message;}
}
async function researchShortlistAdd(code) {
 const el=window.__researchDialog,id=el.querySelector('select').value,status=el.querySelector('[role=status]'),button=el.querySelector('button.primary');button.disabled=true;
 try{await researchPrivateAPI('/api/research/lists/'+encodeURIComponent(id)+'/items',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code})});if(window.__researchDialog===el){status.textContent='Stock added. Existing research retained.';button.textContent='Added';}}
 catch(e){if(window.__researchDialog===el){status.textContent=e.message;button.disabled=false;}}
}
function researchReviewOpen(code,record=null) {
 const item=record || window.__researchListItems.find(r=>r.code===code);if(!item)return;researchDialogClose();
 const restored=window.__researchNoteDrafts?.[window.__researchListID+'|'+code];
 const values=restored || item;window.__researchReviewDraft={list:window.__researchListID,code,revision:values.revision};window.__researchReviewCursor=code;
 researchDialogOpen(`<div class="dialog-heading"><h2>Review ${esc(code)}</h2><button class="btn ghost" onclick="researchDialogClose()">Close</button></div><form data-review onsubmit="event.preventDefault();researchReviewSave(this)"><label>Review status<select name="review_status">${['unreviewed','in_review','reviewed'].map(v=>`<option value="${v}" ${v===values.review_status?'selected':''}>${v.replaceAll('_',' ')}</option>`).join('')}</select></label><label>Research note<textarea name="note" maxlength="4000" rows="8">${esc(values.note)}</textarea></label><button class="btn primary" type="submit">Save review</button></form><p role="status">${restored?'Unsaved draft restored. Save review to persist it; reload or sign-out discards drafts.':''}</p><button class="btn ghost" onclick="researchReviewLatest()">Load latest review to compare</button><div id="research-latest-review"></div>`);
}
async function researchReviewSave(form) {
 const el=window.__researchDialog,draft={...window.__researchReviewDraft},status=el.querySelector('[role=status]'),button=form.querySelector('button[type=submit]');button.disabled=true;
 try{await researchPrivateAPI('/api/research/lists/'+encodeURIComponent(draft.list)+'/items/'+encodeURIComponent(draft.code),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:draft.revision,note:form.elements.note.value,review_status:form.elements.review_status.value})});
  if(window.__researchDialog!==el)return;delete window.__researchNoteDrafts?.[draft.list+'|'+draft.code];researchDialogClose(false);await showPage('shortlists');
 }catch(e){if(window.__researchDialog===el)status.textContent=e.message+(e.status===409?' Your draft is retained. Load the latest review to compare before saving.':'');}finally{if(button.isConnected)button.disabled=false;}
}
async function researchReviewLatest() {
 const el=window.__researchDialog,draft={...window.__researchReviewDraft};
 try{const d=await researchPrivateAPI('/api/research/lists/'+encodeURIComponent(draft.list)+'/items/'+encodeURIComponent(draft.code));if(window.__researchDialog!==el)return;
  window.__researchReviewDraft.revision=d.item.revision;const save=el.querySelector('button[type=submit]');save.disabled=!d.item.active;el.querySelector('#research-latest-review').innerHTML=`<h3>Latest saved review · revision ${d.item.revision}</h3><p>${esc(d.item.review_status.replaceAll('_',' '))}</p><pre>${esc(d.item.note || 'No note')}</pre><p>${d.item.active?'Your draft above is unchanged. Save review applies it to this revision.':'This stock was removed from the list. Your draft is retained; restore membership before saving.'}</p>`;
 }catch(e){if(window.__researchDialog===el)el.querySelector('[role=status]').textContent=e.message;}
}
async function researchListRemove(code) {
 const item=window.__researchListItems.find(r=>r.code===code),id=window.__researchListID;if(!item)return;
 try{await researchPrivateAPI('/api/research/lists/'+encodeURIComponent(id)+'/items/'+encodeURIComponent(code),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:item.revision,active:false})});window.__researchUndo={list:id,code};await showPage('shortlists');}
 catch(e){const el=document.getElementById('research-list-status');if(el)el.textContent=e.message;}
}
async function researchListUndo() {
 const undo=window.__researchUndo;if(!undo)return;
 try{await researchPrivateAPI('/api/research/lists/'+encodeURIComponent(undo.list)+'/items',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:undo.code})});window.__researchUndo=null;await showPage('shortlists');}
 catch(e){const el=document.getElementById('research-list-status');if(el)el.textContent=e.message;}
}
function researchListInspect(code,origin) {
 const item=window.__researchListItems.find(r=>r.code===code);if(!item)return;
 window.__inspectOrigin=origin;window.__researchPrivateInspect=true;researchInspectRow(researchListQuote(item),{focus:true});
}
function researchListOpenStock(code) {
 window.__researchContext={kind:'shortlists',listID:window.__researchListID,offset:window.__researchListOffset || 0,q:window.__researchListSearch || '',review_status:window.__researchListStatus || 'all',scroll:window.scrollY || 0,
  rows:window.__researchListItems.map(r=>({code:r.code,symbol:researchListQuote(r).symbol})),selected:[]};researchListNavigationPersist();researchOriginPersist();openStock(code);
}
function researchListCSV(list,items) {
 const cell=researchCSVCell,issues=[];
 const rows=items.map(item=>{const r=researchListQuote(item),bad=r.price!=null && !(typeof r.price==='number' && Number.isFinite(r.price));
  const issue=bad?[{field:'price',reason:'invalid_numeric',source_value:r.price}]:[];issues.push(issue);
  return [list.name,list.revision,item.code,r.symbol,r.name,bad?'Unavailable':r.price,r.currency,item.quote_cache_at,item.review_status,item.note];});
 const headers=['list_name','list_revision','code','symbol','name','price','currency','quote_cache_at','review_status','note'];
 if(issues.some(issue=>issue.length)){headers.push('export_value_issues');rows.forEach((row,i)=>row.push(issues[i]));}
 return '\ufeff'+[headers,...rows].map(row=>row.map(cell).join(',')).join('\n');
}
async function researchListExport() {
 const id=window.__researchListID,gen=window.__researchAuthGen || 0,status=document.getElementById('research-list-status');if(!id)return;
 if(status)status.textContent='Preparing full shortlist CSV…';
 try{let items=[],list;for(let offset=0;offset<40000;offset+=500){const d=await researchPrivateAPI('/api/research/lists/'+encodeURIComponent(id)+'/items?limit=500&offset='+offset);
   if(list && list.revision!==d.list.revision)throw Error('The shortlist changed during export. Retry with the current list.');list=d.list;items.push(...d.items);if(!d.has_more)break;if(!d.items.length || offset===39500)throw Error('Shortlist export is incomplete.');}
  const final=await researchPrivateAPI('/api/research/lists/'+encodeURIComponent(id)+'/items?limit=1');if(final.list.revision!==list.revision || new Set(items.map(r=>r.code)).size!==items.length)throw Error('Shortlist changed or duplicate identities were returned. Retry export.');
  if(gen!==(window.__researchAuthGen || 0))return;const blob=new Blob([researchListCSV(list,items)],{type:'text/csv;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='shortlist_'+id+'.csv';a.textContent='Download prepared shortlist CSV';(window.__researchExportURLs ||= new Set()).add(a.href);
  if(status?.isConnected && typeof status.appendChild==='function'){status.textContent=items.length+' stocks prepared · Download link available for 5 minutes. ';status.appendChild(a);}else document.body.appendChild(a);
  a.click();if(!status?.isConnected)a.remove();const url=a.href;setTimeout(()=>{URL.revokeObjectURL(url);window.__researchExportURLs?.delete(url);if(a.isConnected){a.remove();if(status?.isConnected)status.textContent='Prepared download link expired. Export again to download.';}},300000);
 }catch(e){if(gen===(window.__researchAuthGen || 0) && status?.isConnected!==false && status)status.textContent='Export unavailable: '+e.message;}
}
