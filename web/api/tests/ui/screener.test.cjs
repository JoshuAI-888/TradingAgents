const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../../static/index.html'), 'utf8');
const helper = fs.readFileSync(require('node:path').join(__dirname, '../../static/research-workspace.js'),'utf8');
const account = fs.readFileSync(require('node:path').join(__dirname, '../../static/research-account.js'),'utf8');
const script = helper + '\n' + account + '\n' + [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].slice(1).map(m=>m[1]).join('\n');
function harness(saved = {}, hash = '') {
  const page = {innerHTML:'existing screener'};
  const elements = new Map([['page',page]]);
  const document = {querySelector: s => s === '#page' ? page : null, querySelectorAll:()=>[],
    getElementById:id=>elements.get(id), addEventListener(){}, visibilityState:'visible',
    createElement:()=>({style:{},remove(){}}), body:{appendChild(){}}};
  const c = {__researchExtendedWorkspace:true,document, localStorage:{getItem:k=>k==='scrState'?JSON.stringify(saved):null,setItem(){}},
    location:{hash,pathname:'/',search:''}, history:{replaceState(_a,_b,h){c.location.hash=h;},pushState(_a,_b,h){c.location.hash=h;}},
    sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},URLSearchParams, URL, console, setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},
    fetch:async()=>({ok:true,json:async()=>({})})};
  c.window=c; c.addEventListener=()=>{}; c.scrollTo=()=>{};
  vm.createContext(c);
  vm.runInContext(script.slice(0, script.indexOf('document.querySelectorAll(".nav button").forEach(b => b.onclick')),c);
  c.render = vm.runInContext('showPage',c);
  c.showPage=()=>{};
  return c;
}
const stock = (symbol,cap,pct,extra={})=>({symbol,market_cap:cap,pct,stock_type:'STOCK',...extra});
test('research headers reject price sentinels and HK extended-hour placeholders while preserving negative ratios',async()=>{
 const c=harness();vm.runInContext('state.page="stock"',c);const st=c.stkState();st.sym='HK.00700';st.tab='overview';
 let quote={code:'HK.00700',last_price:421.2,prev_close_price:431,pre_price:0,after_price:0,lowest_history_price:-23.001796322,pe_ratio:-2,bid_ask_ratio:-10.76,update_time:1790928485000};
 c.api=async()=>quote;c.stkHeaderSwitch=async()=>'';c.stkTabPage=async()=>'';c.stkMountControls=c.stkLoadChart=c.klineTeardown=()=>{};
 await c.renderStock();let html=c.document.querySelector('#page').innerHTML;
 assert.doesNotMatch(html,/Pre-market|After-hours|-23\.002/);assert.match(html,/GMT\+8|HKT/);assert.match(html,/-10\.76%/);assert.match(html,/>-2</);assert.match(html,/stk-px r/);
 quote={...quote,pre_price:500,after_price:500};await c.renderStock();assert.doesNotMatch(c.document.querySelector('#page').innerHTML,/Pre-market|After-hours/);
 st.sym='AAPL';quote={...quote,code:'US.AAPL',last_price:0,prev_close_price:-1,pre_price:0,after_price:0};await c.renderStock();html=c.document.querySelector('#page').innerHTML;
 assert.doesNotMatch(html,/Pre-market|After-hours|▼ -1/);
 quote={...quote,last_price:200,prev_close_price:201,pre_price:199,after_price:202};await c.renderStock();html=c.document.querySelector('#page').innerHTML;
 assert.match(html,/Pre-market \(ET\)/);assert.match(html,/After-hours \(ET\)/);assert.doesNotMatch(html,/04:00|19:30/);
});
test('HK chart dates and event matching use the source trading day without changing OHLC',()=>{
 const c=harness(),t=1790870400000;assert.equal(new Date(t).toISOString().slice(0,10),'2026-10-01');
 assert.equal(c.stockTradingDate(t,'HK.00700'),'2026-10-02');assert.equal(c.stockTradingDate(1790913600000,'US.AAPL'),'2026-10-02');
 const bars=c.cmpSanitizeBars([{time_key:t,open:422,high:425,low:419.8,close:421.2,volume:19108045}]);
 const mapped=c.cmpMapData({sym:'HK.00700',bars})[0];assert.equal(mapped.timestamp,t);assert.equal(mapped.tradingDate,'2026-10-02');assert.equal(mapped.open,422);assert.equal(mapped.close,421.2);
 const el={innerHTML:''};c.document.getElementById=id=>id==='cmp-readout-0'?el:null;
 c.__cmp={cells:[{sym:'HK.00700',events:true,_ev:{earn:{'2026-10-02':{type:'BMC'}},div:{}}}]};c.__cmpHosts=[{chart:{getDataList:()=>[mapped]}}];c.cmpReadout(0,{kLineData:mapped});assert.match(el.innerHTML,/E 2026-10-02 BMC/);
 const zones=[],chart={setTimezone:z=>zones.push(z),setDataLoader:()=>{},setSymbol:()=>{},setPeriod:()=>{},resetData:()=>{},setStyles:()=>{}};const host={elId:'cmp-kc-0',state:()=>({sym:'HK.00700'}),chart,drawingIds:[]};c.klineEnsure=()=>chart;c.klineApply=()=>{};
 c.klineSetData(host,[mapped]);assert.deepEqual(zones,['Asia/Hong_Kong']);
});
test('invalid bar timestamps cannot reach a chart or event-date formatter',async()=>{
 const c=harness(),rows=[{time_key:null,close:1},{time_key:'bad',close:1},{time_key:Infinity,close:1},{time_key:1000,close:1}];
 assert.equal(c.cmpSanitizeBars(rows).length,1);const store={};c.api=async()=>({bars:rows});await c.klineLoadLive(store,'A',{src:'range',range:'Q'});assert.equal(store.bars.length,1);
 c.api=async()=>({section_list:[{point_list:[{cur_price:1,time:'bad'},{cur_price:1,time:1000}]}]});await c.klineLoadLive(store,'A',{src:'intraday',kind:'FULL'});assert.equal(store.pts.length,1);
});
test('stock switchers and quote cards preserve HK prefixes and US share classes',async()=>{
 const c=harness(),hk={code:'HK.00700',symbol:'00700',name:'Tencent'},brk={code:'US.BRK.B',symbol:'BRK.B'};
 c.stkState().sym='HK.00700';assert.equal(c.stkCurrentMarket(),'HK');assert.equal(c.stkRowCode(hk),'HK.00700');assert.equal(c.stkRowCode({symbol:'BRK.B'}),'US.BRK.B');
 assert.match(c.stkDropRow(hk),/openStock\(&quot;HK\.00700&quot;\)/);assert.match(c.stkDropRow(brk),/US\.BRK\.B/);
 const drop={style:{},innerHTML:''};c.document.getElementById=id=>id==='stk-drop'?drop:null;
 vm.runInContext('__stkDropRows=[{code:"HK.00700",symbol:"00700"}]',c);let opened;c.openStock=s=>opened=s;
 c.stkSearchKey({key:'Enter',target:{value:'00700'}});assert.equal(opened,'HK.00700');
 c.__pk={market:'HK',q:'',sector:'',watchlist:false};c.stkUniverse=async()=>[hk];c.api=async()=>({rows:[]});
 assert.match(await c.stkPickerPage(),/openStock\(&quot;HK\.00700&quot;\)/);
 let market;c.stkUniverse=async m=>{market=m;return []};await c.stkHeaderSwitch('HK.00700');assert.equal(market,'HK');
});
test('late stock-universe and dropdown responses cannot restore a previous market or query',async()=>{
 const c=harness(),pending=[];c.api=url=>new Promise(resolve=>pending.push({url,resolve}));
 const us=c.stkUniverse('US'),hk=c.stkUniverse('HK');pending[1].resolve({rows:[{symbol:'00700',code:'HK.00700'}]});await hk;
 pending[0].resolve({rows:[{symbol:'AAPL',code:'US.AAPL'}]});await us;assert.equal(c.__stkUniverse.market,'HK');assert.equal(c.__stkUniverse.rows[0].code,'HK.00700');
 vm.runInContext('state.page="stock"',c);c.stkState().sym='HK.00700';const drop={style:{},innerHTML:''};c.document.getElementById=id=>id==='stk-drop'?drop:null;
 const searches=[];c.stkUniverse=()=>new Promise(resolve=>searches.push(resolve));
 const old=c.stkSearchDrop('00'),fresh=c.stkSearchDrop('007');searches[1]([{symbol:'00700',code:'HK.00700'}]);await fresh;const latest=drop.innerHTML;
 searches[0]([{symbol:'00005',code:'HK.00005'}]);await old;assert.equal(drop.innerHTML,latest);assert.match(latest,/00700/);
});
test('a delayed stock directory cannot replace a newer directory or an opened stock',async()=>{
 const c=harness(),pending=[],page=c.document.querySelector('#page');c.stkPickerPage=()=>new Promise(resolve=>pending.push(resolve));
 c.openStockPicker();c.openStockPicker();pending[1]('latest directory');await Promise.resolve();assert.equal(page.innerHTML,'latest directory');
 pending[0]('old directory');await Promise.resolve();assert.equal(page.innerHTML,'latest directory');
 c.openStockPicker();vm.runInContext('state.page="stock"',c);page.innerHTML='current stock';pending[2]('late directory');await Promise.resolve();assert.equal(page.innerHTML,'current stock');
});
test('chart loading distinguishes unavailable, empty and failed responses and offers retry',async()=>{
 const c=harness(),status={hidden:true,innerHTML:'',style:{}},node={};vm.runInContext('state.page="stock"',c);
 const st=c.stkState();st.sym='A';st.tab='overview';st.chart={src:'range',range:'Q',kind:'FULL'};
 c.document.getElementById=id=>id==='stk-kc'?node:id==='stk-kc-status'?status:null;c.klineSetData=()=>{};
 let resolve;c.api=()=>new Promise(r=>resolve=r);const pending=c.stkLoadChart();assert.match(status.innerHTML,/Loading A chart/);
 resolve({available:false,bars:[{close:22,time_key:1000}]});await pending;
 assert.match(status.innerHTML,/source unavailable/);assert.match(status.innerHTML,/Retry chart/);
 assert.equal(vm.runInContext('stkChartState.bars.length',c),0);
 c.api=async()=>({available:true,bars:[]});await c.stkLoadChart();assert.match(status.innerHTML,/No chart data/);
 c.api=async()=>{throw Error('private transport details')};await c.stkLoadChart();assert.match(status.innerHTML,/request failed/);assert.doesNotMatch(status.innerHTML,/private transport/);
 c.api=async()=>({available:true,bars:[{time_key:1000,close:22}]});await c.klineRetry('stk-kc');assert.equal(status.hidden,true);assert.equal(status.style.display,'none');
 assert.equal(vm.runInContext('stkChartState.bars[0].c',c),22);
});
test('unavailable intraday source cannot render embedded points as current data',async()=>{
 const c=harness(),store={};c.api=async()=>({available:false,section_list:[{point_list:[{time:1000,cur_price:22}]}]});
 await c.klineLoadLive(store,'A',{src:'intraday',kind:'FULL'});
 assert.equal(store.pts.length,0);assert.equal(store.status,'Chart source unavailable.');
});
test('stock and analysis chart responses commit only for the current ticker, tab and request',async()=>{
 for(const [loader,tab,nodeId,storeName] of [['stkLoadChart','overview','stk-kc','stkChartState'],['anaLoadChart','analysis','ana-kc','anaChartState']]){
  const c=harness(),pending=[],paint=[];let node={};
  vm.runInContext('state.page="stock"',c);const st=c.stkState();st.sym='A';st.tab=tab;
  c.document.getElementById=id=>id===nodeId?node:null;
  c.api=url=>new Promise(resolve=>pending.push({url,resolve}));c.klineSetData=(_h,data)=>paint.push(data);
  const a=c[loader]();st.sym='B';const b=c[loader]();
  const reply=value=>({bars:[{time_key:1000,close:value}],section_list:[{point_list:[{time:1000,cur_price:value}]}]});
  pending[1].resolve(reply(22));await b;pending[0].resolve(reply(11));await a;
  assert.equal(paint.length,1);assert.equal(paint[0][0].close,22);
  const stale=c[loader]();st.tab='news';pending[2].resolve(reply(33));await stale;assert.equal(paint.length,1);
  st.tab=tab;const replaced=c[loader]();node={};pending[3].resolve(reply(44));await replaced;assert.equal(paint.length,1);
  assert.equal(vm.runInContext(`(${storeName}.bars.length?${storeName}.bars:${storeName}.pts)[0].c`,c),22);
  const first=c[loader](),latest=c[loader]();pending[5].resolve(reply(66));await latest;pending[4].resolve(reply(55));await first;
  assert.equal(paint.length,2);assert.equal(paint[1][0].close,66);
 }
});
test('Compare rejects obsolete ranges, removed panels and ticker event responses',async()=>{
 const c=harness(),pending=[],paint=[];vm.runInContext('state.page="compare"',c);
 const cell={sym:'A',range:'Q',ext:false,_ev:{}},host={};c.__cmp={cells:[cell]};c.__cmpHosts=[host];c.__cmpData={};
 c.api=url=>new Promise(resolve=>pending.push({url,resolve}));c.klineSetData=(_h,data)=>paint.push(data);
 c.cmpApplyOvls=c.cmpApplyEvt=c.cmpBindSync=c.cmpEqualize=()=>{};
 const old=c.cmpLoadCell(0);cell.range='Y';const fresh=c.cmpLoadCell(0);
 pending[1].resolve({bars:[{time_key:1000,close:22}]});await fresh;
 pending[0].resolve({bars:[{time_key:1000,close:11}]});await old;
 assert.equal(paint.length,1);assert.equal(cell.bars[0].c,22);assert.equal(c.__cmpData['A|Q'],undefined);
 const removed=c.cmpLoadCell(0,true);c.__cmp.cells[0]={sym:'B',range:'Y'};pending[2].resolve({bars:[{time_key:1000,close:33}]});await removed;
 assert.equal(paint.length,1);
 c.__cmp.cells[0]=cell;const events=c.cmpLoadEvents(0);cell.sym='B';pending.slice(3).forEach(p=>p.resolve({list:[{ex_date:'2026-01-01'}],calendar:{'Earnings Date':'2026-01-02'}}));await events;
 assert.equal(cell._ev.next,undefined);
});
test('Compare studies opening and closing preserves keyboard origin without scrolling',()=>{
 const c=harness(),calls=[];
 const opener={isConnected:true,focus:opts=>calls.push(['opener',opts.preventScroll])};
 const close={focus:opts=>calls.push(['close',opts.preventScroll])};
 const drawer={style:{display:'none'},querySelector:()=>close};
 c.document.activeElement=opener;c.document.getElementById=id=>id==='cmp-drawer'?drawer:null;c.cmpDrawerRender=()=>{};
 c.cmpDrawer(true);assert.equal(drawer.style.display,'block');assert.equal(c.__cmpDrawerFocus,opener);
 c.document.activeElement=close;c.cmpDrawer(true);assert.equal(c.__cmpDrawerFocus,opener);
 c.cmpDrawer(false);assert.equal(drawer.style.display,'none');assert.equal(c.__cmpDrawerFocus,null);
 assert.deepEqual(calls,[['close',true],['close',true],['opener',true]]);
 c.document.activeElement=opener;c.cmpDrawer(true);opener.isConnected=false;c.cmpDrawer(false);
 assert.equal(calls.filter(x=>x[0]==='opener').length,1);
});
test('Compare quote polling cannot replace a newer quote or a rebuilt workspace',async()=>{
 const c=harness(),pending=[],quote={innerHTML:''};let grid={};vm.runInContext('state.page="compare"',c);
 c.__cmp={cells:[{sym:'A'}]};c.document.getElementById=id=>id==='cmp-grid'?grid:id==='cmp-q-0'?quote:null;
 c.api=()=>new Promise(resolve=>pending.push(resolve));
 const old=c.cmpQuotePoll(),fresh=c.cmpQuotePoll();const reply=p=>({available:true,quotes:{A:{last_price:p,pct_change:1,volume:1}}});
 pending[1](reply(22));await fresh;const latestHTML=quote.innerHTML;assert.match(latestHTML,/22\.00/);
 pending[0](reply(11));await old;assert.equal(quote.innerHTML,latestHTML);
 const rebuilt=c.cmpQuotePoll();grid={};pending[2](reply(33));await rebuilt;assert.equal(quote.innerHTML,latestHTML);
});
test('facets never read the previous market dataset and respect watchlist scope',()=>{
 const c=harness();c.__scrDataset={key:'US|0|moo',rows:[stock('A',2,1,{name:'Alpha'}),stock('B',1,2,{name:'Beta'})],watchlist:['B']};
 assert.equal(c.scrLocalFacets('name').map(v=>v.value).join(','),'Alpha,Beta');
 c.__scr.watchlistOnly=true;assert.equal(c.scrLocalFacets('name').map(v=>v.value).join(','),'Beta');
 c.__scr.market='HK';assert.equal(c.scrLocalFacets('name'),null);
 c.__scrDataset={key:'HK|0|moo',rows:[],watchlist:[]};assert.equal(c.scrLocalFacets('name').length,0);
});
test('late facet responses cannot poison a newer market or generation cache',async()=>{
 const c=harness(),pending=[];let menu;
 c.document.createElement=()=>({style:{},contains:()=>false,querySelectorAll:()=>[],querySelector:()=>null});
 c.document.body.appendChild=el=>menu=el;c.document.getElementById=id=>id==='scr-colmenu'?menu:null;
 c.researchModalIsolate=()=>{};c.scrLocalFacets=()=>null;c.api=url=>new Promise(resolve=>pending.push({url,resolve}));
 c.scrRenderColMenu('name','multi');assert.match(pending[0].url,/market=US/);
 c.scrSet('market','HK');c.scrRenderColMenu('name','multi');assert.match(pending[1].url,/market=HK/);
 pending[0].resolve({values:[{value:'US only',count:1}]});await Promise.resolve();assert.equal(c.__scrFacets.name,undefined);
 pending[1].resolve({values:[{value:'HK only',count:1}]});await Promise.resolve();assert.equal(c.__scrFacets.name[0].value,'HK only');
 c.__scrDataset={key:'HK|0|moo',ts:10,rows:[]};c.scrEnsureFacetScope();assert.equal(c.__scrFacets.name,undefined);
 c.__scrFacets.name=[{value:'old generation',count:1}];c.__scrDataset.ts=11;c.scrEnsureFacetScope();assert.equal(c.__scrFacets.name,undefined);
});
test('large facet lists remain searchable and paged without losing off-page selections or quoted names',()=>{
 const c=harness();c.__scrFacets={name:Array.from({length:12045},(_,i)=>({value:i===12044?"O'Reilly & Sons":'Company '+i,count:1}))};
 c.__colFilterDraft={field:'name',value:{values:['Company 2']}};
 let html=c.scrColFacetHTML('name');assert.equal((html.match(/type="checkbox"/g)||[]).length,100);assert.match(html,/12,045 values/);
 c.__colFilterDraft.facetOffset=12000;html=c.scrColFacetHTML('name');assert.equal((html.match(/type="checkbox"/g)||[]).length,45);
 assert.match(html,/this.value,this.checked/);assert.doesNotMatch(html,/scrToggleValue\('name','O'/);
 c.__colFilterDraft.facetQuery='REILLY';html=c.scrColFacetHTML('name');assert.equal((html.match(/type="checkbox"/g)||[]).length,1);assert.match(html,/1–1 of 1 values/);
 c.scrToggleValue('name',"O'Reilly & Sons",true);assert.equal(c.__colFilterDraft.value.values.join('|'),"Company 2|O'Reilly & Sons");
 c.__colFilterDraft.facetQuery='absent';assert.match(c.scrColFacetHTML('name'),/No matching values/);
 c.scrApplyColFilter('name');assert.equal(c.__scr.colFilters.name.values.join('|'),"Company 2|O'Reilly & Sons");
});
test('column filter isolates background, traps keyboard focus and restores its origin',()=>{
 const c=harness(),background={tagName:'MAIN',inert:false},origin={isConnected:true,getClientRects:()=>[{}],focus(){c.document.activeElement=this;}};
 const controls=['Close column filter','Minimum Price','Maximum Price','Reset','Apply'].map(name=>({getAttribute:key=>key==='aria-label'?name:null,getClientRects:()=>[{}],focus(){c.document.activeElement=this;}}));
 let menu;const body={children:[background],appendChild(el){menu=el;el.parentElement=this;this.children.push(el);}};c.document.body=body;c.document.activeElement=origin;
 c.document.createElement=()=>({style:{},contains:el=>controls.includes(el),querySelectorAll:()=>controls,querySelector:s=>s==='input'?controls[1]:null,remove(){body.children=body.children.filter(e=>e!==this);menu=null;}});
 c.document.getElementById=id=>id==='scr-colmenu'?menu:null;
 c.scrRenderColMenu('price','num');assert.equal(background.inert,true);assert.equal(c.document.activeElement,controls[1]);assert.match(menu.innerHTML,/role="dialog" aria-modal="true" aria-label="Filter Price"/);assert.match(menu.innerHTML,/aria-label="Maximum Price"/);
 let prevented=false;c.document.activeElement=controls[0];menu.onkeydown({key:'Tab',shiftKey:true,preventDefault(){prevented=true;}});assert.equal(prevented,true);assert.equal(c.document.activeElement,controls[4]);
 menu.onkeydown({key:'Tab',shiftKey:false,preventDefault(){}});assert.equal(c.document.activeElement,controls[0]);
 menu.onkeydown({key:'Escape',preventDefault(){}});assert.equal(menu,null);assert.equal(background.inert,false);assert.equal(c.document.activeElement,origin);assert.equal(c.__colFilterDraft,null);
});
test('header sign-in retains the current workflow and explicit add/review intents',async()=>{
 for(const [page,intent,expected] of [['home','header','home'],['info','header','info'],['settings','header','settings'],['shortlists','header','shortlists'],['info','pair','home'],['home','add','picker']]){
  const c=harness();vm.runInContext(`state.page=${JSON.stringify(page)}`,c);
  const status={},button={isConnected:true},dialog={querySelector:()=>status};c.__researchDialog=dialog;
  const form={elements:{email:{value:'reviewer@example.test'},password:{value:'preview-password'}},querySelector:()=>button};
  c.researchAuthFetch=async()=>({access_token:'synthetic'});c.researchSessionSet=()=>{};c.researchDialogClose=()=>{c.__researchDialog=null;};
  const actions=[];c.showPage=async name=>actions.push(name);c.researchShortlistPicker=async code=>actions.push(code==='US.S0001'?'picker':'unexpected');
  if(intent==='pair')c.__researchPendingPairReview=true;if(intent==='add')c.__researchPendingAdd='US.S0001';
  await c.researchSignIn(form);assert.deepEqual(actions,[expected]);assert.equal(form.elements.password.value,'');
 }
});
test('clean boot excludes ETFs and migrates legacy empty-view sorting',()=>{
  const c=harness({etfs:true,sort:'pct'});
  assert.equal(c.__scr.etfs,false); assert.equal(c.__scr.sort,'market_cap');
});
test('Clear, preset exit and a second card click share a complete reset',()=>{
  for(const path of ['scrResetAll','scrExitPreset','scrApplyPreset']){
    const c=harness(); Object.assign(c.__scr,{activePreset:'p',filters:[{field:'price',max:5}],
      colFilters:{pb:{max:1}},etfs:true,watchlistOnly:true,sort:'pct',page:8,src:'yf'});
    c.__scrPresets=[{key:'p',filters:[{field:'price',max:5}]}];
    c[path]('p');
    assert.equal(c.__scr.activePreset,null); assert.equal(c.__scr.etfs,false);
    assert.equal(c.__scr.watchlistOnly,false); assert.equal(c.__scr.sort,'market_cap');
    assert.equal(c.__scr.dir,2); assert.equal(c.__scr.page,1); assert.equal(c.__scr.filters.length,0);
    assert.equal(Object.keys(c.__scr.colFilters).length,0);
  }
});
test('preset sort comes from its definition; server factors are not re-evaluated as snapshot factors',()=>{
 const c=harness(); const filters=[{field:'volume',min:100000,days:30}];
 c.__scrPresets=[{key:'p',filters,sort:'pct',direction:2}]; c.scrApplyPreset('p');
 const payload={filters,rows:[stock('LOW',10,-3,{volume:10}),stock('HIGH',5,8,{volume:10}),
   stock('ETF',100,20,{stock_type:'ETF',volume:999999})]};
 assert.equal(c.scrPresetRows(payload).map(r=>r.symbol).join(','),'HIGH,LOW');
 assert.equal(c.__scr.sort,'pct');
});
test('removing or editing a preset filter stops hidden server membership',()=>{
 const c=harness(); c.__scr.activePreset='p';c.__scr.filters=[{field:'price',max:5},{field:'pb',max:1}];
 c.scrRemoveFilter(0);assert.equal(c.__scr.activePreset,null);assert.equal(c.__scr.filters.length,1);
});
test('saved screener replaces preset and retains its saved sorting',async()=>{
 const c=harness();c.__scr.activePreset='p';c.__savedScreeners=[{id:'s',market:'HK',filters:[],sort:'price',direction:1}];
 await c.scrApplySaved('s'); assert.equal(c.__scr.activePreset,null);assert.equal(c.__scr.market,'HK');
 assert.equal(c.__scr.sort,'price');assert.equal(c.__scr.dir,1);
});
test('pagination clamps Last, supports preset pages and keeps global row offsets',()=>{
 const c=harness();c.__scr.pageSize=100;c.__scr.page=999999;
 const p=c.scrPageRows(Array.from({length:225},(_,i)=>i));
 assert.equal(c.__scr.page,3);assert.equal(p.offset,200);assert.equal(p.shown,25);
 c.scrSet('pageSize',250);assert.equal(c.__scr.page,1);
 c.__scr.page=8;c.scrTickers('nvda, aapl');assert.equal(c.__scr.page,1);
});
test('deep links reset omitted values instead of leaking stored settings',()=>{
 const c=harness({schemaVersion:2,etfs:true,sort:'pct',src:'yf',filters:[{field:'price',max:5}],activePreset:'p',colFilters:{pb:{max:1}}},'#/screener?m=US');
 c.scrRestoreFromHash();assert.equal(c.__scr.sort,'market_cap');assert.equal(c.__scr.etfs,false);
 assert.equal(c.__scr.activePreset,null);assert.equal(c.__scr.filters.length,0);assert.equal(Object.keys(c.__scr.colFilters).length,0);
 c.__scr.etfs=true;c.__scr.colFilters={pb:{max:1}};c.scrPersist();
 assert.match(c.location.hash,/etfs=1/);assert.match(c.location.hash,/cf=/);
});
test('numeric sorts keep missing values last in both directions',()=>{
 const c=harness();c.__scr.sort='market_cap';
 for (const dir of [1,2]) {c.__scr.dir=dir;const rows=c.scrSortRows([stock('NULL',null,0),stock('A',1,0),stock('B',2,0)]);
 assert.equal(rows.at(-1).symbol,'NULL');assert.equal(rows[0].symbol,dir===1?'A':'B');}
});
test('RSI signals switch to enriched data, absent factors do not silently match everything',()=>{
 const c=harness();c.scrSignal('oversold');assert.equal(c.__scr.src,'yf');
 assert.equal(c.scrFieldPass([stock('A',1,1)],c.__scr.filters).length,0);
 const rows=Array.from({length:60},(_,i)=>stock(String(i),1,1,i===59?{rsi14:20}:{}));
 assert.equal(c.scrFieldPass(rows,c.__scr.filters).length,1);
});
test('warming returns its payload to a simultaneous click',async()=>{
 const c=harness();const payload={available:true,rows:[]};c.api=async()=>payload;
 c.scrWarmPreset('p','US');assert.equal(await c.__presetInflight['p|US'],payload);
});
test('stale renders cannot erase a newer page',async()=>{
 const c=harness();let resolve;
 vm.runInContext('pages.home = () => new Promise(r => window.releaseHome = r); pages.info = async () => "new info"',c);
 const old=c.render('home');const newer=c.render('info');await newer;
 c.releaseHome('');await old;
 assert.equal(c.document.querySelector('#page').innerHTML,'new info');
});
test('column filter changes remain a draft until Apply',()=>{
 const c=harness();c.__scr.colFilters={price:{min:1}};
 c.__colFilterDraft={field:'price',value:{min:1}};c.scrColDraftVal('price','min','10');c.scrColMenuClose();
 assert.equal(c.__scr.colFilters.price.min,1);
 c.__colFilterDraft={field:'price',value:{min:10}};c.scrApplyColFilter('price');assert.equal(c.__scr.colFilters.price.min,10);
});
test('saved screens restore columns, provider membership, mode and exclusions together',async()=>{
 const c=harness();c.__savedScreeners=[{id:'investment',market:'US',filters:[{field:'price',max:5}],sort:'pct',direction:2,
 settings:{src:'moo',etfs:false,cols:['symbol','price'],view:'custom',presentation:'explore',preset:'penny',colFilters:{pb:{max:1}}}}];
 await c.scrApplySaved('investment');assert.equal(c.__scr.activePreset,'penny');assert.equal(c.__scr.savedScreenId,'investment');
 assert.equal(c.__scr.cols.join(','),'symbol,price');assert.equal(c.__scr.presentation,'explore');assert.equal(c.__scr.etfs,false);
 c.__scr.page=3;c.scrPersist();assert.match(c.location.hash,/saved=investment/);assert.match(c.location.hash,/p=3/);
 c.scrRestoreFromHash();assert.equal(c.__scr.page,3);assert.equal(c.__scr.savedScreenId,'investment');
});
test('Explore excludes unknown and nonmeaningful ratios instead of plotting them as zero',()=>{
 const c=harness();assert.equal(c.researchPlottable({pe_ttm:null,pct:2},'pe_ttm','pct'),false);
 assert.equal(c.researchPlottable({pe_ttm:-2,pct:2},'pe_ttm','pct'),false);
 assert.equal(c.researchPlottable({pe_ttm:8,pct:0},'pe_ttm','pct'),true);
});
test('drawings survive chart teardown and restore under their instrument scope',()=>{
 const c=harness();let disposed;
 c.klinecharts={dispose:id=>disposed=id};c.removeEventListener=()=>{};
 // v10 engine surface: overlays are read through getOverlays(filter)
 const h={elId:'chart-a',state:()=>({sym:'AAPL',range:'Y'}),drawingScope:'scope-a',drawingIds:['trend'],
 chart:{getOverlays:f=>f&&f.id==='trend'?[Object.assign({id:'trend'},{name:'segment',points:[{timestamp:1,value:100},{timestamp:2,value:110}]})]:[],
        removeOverlay:()=>{}}};
 c.klineTeardown(h);assert.equal(disposed,'chart-a');assert.equal(c.__chartDrawings['scope-a'][0].points[1].value,110);
 assert.equal(h.chart,null);assert.equal(h.drawingIds.length,0);
});

test('screener ticker links enter full research with return context',()=>{
 const c=harness();c.scrClientRows=()=>[stock('BRK.B',1e11,2,{code:'US.BRK.B'})];
 Object.assign(c.__scr,{sort:'price',page:3,filters:[{field:'price',min:1}]});
 let opened;c.openStock=s=>opened=s;c.researchOpen('US.BRK.B');
 assert.equal(opened,'US.BRK.B');assert.equal(c.__researchContext.state.page,3);
 assert.equal(c.__researchContext.rows[0].code,'US.BRK.B');
 c.__scr.page=1;assert.equal(c.__researchContext.state.page,3);
 assert.match(html,/event.preventDefault\(\);researchOpen\('\$\{esc\(r.code \|\| r.symbol\)\}'\)/);
});
test('capital-flow totals use gross distribution, not a sum of cumulative net observations',()=>{
 const c=harness();
 const data={flow:[{capital_flow_item_time:1,in_flow:10},{capital_flow_item_time:2,in_flow:20}],distribution:{capital_in_super:100,capital_in_big:200,capital_in_mid:300,capital_in_small:400,capital_out_super:20,capital_out_big:30,capital_out_mid:40,capital_out_small:50}};
 const intraday=c.stkCapitalTotals(data,'intraday');assert.equal(intraday.inflow,1000);assert.equal(intraday.outflow,140);assert.equal(intraday.net,860);
 const daily=c.stkCapitalTotals(data,'day');assert.equal(daily.net,20);assert.equal(daily.inflow,null);assert.equal(daily.outflow,null);
 assert.equal(c.stkCapitalTotals({},'intraday').net,null);
});
test('inspector values retain percent units, short cap units and unavailable numeric evidence',()=>{
 const c=harness();
 assert.equal(c.researchValue('revenue_growth',43.956),'43.96%');
 assert.equal(c.researchValue('market_cap',5.564e12,'USD'),'USD 5.56T');
 assert.equal(c.researchValue('pe_ttm',null),'Unavailable');
 const e=c.researchEvidence({revenue_growth:99,criterion_values:{}},{field:'revenue_growth',min:5,excl_min:1},'penny');
 assert.equal(e.value,'Numeric evidence unavailable');assert.equal(e.threshold,'> 5%');assert.equal(e.basis,'Annual financial basis requested');assert.equal(e.period,'Reported period not supplied');
 const v=c.researchEvidence({criterion_values:{volume:100001}},{field:'volume',min:100000,days:30},'penny');
 assert.equal(v.value,'100,001 shares');assert.equal(v.basis,'30-day average requested');assert.equal(v.period,'Reported period not supplied');
 assert.equal(c.researchValue('price',0.000001),'0.000001');assert.equal(c.researchValue('price',123.4),'123.40');
});
test('desk library groups retain every original preset and leave future definitions reachable',()=>{
 const c=harness(),presets=JSON.parse(fs.readFileSync(require('node:path').join(__dirname,'presets-baseline.json'),'utf8'));
 const before=JSON.stringify(presets),grouped=c.researchLibraryGroups(presets),keys=grouped.flatMap(g=>g.presets.map(p=>p.key));
 assert.equal(keys.length,22);assert.equal(new Set(keys).size,22);assert.equal(JSON.stringify(presets),before);
 assert.deepEqual([...keys].sort(),presets.map(p=>p.key).sort());
 const extra=c.researchLibraryGroups([...presets,{key:'future',name:'Future screen'}]);assert.equal(extra.at(-1).presets[0].key,'future');
});
test('new Overview is readable while existing saved column arrays remain intact',()=>{
 const c=harness();assert.equal(c.__scr.cols.join(','),'symbol,name,price,pct,market_cap,pe_ttm,volume');
 const old=harness({schemaVersion:2,cols:['symbol','name','price','chg','pb'],view:'overview'});
 assert.equal(old.__scr.cols.join(','),'symbol,name,price,chg,pb');
 old.scrResetAll();assert.equal(old.__scr.cols.join(','),'symbol,name,price,pct,market_cap,pe_ttm,volume');assert.equal(old.__researchResetScroll,true);
});
test('mobile detail fields retain text, vendor lists and boolean meanings',()=>{
 const c=harness();assert.equal(c.researchDisplayField('name','Company A'),'Company A');assert.equal(c.researchDisplayField('plate',['Banks','OTC']),'Banks, OTC');
 assert.equal(c.researchDisplayField('new_high',false),'No');assert.equal(c.researchDisplayField('new_high','0'),'No');assert.equal(c.researchDisplayField('new_low',1),'Yes');assert.equal(c.researchDisplayField('new_low',null),'Unavailable');
});
test('changing to a modal breakpoint retains the original stock-row focus target',()=>{
 const c=harness(),origin={stockRow:true};let focused=0;
 c.__inspectOrigin=origin;c.document.activeElement={exportSummary:true};
 c.document.getElementById=id=>id==='research-inspector'?{classList:{contains:()=>true},setAttribute(){},contains:()=>false,querySelector:()=>({focus(){focused++;}})}:null;
 c.matchMedia=q=>({matches:q.includes('max-width')});c.researchModalIsolate=()=>{};
 c.researchResponsivePanels();assert.equal(c.__inspectOrigin,origin);assert.equal(focused,1);
});
test('direct sort control applies field and direction together and resets pagination',()=>{
 const c=harness();c.__scr.page=4;let renders=0;c.showPage=()=>renders++;
 c.researchSortSet('price','1');assert.equal(c.__scr.sort,'price');assert.equal(c.__scr.dir,1);assert.equal(c.__scr.page,1);assert.equal(renders,1);
 c.researchSortSet('missing','2');c.researchSortSet('market_cap','0');assert.equal(renders,1);assert.equal(c.__scr.sort,'price');
});
test('saved screens mount without the removed legacy dropdown',async()=>{
 const c=harness();const rows=[{id:'saved',name:'Saved screen'}];c.api=async()=>({screeners:rows});let mounted=0;c.researchSavedMount=()=>mounted++;
 await c.scrLoadMyPresets();assert.equal(mounted,1);assert.equal(c.__savedScreeners[0].id,'saved');
});
test('intent warming is bounded and does not request every queued screen concurrently',async()=>{
 const c=harness();let resolve,requests=0;c.api=()=>{requests++;return new Promise(r=>resolve=r);};
 c.scrWarmPreset('penny','US');c.scrWarmPreset('blue-chip','US');c.scrWarmPreset('penny','US');
 assert.equal(requests,1);assert.equal(c.__presetWarmQueue.length,1);
 resolve({available:true,rows:[]});await c.__presetInflight['penny|US'];
 assert.equal(requests,1);assert.equal(c.__presetCache['penny|US'].payload.available,true);
});
test('selected exports preserve cohort sort and canonical share-class identity',()=>{
 const c=harness(); const rows=[stock('BRK.A',10,1,{code:'US.BRK.A'}),stock('BRK.B',9,1,{code:'US.BRK.B'}),stock('X',1,0,{code:'US.X'})];
 assert.equal(c.researchSelectedRows(rows,['US.BRK.B','US.BRK.A']).map(r=>r.code).join(','),'US.BRK.A,US.BRK.B');
 assert.equal(c.researchSelectedRows(rows,['BRK.B']).length,0);
});
test('inspector history sorts and deduplicates valid bars while rejecting missing OHLC and broken ranges',()=>{
 const c=harness(),now=Date.now();
 const bar=(t,extra={})=>({timestamp:t,open:10,high:12,low:9,close:11,volume:10,...extra});
 const bars=c.researchInspectorBars({bars:[bar(now),bar(now-86400000),bar(now,{close:12}),bar(now-200*86400000),bar(now-2*86400000,{open:null}),bar(now-3*86400000,{high:8})]},31);
 assert.equal(bars.length,2);assert.equal(bars[0].timestamp,now-86400000);assert.equal(bars[1].close,12);
 const sec=c.researchInspectorBars({bars:[bar(Math.floor(now/1000))]},31);assert.equal(sec.length,1);assert.ok(sec[0].timestamp>1e12);
 assert.equal(c.researchInspectorBars({bars:[bar(now+86400000),bar(now,{low:-1}),bar(now,{volume:'invalid'})]},31).length,0);
 assert.equal(c.researchInspectorBars({bars:[bar(now,{volume:null})]},31)[0].volume,undefined);
});
test('selected CSV and Excel export exactly the sorted selection and reject a partial cohort',async()=>{
 const c=harness(),rows=[stock('BRK.A',10,1,{code:'US.BRK.A'}),stock('BRK.B',9,1,{code:'US.BRK.B'}),stock('X',1,0,{code:'US.X'})];
 c.scrClientRows=()=>rows;c.__researchSelected=['US.BRK.B','US.BRK.A'];c.__scr.cols=['symbol','market_cap'];
 let blob,filename,clicked=0,alert;
 c.Blob=Blob;c.URL={createObjectURL:b=>{blob=b;return 'blob:test';},revokeObjectURL(){}};
 c.document.createElement=()=>({click(){clicked++;filename=this.download;},remove(){}});c.alert=m=>alert=m;
 c.scrExport('csv','selected');const csv=Buffer.from(await blob.arrayBuffer());
 assert.equal(csv.subarray(0,3).toString('hex'),'efbbbf');
 assert.equal(csv.toString('utf8').replace(/^\ufeff/,'').split('\n').slice(1).join('\n'),'1,BRK.A,10,US.BRK.A,Unavailable\n2,BRK.B,9,US.BRK.B,Unavailable');assert.match(filename,/_selected\.csv$/);
 c.scrExport('xls','selected');const xml=await blob.text();assert.match(xml,/BRK.A[\s\S]*BRK.B/);assert.equal((xml.match(/<Row>/g)||[]).length,3);assert.match(filename,/_selected\.xls$/);
 c.__researchSelected.push('US.MISSING');c.scrExport('csv','selected');assert.equal(clicked,2);assert.match(alert,/outside the current loaded cohort/);
});
test('disposing an inspector invalidates requests and disconnects its chart observer',()=>{
 const c=harness();let disconnected=0,disposed;
 c.__inspectGen=7;c.__inspectResize={disconnect(){disconnected++;}};c.__inspectChart={};c.klinecharts={dispose:id=>disposed=id};
 c.researchDisposeInspector();assert.equal(c.__inspectGen,8);assert.equal(disconnected,1);assert.equal(disposed,'inspect-chart');assert.equal(c.__inspectChart,null);
});
test('a late inspector response cannot replace the newer stock status',async()=>{
 const c=harness(),status={textContent:''},chart={innerHTML:''},pending=[];
 const inspector={classList:{add(){}},setAttribute(){},removeAttribute(){},querySelector:()=>null};
 c.document.getElementById=id=>({'research-inspector':inspector,'inspect-chart':chart,'inspect-chart-status':status})[id];
 c.api=url=>url.startsWith('/api/screener/company-context')?Promise.resolve({fields:{},origins:{}}):new Promise(resolve=>pending.push(resolve));
 const old=c.researchInspectRow(stock('A',10,1,{code:'US.A'}));
 const newer=c.researchInspectRow(stock('B',9,2,{code:'US.B'}));
 pending[1]({available:false,reason:'B unavailable'});await newer;
 pending[0]({available:false,reason:'A unavailable'});await old;
 assert.equal(c.__researchInspectCode,'US.B');assert.equal(status.textContent,'B unavailable');
});
test('saved Modified relationship ignores object key order and pagination, but tracks recorded query and layout',async()=>{
 const c=harness();const saved={id:'a',name:'My screen',market:'US',sort:'price',direction:1,filters:[{field:'price',min:1,max:10}],settings:{colFilters:{pb:{min:0,max:1}},cols:['symbol','price'],view:'custom'}};
 c.__savedScreeners=[saved];await c.scrApplySaved('a');assert.equal(c.researchSavedModified(saved,c.__scr),false);
 c.__scr.colFilters={pb:{max:1,min:0}};c.__scr.page=3;assert.equal(c.researchSavedModified(saved,c.__scr),false);
 c.__scr.dir=2;assert.equal(c.researchSavedModified(saved,c.__scr),true);assert.equal(saved.direction,1);
 c.__scr.dir=1;c.__scr.cols.push('name');assert.equal(c.researchSavedModified(saved,c.__scr),true);assert.deepEqual(saved.settings.cols,['symbol','price']);
});
test('retained column label distinguishes legacy layout without mutating it',()=>{
 const c=harness({cols:['symbol','name','price','pb'],view:'overview'});const before=JSON.stringify(c.__scr.cols);
 assert.equal(c.researchViewLabel('overview',c.__scr),'Overview · retained columns');assert.equal(JSON.stringify(c.__scr.cols),before);
 c.scrSetView('overview');assert.equal(c.researchViewLabel('overview',c.__scr),'Overview');
});
test('Explorer region bounds preserve sort, zero changes and canonical stock identities',()=>{
 const c=harness();const rows=[stock('A',100,0,{code:'US.A',pe_ttm:10}),stock('B',200,-2,{code:'US.B',pe_ttm:20}),stock('C',50,4,{pe_ttm:null}),stock('D',70,1,{pe_ttm:''})];
 const st={x:'pe_ttm',y:'pct',bounds:{x:{min:10,max:20},y:{min:-2,max:0}}};
 assert.deepEqual(Array.from(c.researchExploreSelected(rows,st),r=>r.code),['US.A','US.B']);assert.equal(c.researchPlottable(rows[3],'pe_ttm','pct'),false);
 assert.throws(()=>c.researchExploreParseBounds({x:{min:'3',max:'2'},y:{min:'',max:''}}),/minimum/);
 assert.throws(()=>c.researchExploreParseBounds({x:{min:'Infinity'},y:{}}),/finite/);
 assert.equal(c.researchExploreParseBounds({x:{min:'',max:'0'},y:{min:'-2',max:null}}).x.max,0);
});
test('Explorer discloses missing values, log exclusions and outliers independently',()=>{
 const c=harness();const rows=Array.from({length:101},(_,i)=>({pe_ttm:i+1,pct:i-50}));rows.push({pe_ttm:null,pct:1});
 const model=c.researchExploreModel(rows,{x:'pe_ttm',y:'pct',xs:'linear',ys:'log',trim:true,bounds:null,zoom:false});
 assert.equal(model.missing,1);assert.equal(model.scaleExcluded,51);assert.equal(model.plotted.length+model.outside+model.scaleExcluded+model.missing,rows.length);
 const d=c.researchExploreDomain([10,10],'log',false);assert.ok(d.min>0 && d.max>d.min);
});
test('Explorer region resets when cohort criteria change and never mutates saved screen filters',()=>{
 const c=harness();const before=JSON.stringify(c.__scr);const st=c.researchExploreState();st.bounds={x:{min:1,max:2},y:{min:null,max:null}};
 assert.equal(JSON.stringify(c.__scr),before);c.__scr.sort='pct';assert.equal(c.researchExploreState(),st);
 c.__scr.market='HK';assert.equal(c.researchExploreState().bounds,null);
});
test('region CSV exports only inclusive region members with both axes and exact numeric values',async()=>{
 const c=harness(),rows=[stock('A',100,0,{pe_ttm:10}),stock('B',200,2,{pe_ttm:20}),stock('C',300,-1,{pe_ttm:30})];
 c.scrClientRows=()=>rows;c.__scr.cols=['symbol'];c.researchExploreState().bounds={x:{min:10,max:20},y:{min:0,max:2}};
 let blob,filename,clicked=0;c.Blob=Blob;c.URL={createObjectURL:b=>{blob=b;return 'blob:test';},revokeObjectURL(){}};c.document.createElement=()=>({click(){clicked++;filename=this.download;},remove(){}});c.alert=()=>{};
 c.scrExport('csv','explore');assert.equal((await blob.text()).replace(/^\ufeff/,'').split('\n').slice(1).join('\n'),'1,A,,10,0\n2,B,,20,2');assert.match(filename,/_region\.csv$/);assert.equal(c.__scr.cols.join(','),'symbol');
 c.researchExploreState().bounds.x.min=99;c.scrExport('csv','explore');assert.equal(clicked,1);
});
test('Clear discards the Explorer region and zoom as well as defaulting the query',()=>{
 const c=harness();const st=c.researchExploreState();st.bounds={x:{min:10,max:20},y:{min:0,max:1}};st.zoom=true;st.x='market_cap';st.ys='log';
 c.scrResetAll();const next=c.researchExploreState();assert.equal(next.bounds,null);assert.equal(next.zoom,false);assert.equal(next.x,'pe_ttm');assert.equal(next.ys,'linear');assert.equal(c.__scr.presentation,'table');
});
test('comparison CSV carries immutable pair IDs, times, definition and unavailable paired evidence',()=>{
 const c=harness(),d={definition:{market:'US',filters:[{field:'price',max:5}]},previous_id:'a',current_id:'b',previous_at:'2026-10-01',current_at:'2026-10-02',previous_source_at:'one',current_source_at:'two'};
 const csv=c.researchChangesCSV(d,[{code:'US.BRK.B',symbol:'BRK.B',name:'Berkshire, Inc.',status:'exited',reason:'numeric cause unavailable',previous:{metrics:{price:4}},current:null,evidence:[{field:'price',previous:4,current:null,status:'unavailable_pair'}]}]);
 assert.match(csv,/^\ufeffdefinition_json,previous_id,current_id/);assert.match(csv,/,a,b,2026-10-01,2026-10-02,one,two,US.BRK.B,BRK.B,"Berkshire, Inc."/);assert.match(csv,/unavailable_pair/);assert.match(csv,/filters/);
});
test('comparison CSV preserves eligible coverage and both typed observations',()=>{
 const c=harness(),criterion={field:'price',max:10},before={criterion,value:12,unit:'currency',currency:'USD',clock:'quote_source',source:'synthetic_fixture',period:'point_in_time',observed_at:'2026-10-01T00:00:00Z'},after={...before,value:8,observed_at:'2026-10-02T00:00:00Z'};
 const d={definition:{filters:[criterion]},previous_id:'before',current_id:'after',observation_coverage:{scope:'eligible_stored_universe',previous:1176,current:1176}};
 const csv=c.researchChangesCSV(d,[{code:'US.A',evidence:[{criterion_key:'c0',criterion,previous:12,current:8,previous_observation:before,current_observation:after,status:'comparable',assessment:'rule_entered'}]}]);
 assert.match(csv,/observation_scope,previous_eligible_observations,current_eligible_observations/);
 assert.match(csv,/eligible_stored_universe,1176,1176/);assert.match(csv,/previous_observation/);assert.match(csv,/rule_entered/);assert.match(csv,/quote_source/);
});
test('a late change-review response cannot replace a newer cohort',async()=>{
 const c=harness();const el={innerHTML:''};c.document.getElementById=id=>id==='research-change-results'?el:null;const pending=[];c.api=()=>new Promise(resolve=>pending.push(resolve));c.researchChangesRender=(_el,d)=>_el.innerHTML=d.tag;
 const old=c.researchLoadChanges();c.researchChangeState().status='exited';const latest=c.researchLoadChanges();pending[1]({tag:'exited'});await latest;pending[0]({tag:'new'});await old;assert.equal(el.innerHTML,'exited');
});
test('comparison errors show user-readable validation details instead of JSON',()=>{
 const c=harness();assert.equal(c.researchErrorMessage({message:'{"detail":"Choose distinct snapshots"}'}),'Choose distinct snapshots');assert.equal(c.researchErrorMessage({message:'{"detail":[{"field":"id"}]}'}),'Please check the requested inputs.');assert.equal(c.researchErrorMessage({message:'Network unavailable'}),'Network unavailable');
});
test('comparison export waits for pending review changes instead of exporting an old pair',async()=>{
 const c=harness();let message,called=0;c.__changeLoading=true;c.alert=m=>message=m;c.api=async()=>{called++;};await c.researchChangesExport();assert.equal(called,0);assert.match(message,/finish loading/);
});

test('comparison export retrieves every page for one immutable filtered pair',async()=>{
 const c=harness();c.__changePayload={comparable:true,previous_id:'before',current_id:'after',definition:{market:'US'}};const st=c.researchChangeState();st.status='all';st.q='Test';st.sort='market_cap';st.direction=2;
 const rows=Array.from({length:501},(_,i)=>({code:'US.T'+i,symbol:'T'+i,name:'Test',status:'unchanged'}));let blob,clicks=0;const calls=[];
 c.Blob=Blob;c.URL={createObjectURL:b=>{blob=b;return 'blob:test';},revokeObjectURL(){}};c.document.createElement=()=>({click(){clicks++;},remove(){}});c.alert=m=>assert.fail(m);
 c.api=async url=>{const qs=new URLSearchParams(url.split('?')[1]);calls.push(qs);return {comparable:true,previous_id:'before',current_id:'after',matched:501,rows:rows.slice(Number(qs.get('offset')),Number(qs.get('offset'))+500)};};
 await c.researchChangesExport();assert.equal(clicks,1);assert.equal(calls.length,2);assert.equal(calls[1].get('offset'),'500');for(const q of calls){assert.equal(q.get('previous_id'),'before');assert.equal(q.get('current_id'),'after');assert.equal(q.get('status'),'all');assert.equal(q.get('q'),'Test');assert.equal(q.get('direction'),'2');}
 assert.equal((await blob.text()).split('\n').length,502);
});
test('comparison export rejects missing, changed and duplicate memberships without a partial file',async()=>{
 for(const fault of ['missing','pair','count','duplicate']){
 const c=harness();c.__changePayload={comparable:true,previous_id:'a',current_id:'b',definition:{market:'US'}};let calls=0,clicks=0,message;const first=Array.from({length:500},(_,i)=>({code:'US.T'+i}));
 c.Blob=Blob;c.URL={createObjectURL:()=>{throw Error('Partial file created');}};c.document.createElement=()=>({click(){clicks++;},remove(){}});c.alert=m=>message=m;
 c.api=async()=>{calls++;return {comparable:true,previous_id: fault==='pair' && calls===2?'different':'a',current_id:'b',matched:fault==='count' && calls===2?502:501,rows:calls===1?first:fault==='missing'?[]:[{code:fault==='duplicate'?'US.T0':'US.T500'}]};};
 await c.researchChangesExport();assert.equal(clicks,0);assert.match(message,/unavailable/);
 }
});
const privateSession=(id='00000000-0000-4000-8000-000000000001')=>({access_token:'access',refresh_token:'refresh',expires_at:Date.now()/1000+3600,user:{id,email:'fixture@example.test'}});
test('sign-out clears every private cache and leaves original screener criteria intact',()=>{
 const c=harness();const before=JSON.stringify(c.__scr);c.__researchSession=privateSession();c.__researchCurrentList={name:'Private'};c.__researchLists=[{name:'Private'}];c.__researchListItems=[{note:'Private thesis'}];c.__researchReviewDraft={note:'draft'};c.__researchUndo={code:'US.A'};
 c.researchPrivateClear();assert.equal(c.__researchSession,null);assert.equal(c.__researchCurrentList,null);assert.equal(c.__researchListItems.length,0);assert.equal(c.__researchLists.length,0);assert.equal(c.__researchReviewDraft,null);assert.equal(c.__researchUndo,null);assert.equal(JSON.stringify(c.__scr),before);
});
test('late private responses are rejected after account switch',async()=>{
 const c=harness();c.researchSessionSet(privateSession());let resolve;c.fetch=()=>new Promise(r=>resolve=r);const pending=c.researchPrivateAPI('/api/research/lists');
 c.researchSessionSet(privateSession('00000000-0000-4000-8000-000000000002'));resolve({ok:true,json:async()=>({lists:[{name:'Old owner secret'}]})});await assert.rejects(pending,e=>e.status===499);assert.equal(c.__researchLists.length,0);
});
test('session refresh is single-flight and cannot replace a changed account',async()=>{
 const c=harness();c.researchSessionSet(privateSession());let resolve,requests=0;c.fetch=()=>{requests++;return new Promise(r=>resolve=r);};const one=c.researchRefreshSession(),two=c.researchRefreshSession();
 c.researchSessionSet(privateSession('00000000-0000-4000-8000-000000000002'));resolve({ok:true,json:async()=>privateSession()});await assert.rejects(one,e=>e.status===499);await assert.rejects(two,e=>e.status===499);assert.equal(requests,1);assert.equal(c.__researchSession.user.id,'00000000-0000-4000-8000-000000000002');
});
test('a revoked refresh clears private data while a network failure preserves retryable session',async()=>{
 for(const status of [401,503]){const c=harness();c.researchSessionSet(privateSession());c.__researchListItems=[{note:'Private'}];c.fetch=async()=>({ok:false,status,text:async()=>'{"detail":"Unavailable"}'});
 await assert.rejects(c.researchRefreshSession());assert.equal(!!c.__researchSession,status===503);assert.equal(c.__researchListItems.length,status===503?1:0);}
});
test('shortlist CSV preserves share classes, missing quotes and numeric negatives while guarding spreadsheet formulas',()=>{
 const c=harness();const csv=c.researchListCSV({name:'Quality',revision:3},[{code:'US.BRK.B',note:'=HYPERLINK("bad")',review_status:'reviewed',quote:{code:'US.BRK.B',symbol:'BRK.B',name:'Berkshire, Inc.',price:-1,currency:'USD'}}]);
 assert.match(csv,/US.BRK.B,BRK.B,"Berkshire, Inc.",-1,USD/);assert.match(csv,/'=HYPERLINK/);assert.match(csv,/list_revision/);
 const missing=c.researchListQuote({code:'US.A',quote:{code:'US.B',price:5}});assert.equal(missing.price,undefined);assert.equal(missing.code,'US.A');
});
test('shortlist export rejects changed list revision before creating a partial file',async()=>{
 const c=harness();c.researchSessionSet(privateSession());c.__researchListID='list';let calls=0,message;c.researchPrivateAPI=async()=>({list:{name:'Quality',revision:++calls},items:[{code:'US.A'}],has_more:false});c.document.getElementById=()=>({set textContent(v){message=v;}});c.Blob=()=>assert.fail('partial export');await c.researchListExport();assert.match(message,/changed/);
});

test('Next unreviewed continues and wraps the filtered ticker cohort without modifying the current page',async()=>{
 const c=harness();c.__researchListID='list';c.__researchCurrentList={active:true};c.__researchListGen=7;c.__researchListSearch='BRK';c.__researchListStatus='reviewed';c.__researchReviewCursor='US.BRK.C';c.__researchListItems=[{code:'US.CURRENT'}];
 const calls=[];let opened;c.researchReviewOpen=(code,item)=>opened={code,item};c.researchPrivateAPI=async url=>{calls.push(new URLSearchParams(url.split('?')[1]));return {items:calls.length===1?[]:[{code:'US.BRK.B',review_status:'unreviewed'}]};};
 await c.researchNextUnreviewed();assert.equal(calls.length,2);assert.equal(calls[0].get('after_code'),'US.BRK.C');assert.equal(calls[1].get('after_code'),null);for(const q of calls){assert.equal(q.get('q'),'BRK');assert.equal(q.get('review_status'),'unreviewed');assert.equal(q.get('offset'),'0');assert.equal(q.get('limit'),'1');}assert.equal(opened.code,'US.BRK.B');assert.equal(c.__researchListItems[0].code,'US.CURRENT');
});
test('Next unreviewed does not open an old list after navigation',async()=>{
 const c=harness();c.__researchListID='list';c.__researchCurrentList={active:true};c.__researchListGen=1;let resolve;c.researchPrivateAPI=()=>new Promise(r=>resolve=r);c.researchReviewOpen=()=>assert.fail('old list opened');const pending=c.researchNextUnreviewed();c.__researchListID='new';c.__researchListGen=2;resolve({items:[{code:'US.A'}]});await pending;
});
test('shortlist export retrieves all 501 members and rechecks revision before download',async()=>{
 const c=harness();c.researchSessionSet(privateSession());c.__researchListID='list';c.__researchListSearch='BRK';c.__researchListStatus='reviewed';const items=Array.from({length:501},(_,i)=>({code:'US.T'+i,note:'',review_status:'unreviewed'}));let blob,clicks=0;const calls=[];
 c.researchPrivateAPI=async url=>{const q=new URLSearchParams(url.split('?')[1]);calls.push(q);return {list:{name:'Quality',revision:4},items:items.slice(Number(q.get('offset') || 0),Number(q.get('offset') || 0)+Number(q.get('limit'))),has_more:q.get('limit')!=='1' && Number(q.get('offset'))===0};};
 c.Blob=Blob;c.URL={createObjectURL:b=>{blob=b;return 'blob:test';},revokeObjectURL(){}};c.document.createElement=()=>({click(){clicks++;},remove(){}});await c.researchListExport();assert.equal(clicks,1);assert.equal(calls.length,3);assert.equal(calls[1].get('offset'),'500');assert.equal(calls[2].get('limit'),'1');assert.equal((await blob.text()).split('\n').length,502);for(const q of calls){assert.equal(q.get('q'),null);assert.equal(q.get('review_status'),null);}
});
test('closing a review keeps a tab-only draft, successful close and sign-out do not recreate it',()=>{
 const c=harness(),form={elements:{note:{value:'Unsaved thesis'},review_status:{value:'in_review'}}};const dialog={querySelector:s=>s==='form[data-review]'?form:null,close(){},remove(){}};
 c.__researchReviewDraft={list:'list',code:'US.BRK.B',revision:2};c.__researchDialog=dialog;c.researchDialogClose();assert.equal(c.__researchNoteDrafts['list|US.BRK.B'].note,'Unsaved thesis');
 c.__researchDialog=dialog;c.researchPrivateClear();assert.equal(Object.keys(c.__researchNoteDrafts).length,0);assert.equal(c.__researchDialog,null);
 c.__researchReviewDraft={list:'list',code:'US.BRK.B',revision:2};c.__researchDialog=dialog;c.researchDialogClose(false);assert.equal(Object.keys(c.__researchNoteDrafts).length,0);
});

 test('debounced shortlist search cannot navigate back after leaving the view or switching lists',async()=>{
 for(const change of ['page','list','generation']){
 const c=harness();let run,calls=0;c.setTimeout=fn=>{run=fn;return 1;};c.__researchListID='old';c.__researchListGen=3;vm.runInContext("state.page='shortlists'",c);c.showPage=()=>{calls++;};
 c.researchListSearch({value:'BRK',selectionStart:3});
 if(change==='page')vm.runInContext("state.page='home'",c);if(change==='list')c.__researchListID='new';if(change==='generation')c.__researchListGen=4;
 await run();assert.equal(calls,0);
 }
 });

test('historical criteria matrix retains exclusive bounds, periods, zero and missing evidence',()=>{
 const c=harness();const html=c.researchCriterionMatrix([{field:'pe_ttm',max:12,excl_max:1},{field:'pct',min:0,excl_min:1}],[{field:'pe_ttm',previous:8,current:null,period:'TTM',source:'provider criterion',status:'unavailable_pair'},{field:'pct',previous:0,current:-1,period:'day',source:'stored',status:'paired'}]);
 assert.match(html,/&lt; 12/);assert.match(html,/&gt; 0%/);assert.match(html,/TTM/);assert.match(html,/Paired values unavailable/);assert.match(html,/0%/);assert.match(html,/-1%/);assert.match(html,/Both values supplied/);assert.doesNotMatch(html,/crossed|passed/);
});
test('Changes uses contextual capture controls while preserving current-screen exports in Table',()=>{
 const c=harness();const st=c.__scr;st.presentation='changes';const args={st,scr:{matched:1,rows:[],shown:0},table:'',allChips:'',msPanel:''};const changes=c.researchDeskHTML(args);assert.match(changes,/Changes in All stocks/);assert.match(changes,/Capture snapshot/);assert.match(changes,/scrResetAll/);assert.doesNotMatch(changes,/aria-label="Column view"|aria-label="Sort results"|onclick="scrExport/);st.presentation='table';const table=c.researchDeskHTML(args);assert.match(table,/aria-label="Column view"/);assert.match(table,/scrExport\('csv','all'\)/);assert.match(table,/scrResetAll/);
});

test('historical columns and sort options use capture evidence rather than current quote metrics',()=>{
 const c=harness(),el={innerHTML:'',querySelector:()=>null};c.document.activeElement=null;const d={comparable:true,previous_id:'a',current_id:'b',previous_at:'2026-10-01T00:00:00Z',current_at:'2026-10-02T00:00:00Z',counts:{new:0,exited:0,all:1,unchanged:1},matched:1,definition:{filters:[{field:'pe_ttm',max:12}]},rows:[{code:'US.A',symbol:'A',status:'unchanged',previous:{evidence:{pe_ttm:0},metrics:{pe_ttm:999}},current:{evidence:{pe_ttm:8},metrics:{pe_ttm:999}}}]};c.researchChangesRender(el,d);assert.match(el.innerHTML,/criterion:before:pe_ttm/);assert.match(el.innerHTML,/criterion:after:pe_ttm/);assert.match(el.innerHTML,/<td>0<\/td><td>8<\/td>/);assert.doesNotMatch(el.innerHTML,/>999</);
});

test('capture retry preserves its request identity and disables the capture control',async()=>{
 const c=harness(),el={innerHTML:'',textContent:''},button={disabled:false,isConnected:true};let generated=0;const calls=[],generations=[];c.__scrDataset={key:'US|0|moo',generationId:'11111111-1111-4111-8111-111111111111'};
 c.crypto={randomUUID:()=>`request-${++generated}`};c.document.getElementById=id=>id==='research-change-results'?el:null;c.document.querySelector=selector=>{assert.equal(selector,'[data-capture]');return button;};c.researchLoadChanges=async()=>{};
 c.api=async(url,options)=>{assert.equal(button.disabled,true);calls.push(options.headers['Idempotency-Key']);generations.push(options.headers['X-Screener-Generation']);if(calls.length===1)throw new Error('response unavailable');return {captured:true};};
 await c.researchSnapshot();assert.match(el.innerHTML,/Retry capture/);assert.equal(button.disabled,false);assert.equal(c.__captureRequest.id,'request-1');
 c.__scrDataset.generationId='22222222-2222-4222-8222-222222222222';await c.researchSnapshot();assert.equal(c.__captureRequest,null);await c.researchSnapshot();assert.deepEqual(calls,['request-1','request-1','request-2']);assert.deepEqual(generations,['11111111-1111-4111-8111-111111111111','11111111-1111-4111-8111-111111111111','22222222-2222-4222-8222-222222222222']);assert.equal(c.__snapshotBusy,false);
});
test('paging retained history preserves the selected comparison and row page',()=>{
 const c=harness(),st=c.researchChangeState();Object.assign(st,{previous_id:'old-before',current_id:'old-after',offset:200});let loaded=0;c.researchLoadChanges=()=>{loaded++;};c.researchChangeSet('history_offset',100);
 assert.equal(loaded,1);assert.equal(st.history_offset,100);assert.equal(st.offset,200);assert.equal(st.previous_id,'old-before');assert.equal(st.current_id,'old-after');
});

test('an uncertain capture request survives reload without persisting market rows or notes',()=>{
 const c=harness(),store=new Map();c.sessionStorage={getItem:k=>store.get(k) || null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)};c.crypto={randomUUID:()=> '00000000-0000-4000-8000-000000000001'};
 const first=c.researchCaptureRequest({market:'US',filters:[]});c.__captureRequest=null;c.crypto.randomUUID=()=>assert.fail('Reload generated a different request');const restored=c.researchCaptureRequest({filters:[],market:'US'});assert.equal(restored.id,first.id);assert.deepEqual(Object.keys(JSON.parse(store.get('researchCaptureRequestV1'))).sort(),['generation_id','id','key']);c.researchCaptureConfirmed(restored);assert.equal(store.size,0);
});
test('definition disclosure does not fabricate missing before-and-after observations',()=>{
 const c=harness();const html=c.researchCriteriaDefinition([{field:'volume',min:100000,days:30}]);assert.match(html,/Screen definition/);assert.match(html,/30d/);assert.doesNotMatch(html,/Before|After|Unavailable|Paired/);assert.equal(c.researchCaptureClockLabel('stored_universe'),'Stored cache update');assert.equal(c.researchCaptureClockLabel('provider_retrieval'),'Provider retrieval');assert.equal(c.researchCaptureClockLabel(undefined),'Time type unverified');
});

test('history paging keeps its disclosure open and moves focus to the usable page control',()=>{
 const c=harness(),disclosure={open:true};let focused=false;const el={innerHTML:'',querySelector:s=>s==='.change-provenance'?disclosure:s==='[data-history-page="older"]'?{disabled:true}:s==='[data-history-page]:not([disabled])'?{focus(){focused=true;}}:null};
 c.document.activeElement={getAttribute:n=>n==='data-history-page'?'older':null};c.researchChangesRender(el,{comparable:true,history:[],history_offset:100,history_has_more:false,scope:'deployment_owner',counts:{new:0,exited:0,all:0,unchanged:0},matched:0,rows:[],definition:{filters:[]}});assert.equal(disclosure.open,true);assert.equal(focused,true);assert.match(el.innerHTML,/Retained capture page 2/);assert.match(el.innerHTML,/deployment-shared history/);
});


test('company shortlist search preserves punctuation, caret and review context through debounce',async()=>{
 const c=harness();let run,shows=0,focused=false,range;c.__researchListID='list';c.__researchListGen=2;c.__researchListStatus='reviewed';c.__researchListOffset=100;c.__researchReviewCursor='US.OLD';vm.runInContext("state.page='shortlists'",c);
 c.setTimeout=fn=>{run=fn;return 1;};c.showPage=async()=>{shows++;};c.document.getElementById=id=>id==='research-list-search'?{focus(){focused=true;},setSelectionRange(a,b){range=[a,b];}}:{textContent:''};
 const name="O'Reilly & Sons";c.researchListSearch({value:name,selectionStart:8});await run();
 assert.equal(shows,1);assert.equal(c.__researchListOffset,0);assert.equal(c.__researchReviewCursor,null);assert.equal(c.__researchListStatus,'reviewed');assert.equal(new URLSearchParams(c.researchListQuery()).get('q'),name);assert.equal(focused,true);assert.deepEqual(range,[8,8]);
});


test('prepared private download URLs are revoked when the research account clears',()=>{
 const c=harness(),revoked=[];c.URL={revokeObjectURL:url=>revoked.push(url)};c.__researchExportURLs=new Set(['blob:private-a','blob:private-b']);c.researchPrivateClear();assert.deepEqual(revoked,['blob:private-a','blob:private-b']);assert.equal(c.__researchExportURLs.size,0);
});
test('late export errors cannot surface private activity after an account change',async()=>{
 const c=harness();c.researchSessionSet(privateSession());c.__researchListID='list';let reject,writes=[];const status={isConnected:true,set textContent(v){writes.push(v);}};c.document.getElementById=id=>id==='research-list-status'?status:null;c.researchPrivateAPI=()=>new Promise((_,r)=>reject=r);const pending=c.researchListExport();c.researchPrivateClear();reject(Error('Old owner private list failure'));await pending;assert.deepEqual(writes,['Preparing full shortlist CSV…']);
});

test('repeated criterion windows retain independent columns, sorts and evidence rows',()=>{
 const c=harness(),definition={filters:[{field:'volume',days:30,min:0},{field:'volume',days:60,min:0}]};const criteria=c.researchChangeCriteria(definition);assert.equal(criteria.length,2);assert.equal(criteria[0].sort_key,'c0');assert.equal(criteria[1].sort_key,'c1');
 const row={evidence:{volume:999},criterion_observations:{c0:{value:10},c1:{value:100}}};assert.equal(c.researchCapturedCriterion(row,criteria[0]),10);assert.equal(c.researchCapturedCriterion(row,criteria[1]),100);assert.equal(c.researchCapturedCriterion({evidence:{volume:999}},criteria[0]),undefined);
 const html=c.researchCriterionMatrix(definition.filters,[{criterion_key:'c0',field:'volume',previous:10,current:20,period:'30-day average',status:'comparable',assessment:'rule_retained'},{criterion_key:'c1',field:'volume',previous:100,current:200,period:'60-day average',status:'unavailable_pair'}],true);
 assert.match(html,/30-day average/);assert.match(html,/60-day average/);assert.match(html,/100/);assert.match(html,/200/);assert.match(html,/Comparable observations/);assert.match(html,/comparability unverified/);
});
test('quote inspector separates provider update and cache clocks without inferring currency',()=>{
 const c=harness(),row={code:'HK.80000',quote_observed_at:'2026-10-02T00:00:00Z',quote_time_semantics:'provider_snapshot_update',quote_cache_at:'2026-10-02T01:00:00Z',data_date:'2026-10-02',update_time:1790919256};
 assert.equal(c.researchQuoteCurrency(row),'');assert.equal(c.researchQuoteCurrency({...row,currency:'CNY'}),'CNY');assert.equal(c.researchQuoteCurrency({...row,currency:'<script>'}),'');
 const html=c.researchQuoteProvenance(row);assert.match(html,/Provider snapshot updated:/);assert.match(html,/Cache updated:/);assert.match(html,/Price currency: Not supplied/);assert.match(html,/not last-trade time/);assert.doesNotMatch(html,/HKD/);
 const missing=c.researchQuoteProvenance({...row,quote_time_semantics:null,quote_observed_at:null,quote_cache_at:'2026-10-02 01:00:00'});assert.match(missing,/Provider snapshot updated: Unavailable/);assert.match(missing,/Cache updated: Unavailable/);
});

test('capture retry keeps viewed generation through a refresh and reload',()=>{
 const c=harness(),store=new Map();let ids=0;c.crypto={randomUUID:()=>`00000000-0000-4000-8000-${String(++ids).padStart(12,'0')}`};
 c.sessionStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)};
 const first='11111111-1111-4111-8111-111111111111',next='22222222-2222-4222-8222-222222222222';
 c.__scrDataset={key:'US|0|moo',generationId:first};const def=c.researchDefinition(),request=c.researchCaptureRequest(def);
 c.__scrDataset.generationId=next;c.__captureRequest=null;
 const retry=c.researchCaptureRequest(def);assert.equal(retry.id,request.id);assert.equal(retry.generation_id,first);
 c.researchCaptureConfirmed(retry);assert.equal(c.researchCaptureRequest(def).generation_id,next);
 c.__scr.activePreset='p';assert.equal(c.researchViewedGeneration(),null);
 c.__scr.activePreset=null;c.__scr.market='HK';assert.equal(c.researchViewedGeneration(),null);
});
test('local export retains canonical generation and cache time while escaping spreadsheet formulas',async()=>{
 const c=harness(),gid='11111111-1111-4111-8111-111111111111';c.__scr.cols=['symbol','name'];
 c.scrClientRows=()=>[stock('A',10,1,{code:'US.A',name:'=1+1',generation_id:gid,quote_cache_at:'2026-10-02T06:00:00Z'})];
 let blob;c.Blob=Blob;c.URL={createObjectURL:b=>{blob=b;return 'blob:test';},revokeObjectURL(){}};c.document.createElement=()=>({click(){},remove(){}});
 c.scrExport('csv','all');const text=await blob.text();assert.match(text,/generation_id,quote_cache_at/);assert.match(text,/US.A/);assert.match(text,/'=1\+1/);assert.ok(text.includes(gid));
 c.scrExport('xls','all');const xml=await blob.text();assert.ok(xml.includes(gid));assert.match(xml,/ss:Type="String">=1\+1/);
});

test('provider scope distinguishes retrieved, stock-filtered, unknown and display-cohort membership',()=>{
 const c=harness(),gid='11111111-1111-4111-8111-111111111111';
 const payload={rows:[{code:'US.A',stock_type:'STOCK',quote_generation_id:gid},{code:'US.E',stock_type:'ETF',quote_generation_id:gid},{code:'US.U',stock_type:'UNKNOWN'}],provider_total:9,quote_generation_id:gid,hydration_warnings:['<untrusted quote>'],next_key:'p2',possibly_truncated:true};
 const html=c.researchProviderScopeHTML(payload,[payload.rows[0]],{etfs:false});
 assert.match(html,/1 stock matches loaded/);assert.match(html,/3 provider members retrieved/);assert.match(html,/9 provider matches before exclusions/);assert.match(html,/1 instrument has unknown classification/);assert.match(html,/1 retrieved members outside this cohort/);assert.match(html,/does not freeze provider membership/);assert.match(html,/&lt;untrusted quote&gt;/);assert.doesNotMatch(html,/<untrusted quote>/);assert.match(html,/Load next 300 matches/);
});
test('preset paging pins display cohort and retains earlier hydration warnings',async()=>{
 const c=harness(),gid='11111111-1111-4111-8111-111111111111';Object.assign(c.__scr,{activePreset:'p',market:'US'});
 c.__presetCache={'p|US':{payload:{quote_generation_id:gid,next_key:'page 2',rows:[{code:'US.A'}],hydration_warnings:['Earlier page unavailable']}}};let url,rendered=0;
 c.api=async u=>{url=u;return {available:true,quote_generation_id:gid,rows:[{code:'US.B'}],hydration_warnings:['Later page unavailable']};};c.showPage=async()=>{rendered++;};
 await c.researchLoadMore();assert.equal(new URLSearchParams(url.split('?')[1]).get('quote_generation_id'),gid);assert.equal(new URLSearchParams(url.split('?')[1]).get('next_key'),'page 2');assert.equal(rendered,1);assert.equal(c.__presetCache['p|US'].payload.rows.map(r=>r.code).join(','),'US.A,US.B');assert.equal(c.__presetCache['p|US'].payload.hydration_warnings.join('|'),'Earlier page unavailable|Later page unavailable');
});
test('preset paging rejects a changed display cohort without replacing prior rows',async()=>{
 const c=harness(),entry={payload:{quote_generation_id:'old',next_key:'p2',rows:[{code:'US.A'}]}};Object.assign(c.__scr,{activePreset:'p',market:'US'});c.__presetCache={'p|US':entry};const status={textContent:''};c.document.getElementById=id=>id==='research-page-status'?status:null;
 c.api=async()=>({available:true,quote_generation_id:'new',rows:[{code:'US.B'}]});c.showPage=()=>assert.fail('Mismatched page rendered');await c.researchLoadMore();assert.equal(c.__presetCache['p|US'],entry);assert.match(status.textContent,/Quote display cohort changed/);
});
test('provider page drift preserves original rows and cursor with a persistent escaped recovery message',async()=>{
 for(const fault of ['overlap','total','cursor','empty','incomplete','duplicate','market']){
  const c=harness(),original={code:'US.A',price:10},entry={retained:true,payload:{available:true,next_key:'p2',possibly_truncated:true,provider_total:3,rows:[original]}};
  Object.assign(c.__scr,{activePreset:'p',market:'US'});c.__presetCache={'p|US':entry};
  const next={available:true,rows:[{code:'US.B'}],provider_total:3,next_key:'p3',possibly_truncated:true};
  if(fault==='overlap')next.rows=[{code:'US.A',price:999},{code:'US.B'}];
  if(fault==='total')next.provider_total=4;
  if(fault==='cursor')next.next_key='p2';
  if(fault==='empty')next.rows=[];
  if(fault==='incomplete'){next.next_key=null;next.possibly_truncated=false;}
  if(fault==='duplicate')next.rows=[{code:'US.B'},{code:'US.B'}];
  if(fault==='market')next.rows=[{code:'HK.00700'}];
  c.api=async()=>next;c.showPage=()=>assert.fail('Inconsistent continuation rendered');
  await c.researchLoadMore();assert.equal(c.__presetCache['p|US'],entry);assert.equal(entry.payload.rows[0],original);assert.equal(original.price,10);assert.equal(entry.payload.next_key,'p2');assert.match(entry.pageError,/previous results retained/);assert.equal(c.__presetPagePending.size,0);
  entry.pageError+='<provider>';const html=c.researchProviderScopeHTML(entry.payload,entry.payload.rows,c.__scr);assert.match(html,/Retry next page/);assert.match(html,/&lt;provider&gt;/);assert.doesNotMatch(html,/<provider>/);
 }
});
test('rate-limited continuation retries the same cursor and clears the error only after a valid complete page',async()=>{
 const c=harness(),entry={retained:true,payload:{available:true,rows:[{code:'US.A'}],provider_total:2,next_key:'p2',possibly_truncated:true}};
 Object.assign(c.__scr,{activePreset:'p',market:'US'});c.__presetCache={'p|US':entry};let calls=0;const cursors=[];
 c.api=async url=>{cursors.push(new URLSearchParams(url.split('?')[1]).get('next_key'));return ++calls===1?{available:false,reason:'rate_limited; retry after 5.0s'}:{available:true,rows:[{code:'US.B'}],provider_total:2,next_key:null,possibly_truncated:false};};
 c.showPage=()=>{assert.equal(c.__presetPagePending.size,0);};
 await c.researchLoadMore();assert.equal(c.__presetCache['p|US'],entry);assert.match(entry.pageError,/rate_limited/);
 await c.researchLoadMore();assert.deepEqual(cursors,['p2','p2']);assert.equal(c.__presetCache['p|US'].payload.rows.map(r=>r.code).join(','),'US.A,US.B');assert.equal(c.__presetCache['p|US'].pageError,undefined);
});
test('provider cursor history rejects cycles while preserving established totals when a page omits them',()=>{
 const c=harness(),current={rows:[{code:'US.A'}],provider_total:3,next_key:'p3'},next={rows:[{code:'US.B'}],next_key:'p2',possibly_truncated:true};
 assert.throws(()=>c.researchMergeProviderPage(current,next,'US',['p2']),/cursor repeated/);
 next.next_key='p4';assert.equal(c.researchMergeProviderPage(current,next,'US',['p2']).length,2);
});
test('late provider page and error cannot overwrite a refreshed cache entry',async()=>{
 for(const failure of [false,true]){const c=harness(),entry={payload:{next_key:'p2',rows:[{code:'US.A'}]}};Object.assign(c.__scr,{activePreset:'p',market:'US'});c.__presetCache={'p|US':entry};let resolve,reject;const status={textContent:''};c.document.getElementById=id=>id==='research-page-status'?status:null;c.api=()=>new Promise((a,b)=>{resolve=a;reject=b;});c.showPage=()=>assert.fail('Old page rendered');const pending=c.researchLoadMore();const newer={payload:{rows:[{code:'US.NEW'}]}};c.__presetCache['p|US']=newer;if(failure)reject(Error('Old request failed'));else resolve({available:true,rows:[{code:'US.OLD'}]});await pending;assert.equal(c.__presetCache['p|US'],newer);assert.equal(status.textContent,'');}
});
test('display field provenance separates screening and hydration without asserting reporting periods',()=>{
 const c=harness(),html=c.researchQuoteProvenance({display_field_sources:{price:{source:'provider_screen',retrieved_at:'2026-10-02T06:00:00Z'},market_cap:{source:'stored_generation',generation_id:'<id>',cache_at:'2026-10-02T05:00:00Z'},stock_type:{source:'provider_basicinfo',retrieved_at:'2026-10-02T06:01:00Z'}}});assert.match(html,/Price: Provider screen/);assert.match(html,/Market Cap: Stored generation/);assert.match(html,/&lt;id&gt;/);assert.match(html,/Type: Provider classification/);assert.match(html,/different source times/);
 const desk=c.researchDeskHTML({st:c.__scr,scr:{server_side:true,rows:[],matched:0},table:'',allChips:'',msPanel:''});assert.match(desk,/financial basis requested: annual; reported period unverified/);assert.doesNotMatch(desk,/financial criteria: annual/);
});

test('opened expired preset retains all loaded pages during home rendering and intent warming',async()=>{
 const c=harness(),rows=[stock('A',10,1,{code:'US.A'}),stock('B',9,2,{code:'US.B'})];Object.assign(c.__scr,{activePreset:'p',market:'US'});
 const entry={ts:Date.now()-120000,retained:true,payload:{available:true,rows,filters:[],name:'Retained',retrieved_at:'2026-10-02T00:00:00Z'}};c.__presetCache={'p|US':entry};c.__panelCache={market:'US',rail:{presets:[{key:'p',name:'Retained',filters:[]}]}};c.scrStreamPanels=()=>{};c.api=()=>assert.fail('Navigation fetched a replacement cohort');
 c.scrWarmPreset('p','US');assert.equal(c.__presetWarmQueue,undefined);
 await vm.runInContext('pages.home()',c);assert.equal(c.__homeCtx.scr.matched,2);assert.equal(c.__homeCtx.execd,entry.payload);assert.equal(c.__presetCache['p|US'],entry);
});
test('explicit preset refresh replaces only on success and revalidates selection',async()=>{
 const c=harness(),entry={ts:1,retained:true,payload:{available:true,rows:[{code:'US.A',stock_type:'STOCK'},{code:'US.OLD',stock_type:'STOCK'}],filters:[],next_key:'old-page'}};Object.assign(c.__scr,{activePreset:'p',market:'US',page:3});c.__presetCache={'p|US':entry};c.__researchSelected=['US.A','US.OLD'];let url,renders=0;c.showPage=async()=>{renders++;};c.api=async u=>{url=u;assert.equal(c.__presetCache['p|US'],entry);return {available:true,rows:[{code:'US.A',stock_type:'STOCK'}],filters:[],next_key:'new-page'};};
 await c.researchRefreshPreset();assert.equal(new URLSearchParams(url.split('?')[1]).get('refresh'),'true');assert.equal(c.__scr.page,1);assert.equal(c.__researchSelected.join(','),'US.A');assert.equal(c.__presetCache['p|US'].retained,true);assert.equal(c.__presetCache['p|US'].payload.next_key,'new-page');assert.equal(c.__presetRefresh['p|US'],undefined);assert.equal(renders,2);
});
test('failed preset refresh retains cohort page and selections with an escaped failure disclosure',async()=>{
 const c=harness(),entry={retained:true,payload:{available:true,rows:[{code:'US.A',stock_type:'STOCK'}]}};Object.assign(c.__scr,{activePreset:'p',market:'US',page:3});c.__presetCache={'p|US':entry};c.__researchSelected=['US.A'];c.api=async()=>({available:false,reason:'<provider failure>'});await c.researchRefreshPreset();assert.equal(c.__presetCache['p|US'],entry);assert.equal(c.__scr.page,3);assert.equal(c.__researchSelected.join(','),'US.A');const html=c.researchProviderScopeHTML(entry.payload,entry.payload.rows,c.__scr);assert.match(html,/Refresh failed; previous results retained/);assert.match(html,/&lt;provider failure&gt;/);
});
test('preset refresh is single flight and cannot overwrite a newer cache entry',async()=>{
 const c=harness(),entry={retained:true,payload:{available:true,rows:[]}};Object.assign(c.__scr,{activePreset:'p',market:'US'});c.__presetCache={'p|US':entry};let resolve,requests=0;c.api=()=>{requests++;return new Promise(r=>resolve=r);};const pending=c.researchRefreshPreset();await Promise.resolve();await c.researchRefreshPreset();assert.equal(requests,1);const newer={retained:true,payload:{available:true,rows:[{code:'US.NEW'}]}};c.__presetCache['p|US']=newer;resolve({available:true,rows:[]});await pending;assert.equal(c.__presetCache['p|US'],newer);
});
test('provider paging and explicit refresh cannot run simultaneously',async()=>{
 const c=harness(),entry={retained:true,payload:{available:true,rows:[],next_key:'p2'}};Object.assign(c.__scr,{activePreset:'p',market:'US'});c.__presetCache={'p|US':entry};let resolve,requests=0;c.api=()=>{requests++;return new Promise(r=>resolve=r);};const paging=c.researchLoadMore();await c.researchRefreshPreset();assert.equal(requests,1);resolve({available:true,rows:[{code:'US.A'}]});await paging;assert.equal(c.__presetPagePending.size,0);
});
test('provider scope appears before analytical rows and does not add content to default results',()=>{
 const c=harness(),html=c.researchDeskHTML({st:c.__scr,scr:{rows:[],matched:0},table:'<table id="rows"></table>',allChips:'',msPanel:''});assert.ok(html.indexOf('id="research-provider-paging"')<html.indexOf('id="rows"'));assert.equal((html.match(/id="research-provider-paging"/g)||[]).length,1);
});

test('provider coverage keeps partial scope and warnings visible with expandable source details',()=>{
 const c=harness(),payload={rows:[{code:'US.U',stock_type:'UNKNOWN'}],provider_total:10,hydration_warnings:['<warning>'],quote_generation_id:'<cohort>',next_key:'p2',possibly_truncated:true};
 const html=c.researchProviderScopeHTML(payload,[],{market:'US',activePreset:'p',etfs:false});
 assert.match(html,/aria-label="Provider result coverage"/);assert.match(html,/0 stock matches loaded/);assert.match(html,/10 provider matches before exclusions/);assert.match(html,/<summary>1 instrument has unknown classification · 1 hydration warning<\/summary>/);assert.match(html,/&lt;cohort&gt;/);assert.match(html,/&lt;warning&gt;/);assert.equal((html.match(/id="research-load-more"/g)||[]).length,1);assert.equal((html.match(/id="research-refresh-preset"/g)||[]).length,1);
 c.__presetRefresh={'p|US':true};const busy=c.researchProviderScopeHTML(payload,[],{market:'US',activePreset:'p'});assert.match(busy,/Previous results retained while refreshing/);assert.match(busy,/research-load-more[^>]*disabled/);assert.match(busy,/research-refresh-preset[^>]*disabled/);
});

test('region criteria reproduce numeric membership, intersect repeated axes and preserve inclusive zero',()=>{
 const c=harness(),st={x:'pe_ttm',y:'pct',bounds:{x:{min:null,max:20},y:{min:-2,max:0}}};
 const rows=[stock('A',10,0,{pe_ttm:10}),stock('B',9,-2,{pe_ttm:20}),stock('C',8,-1,{pe_ttm:0}),stock('D',7,'',{pe_ttm:5}),stock('E',6,Infinity,{pe_ttm:5})];
 const rules=c.researchExploreCriteria(st);assert.equal(rules[0].min,0);assert.equal(rules[0].excl_min,true);assert.equal(c.scrFieldPass(rows,rules).map(r=>r.symbol).join(','),c.researchExploreSelected(rows,st).map(r=>r.symbol).join(','));
 const repeated=c.researchExploreCriteria({x:'pb',y:'pb',bounds:{x:{min:1,max:5},y:{min:2,max:4}}});assert.equal(repeated.length,1);assert.equal(repeated[0].min,2);assert.equal(repeated[0].max,4);
 assert.throws(()=>c.researchExploreCriteria({x:'pb',y:'pb',bounds:{x:{min:1,max:2},y:{min:3,max:4}}}),/intersection/);
});
test('apply region preserves preset rules and sort, marks Modified and round-trips a saved definition',async()=>{
 const c=harness(),original=[{field:'volume',min:100000,days:30}];c.__scrPresets=[{key:'p',name:'Original',filters:original,sort:'pct',direction:2}];c.scrApplyPreset('p');
 const rows=[stock('A',10,0,{code:'US.A',pe_ttm:10,volume:10}),stock('B',9,2,{code:'US.B',pe_ttm:20,volume:10})];c.__presetCache={'p|US':{payload:{available:true,rows,filters:original}}};c.__researchSelected=['US.A','US.B'];
 const st=c.researchExploreState();Object.assign(st,{x:'pe_ttm',y:'pct',bounds:{x:{min:5,max:15},y:{min:0,max:0}},preview:true});c.researchExploreCommit();
 assert.equal(c.__scr.activePreset,'p');assert.equal(c.__scr.sort,'pct');assert.equal(c.__scr.dir,2);assert.equal(c.__scr.presentation,'table');assert.equal(c.__researchSelected.join(','),'US.A');assert.deepEqual(original,[{field:'volume',min:100000,days:30}]);assert.equal(c.scrPresetRows(c.__presetCache['p|US'].payload).map(r=>r.code).join(','),'US.A');
 const saved=JSON.parse(JSON.stringify({...c.scrCurrentScreenerState(),id:'region',name:'Region'}));c.scrResetAll();c.__savedScreeners=[saved];await c.scrApplySaved('region');assert.equal(c.__scr.activePreset,'p');assert.equal(c.researchSavedModified(saved,c.__scr),false,JSON.stringify({saved,state:c.__scr}));assert.equal(c.scrPresetRows(c.__presetCache['p|US'].payload).map(r=>r.code).join(','),'US.A');
});

test('saved metadata arrival restores the title after reload without changing screen criteria',()=>{
 const c=harness({filters:[{field:'pct',min:-1,max:1}],savedScreenId:'region'}),heading={textContent:'Saved screen'},library={innerHTML:''};c.document.getElementById=id=>id==='research-saved'?library:null;c.document.querySelector=q=>q==='.desk-title h2'?heading:null;c.researchLibrarySearch=()=>{};
 c.__savedScreeners=[{id:'region',name:'<Region>',market:'US',filters:[{field:'pct',min:-1,max:1}],sort:'market_cap',direction:2,settings:{}}];c.researchSavedMount();assert.equal(heading.textContent,'<Region>');assert.equal(c.__scr.filters.length,1);
});

test('Explorer coordinate groups preserve collisions and screen sort without jitter or merging nearby values',()=>{
 const c=harness();const rows=[stock('BRK.B',100,0,{code:'US.BRK.B',pe_ttm:8}),stock('BRK.A',90,0,{code:'US.BRK.A',pe_ttm:8}),stock('C',80,0,{code:'US.C',pe_ttm:8.000001}),stock('D',70,0,{code:'US.D',pe_ttm:null})];
 const st={x:'pe_ttm',y:'pct',xs:'linear',ys:'linear',trim:false,bounds:null,zoom:false};
 const groups=c.researchExplorePointGroups(rows,st);
 assert.deepEqual(Array.from(groups,g=>Array.from(g.rows,r=>r.code)),[['US.BRK.B','US.BRK.A'],['US.C']]);
 assert.equal(groups[0].x,8);assert.equal(groups[0].y,0);assert.equal(rows[2].pe_ttm,8.000001);
 assert.equal(c.researchExploreKeyboard(groups,st,'ArrowRight'),groups[0]);
 assert.equal(c.researchExploreKeyboard(groups,st,'Enter'),groups[0]);
 assert.equal(c.researchExploreKeyboard(groups,st,'ArrowDown'),groups[1]);
 assert.equal(c.researchExploreKeyboard(groups,st,'ArrowRight'),groups[1]);
 assert.equal(c.researchExploreKeyboard(groups,st,'Home'),groups[0]);
 assert.equal(c.researchExploreKeyboard(groups,st,'End'),groups[1]);
 assert.equal(c.researchExploreKeyboard(groups,st,'Tab'),null);
 st.xs='log';st.ys='log';assert.equal(c.researchExplorePointGroups(rows,st).length,0);
});
test('Explorer coordinate picker revalidates plotted identities and pages all collisions without changing rules',()=>{
 const c=harness();const rows=Array.from({length:121},(_,i)=>stock('A'+i,200-i,1,{code:'US.A'+i,pe_ttm:8}));
 c.researchRows=()=>rows;const st=c.researchExploreState();let markup='',focus=0,inspected;
 c.document.getElementById=id=>id==='explore-point-picker'?{set innerHTML(v){markup=v;}}:id==='research-scatter'?{focus(){focus++;}}:null;
 c.document.querySelector=()=>({focus(){focus++;}});c.researchInspectRow=(r)=>{inspected=r.code;};
 const original=JSON.stringify(c.__scr);const group=c.researchExplorePointGroups(rows,st)[0];
 c.researchExplorePointOpen(group,{});assert.equal(st.pointCodes.length,121);assert.match(markup,/1–50 of 121/);assert.match(markup,/Inspect A49 at coordinate/);assert.doesNotMatch(markup,/Inspect A50 at coordinate/);
 c.researchExplorePointPage(1);assert.match(markup,/51–100 of 121/);
 c.researchExplorePointPage(1);assert.match(markup,/101–121 of 121/);
 c.researchExplorePointPage(1);assert.match(markup,/101–121 of 121/);
 rows[0].pct=null;assert.equal(c.researchExplorePointRows().length,120);rows[2].pct=2;assert.equal(c.researchExplorePointRows().length,119);
 c.researchExplorePointOpen({rows:[rows[1]]},{});assert.equal(inspected,'US.A1');assert.equal(markup,'');
 c.researchExplorePointClose();assert.equal(st.pointCodes,null);assert.ok(focus>=5);assert.equal(JSON.stringify(c.__scr),original);
});

test('group rendering labels field coverage and currency without an undefined formatter',async()=>{
 const c=harness();c.api=async()=>({available:true,rows:[{key:'Known group',stocks:2,cap_sum:null,cap_currency:null,chg_avg:0,adv:0,decl:0,avgs:{pe_ttm:8},coverage:{pe_ttm:1},drillable:true},{key:'Unknown',stocks:1,cap_sum:100,cap_currency:'HKD',avgs:{},coverage:{market_cap:1},drillable:false}]});
 const html=await c.groupsPage();assert.match(html,/Unavailable/);assert.match(html,/HKD 100/);assert.match(html,/1\/2/);assert.match(html,/Open Known group group in screener/);assert.doesNotMatch(html,/Open Unknown group/);
});
test('group drill opens its exact source cohort instead of retaining hidden preset or private scope',()=>{
 const c=harness();Object.assign(c.__scr,{activePreset:'p',savedScreenId:'saved',filters:[{field:'price',min:100}],colFilters:{pb:{max:1}},watchlistOnly:true,etfs:true,page:5,presentation:'changes'});c.__researchSelected=['US.OLD'];
 c.scrDrillTo('sector','Technology');assert.equal(c.__scr.src,'yf');assert.equal(c.__scr.activePreset,null);assert.equal(c.__scr.savedScreenId,null);assert.equal(c.__scr.page,1);assert.equal(c.__scr.presentation,'table');assert.equal(c.__scr.etfs,false);assert.equal(c.__scr.watchlistOnly,false);assert.equal(c.__researchSelected.length,0);assert.equal(JSON.stringify(c.__scr.filters),'[{"field":"sector","values":["Technology"]}]');
 const before=JSON.stringify(c.__scr);c.scrDrillTo('cap_bucket','Unknown');assert.equal(JSON.stringify(c.__scr),before);
});

test('monetary display requires matching field observations and never borrows trading currency',()=>{
 const c=harness();const r={code:'US.BRK.B',currency:'USD',price:0,eps:2,market_cap:1000,field_observations:{}};
 const obs=(field,currency)=>({code:r.code,field,value:r[field],unit:'currency',currency});
 assert.equal(c.researchMoneyValue(r,'market_cap'),'1K · currency unavailable');
 assert.match(c.researchMoneyHTML(r,'price'),/^0 [\s\S]*Currency not supplied/);
 r.field_observations.price=obs('price','USD');r.field_observations.eps=obs('eps','HKD');
 assert.equal(c.researchMoneyValue(r,'eps'),'HKD 2');assert.match(c.researchMoneyHTML(r,'price'),/^USD /);
 r.field_observations.market_cap=obs('market_cap','EUR');assert.equal(c.researchMoneyValue(r,'market_cap'),'EUR 1K');
 for(const mutation of [{code:'US.BRK.A'},{value:999},{unit:'ratio'},{currency:'<USD>'},{value:true}]){
  r.field_observations.market_cap={...obs('market_cap','USD'),...mutation};assert.equal(c.researchFieldCurrency(r,'market_cap'),'');
 }
 assert.equal(c.researchValue('market_cap',false),'Unavailable');assert.equal(c.researchValue('market_cap',[]),'Unavailable');
});

test('currency and typed provenance survive CSV and Excel selected exports',async()=>{
 const c=harness(),r=stock('A',10,0,{code:'US.A',price:2,field_observations:{market_cap:{code:'US.A',field:'market_cap',value:10,unit:'currency',currency:'HKD'}}});
 c.scrClientRows=()=>[r];c.__scr.cols=['market_cap','price'];c.__researchSelected=['US.A'];
 let blob;c.Blob=Blob;c.URL={createObjectURL:b=>{blob=b;return 'blob:test';},revokeObjectURL(){}};c.document.createElement=()=>({click(){},remove(){}});
 c.scrExport('csv','selected');const csv=await blob.text();assert.match(csv,/market_cap_currency,price_currency,field_observations/);assert.match(csv,/,HKD,Unavailable,/);assert.match(csv,/""currency"":""HKD""/);
 c.scrExport('xls','selected');const xml=await blob.text();assert.match(xml,/market_cap_currency/);assert.match(xml,/>HKD</);assert.match(xml,/"currency":"HKD"/);assert.doesNotMatch(xml,/\[object Object\]/);
});

test('criterion evidence distinguishes requested basis from matching actual observations',()=>{
 const c=harness(),r={code:'US.A',roe:25,criterion_values:{roe:0},display_field_sources:{roe:{source:'yfinance',cache_at:'2026-10-02T00:00:00Z'}},field_observations:{roe:{code:'US.A',field:'roe',value:25,period:'FY2025',source:'source fixture'}}};
 const provider=c.researchEvidence(r,{field:'roe',min:10},'preset');assert.equal(provider.value,'0%');assert.equal(provider.period,'Reported period not supplied');assert.match(provider.status,/does not pass/);
 const stored=c.researchEvidence(r,{field:'roe',min:10},null);assert.equal(stored.period,'FY2025');assert.equal(stored.source,'yfinance cached factor');assert.match(stored.status,/passes/);
 r.field_observations.roe.code='US.B';assert.equal(c.researchEvidence(r,{field:'roe'},null).period,'Reported period not supplied');
 r.criterion_values.roe=false;assert.equal(c.researchEvidence(r,{field:'roe'},'preset').value,'Numeric evidence unavailable');
});

test('preset and appended criteria use independent evidence sources and clocks',()=>{
 const c=harness(),original={field:'volume',min:100,days:30},added={field:'roe',min:10};
 c.__scrPresets=[{key:'p',filters:[original]}];
 const r={code:'US.A',volume:9,roe:25,criterion_values:{volume:999,roe:0},criterion_retrieved_at:'2026-10-02T01:00:00Z',criterion_evidence:[{code:'US.A',criterion:original,value:120,retrieved_at:'2026-10-02T01:00:00Z'}],display_field_sources:{volume:{source:'stored_generation',cache_at:'2026-10-01T00:00:00Z'},roe:{source:'yfinance',cache_at:'2026-10-02T00:00:00Z'}}};
 const provider=c.researchEvidence(r,original,'p');assert.equal(provider.value,'120 shares');assert.equal(provider.display_value,'9 shares');assert.match(provider.timestamp,/02 Oct/);
 const custom=c.researchEvidence(r,added,'p');assert.equal(custom.value,'25%');assert.equal(custom.source,'yfinance cached factor');assert.equal(custom.display_value,null);
 r.criterion_evidence[0].code='US.B';assert.equal(c.researchEvidence(r,original,'p').value,'Numeric evidence unavailable');
 r.criterion_evidence=[];assert.equal(c.researchEvidence(r,original,'p').value,'Numeric evidence unavailable');
});

test('repeated criterion windows cannot reuse a different retrieved observation',()=>{
 const c=harness(),a={field:'volume',min:10,days:10},b={field:'volume',max:200,days:30};c.__scrPresets=[{key:'p',filters:[a,b]}];
 const r={code:'US.A',criterion_values:{volume:999},criterion_evidence:[{code:'US.A',criterion:a,value:11},{code:'US.A',criterion:b,value:150}]};
 assert.equal(c.researchEvidence(r,a,'p').value,'11 shares');assert.equal(c.researchEvidence(r,b,'p').value,'150 shares');r.criterion_evidence.push({...r.criterion_evidence[0]});assert.equal(c.researchEvidence(r,a,'p').value,'Numeric evidence unavailable');
});

test('inspector evidence includes column criteria without inventing a custom default instrument rule',async()=>{
 const c=harness(),inspector={classList:{add(){}},setAttribute(){},removeAttribute(){},querySelector:()=>null};c.document.getElementById=id=>id==='research-inspector'?inspector:null;
 c.__scr.filters=[];c.__scr.colFilters={roe:{min:10}};c.__inspectTab='why';c.__researchInspectCode='US.A';
 await c.researchInspectRow({code:'US.A',symbol:'A',roe:25});assert.match(inspector.innerHTML,/ROE %/);assert.match(inspector.innerHTML,/25%/);assert.doesNotMatch(inspector.innerHTML,/<h4>Type<\/h4>/);
 assert.equal(c.scrEffFilters().some(f=>f.field==='stock_type'),true);assert.equal(c.scrEffFilters(false).length,1);
});

test('CSV and SpreadsheetML preserve per-rule membership evidence independently of table values',async()=>{
 const c=harness();let blob;c.Blob=Blob;c.URL={createObjectURL:b=>{blob=b;return 'blob:test';},revokeObjectURL(){}};c.document.createElement=()=>({click(){},remove(){}});
 const criteria=[{code:'US.A',criterion:{field:'volume',min:100,days:30},value:120,source:'provider_screen',retrieved_at:'2026-10-02T01:00:00Z'}];
 const row=stock('A',10,1,{code:'US.A',volume:9,criterion_values:{volume:120},criterion_evidence:criteria,criterion_retrieved_at:'2026-10-02T01:00:00Z'});
 c.scrClientRows=()=>[row];c.__scr.cols=['symbol','volume'];
 c.scrExport('csv','loaded');const csv=await blob.text();assert.match(csv,/criterion_values,criterion_evidence,criterion_retrieved_at/);assert.match(csv,/""days"":30/);assert.match(csv,/""value"":120/);assert.match(csv,/,9,/);
 c.scrExport('xls','loaded');const xml=await blob.text();assert.match(xml,/"days":30/);assert.match(xml,/"value":120/);assert.doesNotMatch(xml,/\[object Object\]/);
});

test('company context requires source and freshness and only links safe supplied websites',()=>{
 const c=harness(),now=Date.now(),origin={source:'yfinance',cache_at:new Date(now).toISOString()},p={code:'US.A',fields:{sector:'Technology',industry:'Software',website:'https://company.example/'},origins:{sector:origin,industry:origin,website:origin}};
 const html=c.researchCompanyContextHTML(p,'US.A',now);assert.match(html,/Technology/);assert.match(html,/href="https:\/\/company.example\/"/);
 assert.doesNotMatch(c.researchCompanyContextHTML(p,'US.B',now),/Technology|href=/);
 assert.doesNotMatch(c.researchCompanyContextHTML(p,'US.A',now+8*86400000),/Technology|href=/);
 for(const site of ['javascript:alert(1)','data:text/html,bad','https://user:password@company.example/']){p.fields.website=site;assert.doesNotMatch(c.researchCompanyContextHTML(p,'US.A',now),/href=/);}
});

test('late company metadata cannot replace a newer inspector and cached fields avoid repeat requests',async()=>{
 const c=harness();let resolve,markup='',calls=0;c.api=()=>{calls++;return new Promise(r=>resolve=r);};c.document.getElementById=()=>({set innerHTML(v){markup=v;}});c.__inspectGen=1;c.__researchInspectCode='US.A';
 const pending=c.researchCompanyMount('US.A',1);c.__inspectGen=2;c.__researchInspectCode='US.B';resolve({code:'US.A',fields:{},origins:{}});await pending;assert.equal(markup,'');
 c.__researchInspectCode='US.A';await c.researchCompanyMount('US.A',2);assert.equal(calls,1);assert.match(markup,/Unavailable/);
});

test('company dates use each qualified field clock and never borrow another source date',()=>{
 const c=harness(),now=Date.now(),sectorAt=new Date(now-86400000).toISOString(),industryAt=new Date(now-3600000).toISOString();
 const p={code:'US.A',fields:{sector:'Technology',industry:'Software',website:'https://company.example/'},
  origins:{sector:{source:'yfinance',cache_at:sectorAt},industry:{source:'yfinance',cache_at:industryAt},website:{source:'yfinance',cache_at:'2026-01-01'}}};
 const html=c.researchCompanyContextHTML(p,'US.A',now);
 assert.match(html,new RegExp('datetime="'+sectorAt+'"'));assert.match(html,new RegExp('datetime="'+industryAt+'"'));
 assert.match(html,/Website: qualified source\/retrieval time unavailable/);assert.doesNotMatch(html,/href=|datetime="2026-01-01"/);
 assert.match(html,/Retrieval time is not a financial reporting period/);
 assert.doesNotMatch(c.researchCompanyContextHTML(p,'US.B',now),/<time/);
 p.origins.sector.cache_at=new Date(now+86400000).toISOString();
 assert.doesNotMatch(c.researchCompanyContextHTML(p,'US.A',now),/Sector · yfinance · retrieved/);
});

test('inspector opening, section focus and connected or reconstructed row return preserve page position',async()=>{
 const c=harness();c.scrollY=220;
 const control={focus(options){c.document.activeElement=this;if(!options?.preventScroll)c.scrollY=131;}};
 const inspector={classList:{add(){},remove(){}},setAttribute(){},removeAttribute(){},querySelector:()=>control};
 c.document.getElementById=id=>id==='research-inspector'?inspector:null;
 const row={code:'US.A',symbol:'A'};
 c.__researchInspectCode='US.A';c.__inspectTab='why';
 for(const options of [{focus:true},{focusControl:'tab'},{focusControl:'range'}]){
  await c.researchInspectRow(row,options);assert.equal(c.document.activeElement,control);assert.equal(c.scrollY,220);
 }
 const origin={...control,isConnected:true,getClientRects:()=>[{}]};c.__inspectOrigin=origin;
 c.researchCloseInspector();assert.equal(c.document.activeElement,origin);assert.equal(c.scrollY,220);
 const restored={...control,getAttribute:()=> 'Inspect A',getClientRects:()=>[{}]};
 c.document.querySelectorAll=()=>[restored];c.__inspectOrigin={isConnected:false};
 c.researchCloseInspector();assert.equal(c.document.activeElement,restored);assert.equal(c.scrollY,220);
 c.matchMedia=()=>({matches:false});c.__changePayload={rows:[{code:'US.A',symbol:'A',evidence:[]}],definition:{filters:[]}};
 c.researchChangeInspect('US.A',origin);assert.equal(c.document.activeElement,control);assert.equal(c.scrollY,220);
 c.researchCloseInspector();assert.equal(c.document.activeElement,origin);assert.equal(c.scrollY,220);
});

test('Explorer distinguishes Compare selection from region membership without repainting plot',()=>{
 const c=harness(),rows=[stock('A',20,1,{code:'US.A',pe_ttm:8}),stock('B',10,3,{code:'US.B',pe_ttm:8})];
 c.researchRows=()=>rows;c.__researchSelected=['US.A','US.B'];
 const st=c.researchExploreState();st.bounds={x:{min:7,max:9},y:{min:0,max:2}};
 const context={},button={};c.document.getElementById=id=>id==='explore-selection-context'?context:id==='explore-compare'?button:null;
 c.researchExploreMount=()=>{throw Error('Selection must not repaint plot');};c.researchPlot=()=>{throw Error('Selection must not redraw plot');};
 c.researchExploreSelectionMount();assert.match(context.textContent,/2 selected.*1 in this scope · 1 outside/);assert.equal(button.disabled,false);
 c.researchExploreSelect('US.A',false);
 // Normal mount includes the shared selection bar; exercise it with its existing element.
 const bar={};c.document.getElementById=id=>id==='research-selection'?bar:id==='explore-selection-context'?context:id==='explore-compare'?button:null;
 c.researchSelectionMount();assert.equal(button.disabled,true);assert.match(button.textContent,/\(1\)/);
 assert.deepEqual(Array.from(c.__researchSelected),['US.B']);assert.match(context.textContent,/0 in this scope · 1 outside/);
});

test('Explorer action and preview scopes precede plot and exports retain all eligible rows',()=>{
 const c=harness(),rows=[stock('A',20,1,{code:'US.A',pe_ttm:8}),stock('B',10,3,{code:'US.B',pe_ttm:8})];
 let html=c.researchExploreHTML(rows);assert.match(html,/Export plottable results/);assert.match(html,/All 2 eligible loaded rows/);
 assert.ok(html.indexOf('Explorer region actions')<html.indexOf('<canvas'));assert.ok(html.indexOf('Set region bounds')<html.indexOf('<canvas'));
 const st=c.researchExploreState();st.bounds={x:{min:7,max:9},y:{min:0,max:2}};st.preview=true;
 html=c.researchExploreHTML(rows);assert.match(html,/Export region results/);assert.match(html,/All 1 eligible loaded rows/);
 assert.ok(html.indexOf('Apply filters to screen')<html.indexOf('<canvas'));assert.match(html,/Saved definitions stay unchanged/);
 assert.match(html,/Missing\/nonfinite values are excluded/);assert.match(html,/currency is not inferred/);
 assert.match(html,/scrExport\('csv','explore'\)/);assert.match(html,/scrExport\('xls','explore'\)/);
});

test('opening numeric bounds dismisses export menu without modifying region or selection',()=>{
 const c=harness(),menu={open:true};c.document.querySelectorAll=()=>[menu];
 c.__researchSelected=['US.A'];const st=c.researchExploreState();st.bounds={x:{min:7},y:{min:-1}};
 const prior=JSON.stringify(st.bounds);c.researchExploreBoundsToggle({open:true});
 assert.equal(menu.open,false);assert.equal(st.formOpen,true);assert.equal(JSON.stringify(st.bounds),prior);assert.deepEqual(Array.from(c.__researchSelected),['US.A']);
});

test('settings shell renders coverage without waiting for catalog or runtime requests',async()=>{
 const c=harness();let requests=0;c.api=()=>{requests++;return new Promise(()=>{});};
 const result=await vm.runInContext('pages.settings()',c);
 assert.equal(requests,0);assert.match(result,/id="scr-sched"/);assert.match(result,/id="settings-model-panel"/);assert.match(result,/id="settings-runtime-panel"/);
 assert.match(result,/Data &amp; coverage/);assert.match(result,/Display timezone/);
});

test('unknown model pricing never renders negative costs or false free claims',()=>{
 const c=harness(),cat={models:[{id:'auto',in_per_m:-1,out_per_m:-1,est_per_run:-1,free:true},{id:'missing',in_per_m:null,out_per_m:'0',est_per_run:Infinity},{id:'free',in_per_m:0,out_per_m:0,est_per_run:0},{id:'paid',in_per_m:2,out_per_m:10,est_per_run:5}],count:4};
 const result=c.settingsModelPanelHTML(cat,{quick:'auto'});
 assert.match(result,/Unknown\/M in/);assert.match(result,/Unknown\/run/);assert.doesNotMatch(result,/\$-|\$null|\$Infinity/);
 const options=[...result.matchAll(/<option[^>]*>(.*?)<\/option>/g)].map(m=>m[1]);
 assert.doesNotMatch(options[0],/FREE/);assert.doesNotMatch(options[1],/FREE/);assert.match(options[2],/FREE/);assert.match(options[3],/\$2\/M in.*\$10\/M out.*\$5\/run/);
});

test('catalog failure retains runtime and coverage targets and offers recovery',async()=>{
 const c=harness(),targets=new Map(['settings-model-panel','settings-runtime-panel','scr-sched'].map(id=>[id,{id,innerHTML:id}]));
 c.document.getElementById=id=>targets.get(id);vm.runInContext("state.page='settings'; __pageGen=9",c);
 c.api=async path=>{if(path==='/api/models')throw Error('outage');return {models:{quick:'active/q',deep:'active/d'},runtime:{stub:true}};};
 await Promise.all([c.loadSettingsModels(9),c.loadSettingsRuntime(9)]);
 assert.match(targets.get('settings-model-panel').innerHTML,/Model catalog unavailable/);assert.match(targets.get('settings-model-panel').innerHTML,/refreshModels\(\)/);
 assert.match(targets.get('settings-runtime-panel').innerHTML,/id="s-stub"[^>]*checked/);assert.equal(targets.get('scr-sched').innerHTML,'scr-sched');
 assert.equal(vm.runInContext('state.models.quick',c),'active/q');
});

test('obsolete settings responses cannot overwrite a newer render or runtime state',async()=>{
 const c=harness(),old={id:'settings-model-panel',innerHTML:'old'},replacement={id:'settings-model-panel',innerHTML:'new'};
 let current=old,resolve;c.document.getElementById=()=>current;vm.runInContext("state.page='settings'; __pageGen=3",c);
 c.api=()=>new Promise(r=>resolve=r);const pending=c.loadSettingsModels(3);current=replacement;vm.runInContext('__pageGen=4',c);
 resolve({models:[{id:'obsolete',in_per_m:1,out_per_m:2,est_per_run:3}],count:1});await pending;
 assert.equal(old.innerHTML,'old');assert.equal(replacement.innerHTML,'new');
 const runtime={id:'settings-runtime-panel',innerHTML:'current'};current=runtime;const request=c.loadSettingsRuntime(4);
 vm.runInContext("state.page='home'; __pageGen=5",c);resolve({models:{quick:'obsolete'},runtime:{stub:false}});await request;
 assert.equal(runtime.innerHTML,'current');assert.equal(vm.runInContext('state.models',c),null);
});

test('catalog recovery retains active model IDs absent from the refreshed catalog',()=>{
 const c=harness(),cat={models:[{id:'auto',in_per_m:-1,out_per_m:-1,est_per_run:-1}],count:1};
 const result=c.settingsModelPanelHTML(cat,{quick:'current/quick',deep:'current/deep'});
 assert.match(result,/<option value="current\/quick" selected>current\/quick — current model · pricing unavailable/);
 assert.match(result,/<option value="current\/deep" selected>current\/deep — current model · pricing unavailable/);
 assert.doesNotMatch(result,/<option value="auto" selected/);
});

test('Settings, Compare and anonymous shortlist deep links preserve route through rendering',()=>{
 const c=harness();for(const page of ['settings','compare']){c.researchPageRoute(page,'home');assert.equal(c.location.hash,'#/'+page);assert.equal(c.stkRoute().page,page);}
 const id='00000000-0000-4000-8000-000000000003';c.location.hash='#/shortlists/'+id;
 assert.equal(c.stkRoute().list,id);c.__researchRouteList=id;c.researchPageRoute('shortlists','home');assert.equal(c.location.hash,'#/shortlists/'+id);
 c.location.hash='#/stock/%';assert.equal(c.stkRoute(),null);
 c.location.hash='';c.location.pathname='/stock/%';assert.equal(c.stkRoute(),null);
});

test('owner-bound shortlist navigation retains filters and paging without exposing them in URL',()=>{
 const c=harness(),id='00000000-0000-4000-8000-000000000003';const storage=new Map();c.sessionStorage={getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
 c.__researchSession={user:{id:'owner-a'}};c.__researchListID=id;c.__researchListOffset=100;c.__researchListSearch='private company search';c.__researchListStatus='in_review';c.__researchListsArchived=true;
 vm.runInContext("state.page='shortlists'",c);c.researchListNavigationPersist();assert.equal(c.location.hash,'#/shortlists/'+id);assert.doesNotMatch(c.location.hash,/private|review/);
 c.__researchListID=null;c.__researchListOffset=0;c.__researchListSearch='';c.__researchListStatus='all';c.researchListNavigationRestore();
 assert.equal(c.__researchListID,id);assert.equal(c.__researchListOffset,100);assert.equal(c.__researchListSearch,'private company search');assert.equal(c.__researchListStatus,'in_review');assert.equal(c.__researchListsArchived,true);
 c.__researchSession={user:{id:'owner-b'}};c.__researchListID=null;c.__researchListSearch='';c.__researchListOffset=0;c.researchListNavigationRestore();assert.equal(c.__researchListID,null);assert.equal(c.__researchListSearch,'');
});

test('public origin restores screening state and selection while private origin requires validated matching account',async()=>{
 const c=harness(),storage=new Map();c.sessionStorage={getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
 const rows=[{code:'US.A',symbol:'A'},{code:'HK.00700',symbol:'00700'}];
 c.__researchContext={state:{market:'HK',sort:'market_cap',page:2},rows,selected:['HK.00700'],scroll:150,tableScroll:30};c.researchOriginPersist();c.__researchContext=null;await c.researchOriginRestore();
 assert.equal(c.__researchContext.state.page,2);assert.deepEqual(Array.from(c.__researchContext.selected),['HK.00700']);assert.equal(c.__researchContext.scroll,150);
 c.__researchSession={user:{id:'owner-a'}};c.__researchContext={kind:'shortlists',listID:'00000000-0000-4000-8000-000000000003',offset:100,q:'A',review_status:'reviewed',rows,selected:[],scroll:20};c.researchOriginPersist();c.__researchContext=null;
 c.__researchAccountReady=Promise.resolve();c.__researchSession={user:{id:'owner-b'}};await c.researchOriginRestore();assert.equal(c.__researchContext,null);
 c.__researchSession={user:{id:'owner-a'}};await c.researchOriginRestore();assert.equal(c.__researchContext.kind,'shortlists');assert.equal(c.__researchContext.offset,100);
});

test('invalid persisted origins fail closed without replacing current context',async()=>{
 const c=harness(),valid={state:{market:'US'},rows:[{code:'US.A'}],selected:['US.A'],scroll:0};
 for(const context of [{...valid,kind:'unknown'},{...valid,state:[]},{...valid,selected:['US.A','US.A']},{...valid,rows:[{code:'US.A'},{code:'US.A'}]},{...valid,scroll:-1}]){
  c.sessionStorage.getItem=()=>JSON.stringify({version:1,owner:null,context});c.__researchContext=null;await c.researchOriginRestore();assert.equal(c.__researchContext,null);
 }
});

test('private navigation and research origin are cleared on sign-out',()=>{
 const c=harness(),storage=new Map([['researchListNavigationV1','private'],['researchOriginV1',JSON.stringify({owner:'owner-a'})]]);
 c.sessionStorage={getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};c.__researchSession={user:{id:'owner-a'}};
 c.researchPrivateClear();assert.equal(storage.has('researchListNavigationV1'),false);assert.equal(storage.has('researchOriginV1'),false);
});

test('normalizing an existing screener deep link does not push another browser history entry',()=>{
 const c=harness({},'#/screener');let pushed=0;c.history.pushState=()=>pushed++;
 c.researchPageRoute('home','settings');assert.equal(pushed,0);assert.match(c.location.hash,/^#\/screener\?/);
 c.location.hash='#/settings';c.researchPageRoute('home','settings');assert.equal(pushed,1);
});

test('navigation helpers are loaded through versioned browser assets',()=>{
 assert.match(html,/research-workspace\.js\?v=20261004-desk-observations1/);assert.match(html,/research-account\.js\?v=20261003-desk-mvp1/);
});


test('visible Screen values distinguish original provider rules from display and custom filters',()=>{
 const c=harness(),a={field:'pe_ttm',min:20},b={field:'volume',min:100,days:30},custom={field:'pe_ttm',max:30};
 c.__scrPresets=[{key:'p',filters:[a,b]}];Object.assign(c.__scr,{activePreset:'p',filters:[a,b,custom]});
 const row={code:'US.A',pe_ttm:8,volume:9,criterion_evidence:[{code:'US.A',criterion:a,value:25},{code:'US.A',criterion:b,value:120}]};
 const pe=c.researchScreenValuesHTML(row,'pe_ttm');assert.match(pe,/Screen: 25/);assert.equal((pe.match(/class="screen-value"/g)||[]).length,1);assert.doesNotMatch(pe,/Screen: 8/);
 assert.match(c.researchScreenValuesHTML(row,'volume'),/Screen · 30-day: 120 shares/);
 row.criterion_evidence[0].code='US.B';assert.match(c.researchScreenValuesHTML(row,'pe_ttm'),/Screen: Unavailable/);
 c.__scr.activePreset=null;assert.equal(c.researchScreenValuesHTML(row,'pe_ttm'),'');
});

test('screen-value labels fail closed for ambiguous observations and preserve repeated windows',()=>{
 const c=harness(),a={field:'volume',days:10,min:10},b={field:'volume',days:30,min:100};c.__scrPresets=[{key:'p',filters:[a,b]}];Object.assign(c.__scr,{activePreset:'p',filters:[a,b]});
 const row={code:'US.A',criterion_evidence:[{code:'US.A',criterion:a,value:0},{code:'US.A',criterion:b,value:150}]};
 assert.match(c.researchScreenValuesHTML(row,'volume'),/Screen · 10-day: 0 shares/);assert.match(c.researchScreenValuesHTML(row,'volume'),/Screen · 30-day: 150 shares/);
 row.criterion_evidence.push({...row.criterion_evidence[0]});assert.match(c.researchScreenValuesHTML(row,'volume'),/Screen · 10-day: Unavailable/);
 assert.match(c.researchProviderScopeHTML({rows:[]},[],c.__scr),/Sort and added filters use display values/);
 assert.match(html,/researchScreenValuesHTML\(r,k,st\)/);assert.match(helper,/researchScreenValuesHTML\(r,'pe_ttm',st\)/);
});


test('typed factors agree across plots, region handoff and filters without coercing invalid values',()=>{
 const c=harness(),invalid=[true,false,[],[8],{},'8','',Infinity,NaN];
 const rows=invalid.map((pe_ttm,i)=>({symbol:'bad'+i,code:'US.BAD'+i,pe_ttm,pct:0})).concat([{symbol:'valid',code:'US.VALID',pe_ttm:8,pct:0}]);
 const st={x:'pe_ttm',y:'pct',bounds:{x:{min:0,max:10},y:{min:0,max:0}},xs:'linear',ys:'linear'};
 assert.deepEqual(Array.from(c.researchExploreSelected(rows,st),r=>r.code),['US.VALID']);
 assert.deepEqual(Array.from(c.scrFieldPass(rows,c.researchExploreCriteria(st)),r=>r.code),['US.VALID']);
 for(const bound of [true,'8',{},[],Infinity,NaN])assert.equal(c.scrFieldPass([{pe_ttm:8}],[{field:'pe_ttm',max:bound}]).length,0);
 assert.equal(c.scrFieldPass([{new_low:true},{new_low:false}],[{field:'new_low',min:1}]).length,1);
});

test('typed sorts keep invalid observations last and retain textual and Boolean ordering',()=>{
 const c=harness(),rows=[{symbol:'badBool',pe_ttm:true},{symbol:'badString',pe_ttm:'8'},{symbol:'badInfinite',pe_ttm:Infinity},{symbol:'A',pe_ttm:-1},{symbol:'B',pe_ttm:0}];
 c.__scr.sort='pe_ttm';for(const dir of [1,2]){c.__scr.dir=dir;const result=c.scrSortRows(rows);assert.equal(result[0].symbol,dir===1?'A':'B');assert.deepEqual(Array.from(result.slice(2),r=>r.symbol),['badBool','badString','badInfinite']);}
 c.__scr.dir=1;c.__scr.sort='symbol';assert.deepEqual(Array.from(c.scrSortRows([{symbol:'Z'},{symbol:{}},{symbol:'a'}]),r=>r.symbol),['a','Z',{}]);
 c.__scr.sort='new_high';assert.deepEqual(Array.from(c.scrSortRows([{new_high:true},{new_high:false},{new_high:2}]),r=>r.new_high),[false,true,2]);
});


test('actual preset table rendering does not invent numeric values or Boolean flags',async()=>{
 const c=harness(),rows=[stock('BAD',10,0,{code:'US.BAD',pe_ttm:true,volume:[8],pct:'2',new_high:2}),stock('ZERO',9,0,{code:'US.ZERO',pe_ttm:0,volume:0,pct:0,new_high:false})];
 Object.assign(c.__scr,{activePreset:'p',market:'US',cols:['symbol','pe_ttm','volume','pct','new_high']});
 c.__presetCache={'p|US':{ts:Date.now(),retained:true,payload:{available:true,rows,filters:[],name:'Typed',retrieved_at:'2026-10-02T00:00:00Z'}}};
 c.__panelCache={market:'US',rail:{presets:[{key:'p',name:'Typed',filters:[]}]}};c.scrStreamPanels=()=>{};c.api=()=>assert.fail('unexpected provider fetch');
 const result=await vm.runInContext('pages.home()',c);
 for(const field of ['pe_ttm','volume','pct','new_high'])assert.match(result,new RegExp('data-field="'+field+'"><span[^>]*>Unavailable</span>'));
 assert.match(result,/data-field="new_high"><span[^>]*>No<\/span>/);
 assert.match(result,/data-field="volume"><span[^>]*>0\.00M<\/span>/);
});

test('export cells preserve typed numbers, invalid diagnostics and structured nonfinite evidence',()=>{
 const c=harness(),raw={code:'US.BAD',price:true,pe_ttm:'8',volume:Infinity,new_high:2,field_observations:{price:{value:NaN}}};
 const row=c.researchExportRow(raw,['price','pe_ttm','volume','new_high']);
 for(const field of ['price','pe_ttm','volume','new_high'])assert.equal(row[field],'Unavailable');
 assert.equal(row.export_value_issues.length,4);assert.equal(raw.price,true);assert.equal(raw.volume,Infinity);
 const evidence=JSON.parse(c.researchExportJSON(row));assert.equal(evidence.field_observations.price.value.export_unavailable,'nonfinite_number');
 assert.equal(evidence.export_value_issues[2].source_value.source_value,'Infinity');
 assert.match(c.researchXMLCell(0),/ss:Type="Number">0</);assert.match(c.researchXMLCell(-2),/ss:Type="Number">-2</);
 assert.match(c.researchXMLCell(Infinity),/ss:Type="String".*nonfinite_number/);assert.match(c.researchXMLCell('a\u0001<&'),/a\\u0001&lt;&amp;/);
 assert.equal(c.researchCSVCell('  =1+1'),"'  =1+1");assert.equal(c.researchCSVCell(-2),'-2');
 assert.match(c.researchCSVCell('\r=1+1'),/^"'\r/);
});

test('download blobs retain scope, typed Excel cells and invalid-source diagnostics',async()=>{
 const c=harness(),rows=[stock('BAD',10,1,{code:'US.BAD',price:true,pe_ttm:'8',volume:Infinity,field_observations:{price:{value:NaN}}}),stock('ZERO',9,0,{code:'US.ZERO',price:0,pe_ttm:0,volume:0})];
 c.scrClientRows=()=>rows;c.__scr.cols=['symbol','price','pe_ttm','volume'];let blob;
 c.Blob=Blob;c.URL={createObjectURL:b=>{blob=b;return 'blob:test';},revokeObjectURL(){}};c.document.createElement=()=>({click(){},remove(){}});
 c.scrExport('csv','loaded');const csv=await blob.text();assert.match(csv,/export_value_issues/);assert.match(csv,/1,BAD,Unavailable,Unavailable,Unavailable/);assert.match(csv,/2,ZERO,0,0,0/);assert.match(csv,/nonfinite_number/);
 c.scrExport('xls','loaded');const xml=await blob.text();assert.match(xml,/ss:Type="Number">0</);assert.match(xml,/ss:Type="String">Unavailable</);assert.doesNotMatch(xml,/ss:Type="Number">(?:true|Infinity|NaN)</);
 assert.equal(rows[0].price,true);assert.equal(rows[0].volume,Infinity);
 const shortlist=c.researchListCSV({name:'Quality',revision:4},[{code:'US.BAD',quote:rows[0],note:'  =1+1'},{code:'US.ZERO',quote:rows[1]}]);
 assert.match(shortlist,/export_value_issues/);assert.match(shortlist,/Unavailable/);assert.match(shortlist,/'  =1\+1/);assert.match(shortlist,/invalid_numeric/);
});

test('pair review presentation distinguishes private state, storage failure and anonymous access',()=>{
 const c=harness(),d={previous_id:'1',current_id:'2',owner_id:'owner',review_scope:'private_capture_pair'},r={code:'US.A',review:{revision:1,note:'<private>',review_status:'in_review'}};
 assert.match(c.researchPairToolsHTML(d,{}),/Sign in to review/);c.__researchSession={user:{id:'owner'}};
 assert.match(c.researchPairToolsHTML(d,{review_status:'unreviewed'}),/Next unreviewed/);assert.match(c.researchPairToolsHTML({...d,review_error:'storage <failed>'},{}),/storage &lt;failed&gt;/);
 assert.match(c.researchPairFormHTML(d,r),/&lt;private&gt;/);assert.match(c.researchPairFormHTML(d,r),/Save pair review/);
 const key=c.__researchPairDraftKey,status={};c.researchPairDraftUpdate({elements:{note:{value:'unsaved'},review_status:{value:'reviewed'}},querySelector:()=>status});assert.match(status.textContent,/Unsaved changes/);
 assert.match(c.researchPairFormHTML(d,r),/unsaved/);assert.equal(c.__researchPairDraftKey,key);
 assert.doesNotMatch(c.researchPairFormHTML({...d,current_id:'3'},r),/unsaved/);
});

test('pair review save conflicts retain drafts and late success retains newer edits',async()=>{
 const c=harness();c.__researchSession={user:{id:'owner'}};const pair={previous_id:'1',current_id:'2',definition:{market:'US'},owner_id:'owner',review_scope:'private_capture_pair',rows:[{code:'US.A',review:{revision:1,note:'saved',review_status:'unreviewed'}}]};c.__changePayload=pair;
 c.researchPairFormHTML(pair,pair.rows[0]);const key=c.__researchPairDraftKey,button={isConnected:true},status={};const form={isConnected:true,elements:{note:{value:'draft'},review_status:{value:'in_review'}},querySelector:s=>s==='button[type=submit]'?button:status};
 c.researchPrivateAPI=async()=>{throw c.researchAuthError('conflict',409);};await c.researchPairSave(form);
 assert.equal(c.__researchPairDrafts[key].note,'draft');assert.match(status.textContent,/Your draft is kept/);
 let complete;c.researchPrivateAPI=()=>new Promise(resolve=>complete=resolve);const saving=c.researchPairSave(form);
 form.elements.note.value='newer draft';c.researchPairDraftUpdate(form);complete({review:{revision:2,note:'draft',review_status:'in_review'}});await saving;
 assert.equal(c.__researchPairDrafts[key].note,'newer draft');assert.equal(c.__researchPairDrafts[key].revision,2);assert.match(status.textContent,/newer edits are still unsaved/);
});

test('sign-out clears pair notes and rejects late review responses',async()=>{
 const c=harness();c.__researchSession={user:{id:'owner'}};c.__researchPairDrafts={secret:{note:'private'}};c.__changePayload={review_scope:'private_capture_pair',rows:[{review:{note:'private'}}]};
 c.researchPrivateClear();assert.equal(Object.keys(c.__researchPairDrafts).length,0);assert.equal(c.__changePayload,null);
});

test('pair review filters retain string states and reset pagination',()=>{
 const c=harness();c.researchLoadChanges=()=>{};c.researchChangeState().offset=500;
 c.researchChangeSet('review_status','reviewed');assert.equal(c.researchChangeState().review_status,'reviewed');assert.equal(c.researchChangeState().offset,0);
 c.researchChangeSet('review_status','malformed');assert.equal(c.researchChangeState().review_status,'reviewed');
});

test('review-filtered comparison export preserves private scope and rejects changing revisions',async()=>{
 const c=harness(),pair={comparable:true,previous_id:'1',current_id:'2',definition:{market:'US'},review_scope:'private_capture_pair',owner_id:'owner',rows:[]};c.__changePayload=pair;c.__researchSession={user:{id:'owner'}};c.researchChangeState().review_status='reviewed';
 let blob,clicks=0,warning;c.alert=m=>warning=m;c.Blob=Blob;c.URL={createObjectURL:b=>{blob=b;return 'blob:test';},revokeObjectURL(){}};c.document.createElement=()=>({click(){clicks++;},remove(){}});
 c.researchPrivateAPI=async path=>{assert.equal(new URLSearchParams(path.split('?')[1]).get('review_status'),'reviewed');return {...pair,matched:1,review_revision_hash:'hash',rows:[{code:'US.A',review:{revision:2,review_status:'reviewed',note:'  =1+1'}}]};};
 await c.researchChangesExport();assert.equal(clicks,1);assert.match(await blob.text(),/review_revision_hash,review_revision,review_status,private_note/);assert.match(await blob.text(),/private_capture_pair,hash,2,reviewed,'  =1\+1/);
 let pages=0;c.researchPrivateAPI=async()=>({...pair,matched:501,review_revision_hash:++pages===1?'first':'changed',rows:Array.from({length:pages===1?500:1},(_,i)=>({code:'US.A'+(pages===1?i:500)}))});
 await c.researchChangesExport();assert.equal(clicks,1);assert.match(warning,/Review revisions changed/);
});

test('reload saved pair review adopts the current revision without replacing the draft',async()=>{
 const c=harness();c.__researchSession={user:{id:'owner'}};const pair={previous_id:'1',current_id:'2',definition:{market:'US'},owner_id:'owner',review_scope:'private_capture_pair',rows:[{code:'US.A',review:{revision:1,note:'saved',review_status:'unreviewed'}}]};c.__changePayload=pair;c.researchPairFormHTML(pair,pair.rows[0]);const key=c.__researchPairDraftKey,status={};
 const form={isConnected:true,elements:{note:{value:'my draft'},review_status:{value:'in_review'}},querySelector:()=>status};let rendered;
 c.researchChangeInspect=code=>rendered=code;c.researchPrivateAPI=async path=>{const query=new URLSearchParams(path.split('?')[1]);assert.equal(query.get('code'),'US.A');assert.equal(query.get('review_status'),'all');return {rows:[{code:'US.A',review:{revision:3,note:'other edit',review_status:'reviewed'}}]};};
 await c.researchPairReload(form);const draft=c.__researchPairDrafts[key];assert.equal(draft.note,'my draft');assert.equal(draft.review_status,'in_review');assert.equal(draft.revision,3);assert.equal(draft.latest.note,'other edit');assert.equal(rendered,'US.A');
});

test('Changes selections persist across pages but clear on query, pair, revision or owner changes',()=>{
 const c=harness(),pair={comparable:true,definition:{market:'US'},previous_id:'before',current_id:'after',review_scope:'private_capture_pair',review_revision_hash:'h1',rows:[{code:'US.A',symbol:'A'}]};
 c.__researchSession={user:{id:'owner'}};c.__changePayload=pair;c.researchChangeSelectPage(true);
 c.researchChangeState().offset=500;pair.rows=[{code:'US.B',symbol:'B'}];c.researchChangeSelectPage(true);
 assert.deepEqual(Array.from(c.researchChangeSelection().rows,r=>r.code),['US.A','US.B']);c.researchChangeSelectPage(false);
 assert.deepEqual(Array.from(c.researchChangeSelection().rows,r=>r.code),['US.A']);
 for(const mutate of [()=>c.researchChangeState().q='B',()=>pair.current_id='later',()=>pair.review_revision_hash='h2',()=>c.__researchSession.user.id='other']){
  c.researchChangeSelectPage(true);assert.ok(c.researchChangeSelection().rows.length);mutate();assert.equal(c.researchChangeSelection().rows.length,0);assert.match(c.researchChangeSelection().message,/cleared/);
 }
});

test('selected comparison downloads retain server ordering and reject stale revision or missing identities',async()=>{
 const c=harness(),pair={comparable:true,definition:{market:'US'},previous_id:'1',current_id:'2',review_scope:'private_capture_pair',review_revision_hash:'original',rows:[{code:'US.A'},{code:'US.C'}]};
 c.__changePayload=pair;c.__researchSession={user:{id:'owner'}};c.researchChangeSelectPage(true);let blob,warning,clicks=0;
 c.alert=m=>warning=m;c.Blob=Blob;c.URL={createObjectURL:b=>{blob=b;return 'blob:test';},revokeObjectURL(){}};c.document.createElement=()=>({click(){clicks++;},remove(){}});
 let hash='original',rows=[{code:'US.C'},{code:'US.B'},{code:'US.A'}];c.researchPrivateAPI=async()=>({...pair,review_revision_hash:hash,matched:rows.length,rows});
 await c.researchChangesExport('selected');const csv=await blob.text();assert.equal(clicks,1);assert.ok(csv.indexOf('US.C')<csv.indexOf('US.A'));assert.doesNotMatch(csv,/US.B/);assert.match(csv,/selected/);
 hash='updated';await c.researchChangesExport('selected');assert.equal(clicks,1);assert.match(warning,/changed since selection/);
 hash='original';rows=[{code:'US.A'}];await c.researchChangesExport('selected');assert.equal(clicks,1);assert.match(warning,/no longer in this review/);
});

test('Changes bulk retries only unconfirmed additions and rejects account changes or loading',async()=>{
 const c=harness(),pair={comparable:true,definition:{market:'US'},previous_id:'1',current_id:'2',rows:[{code:'US.A'},{code:'US.B'},{code:'US.C'}]};
 c.__changePayload=pair;c.__researchSession={user:{id:'owner'}};c.researchChangeSelectPage(true);
 const bulk={owner:'owner',key:c.researchChangeSelection().key,codes:['US.A','US.B','US.C'],done:[],failures:[]};c.__researchChangeBulk=bulk;
 const list={value:'00000000-0000-4000-8000-000000000003'},button={isConnected:true},status={},failures={};
 c.__researchDialog={querySelector:s=>s==='select'?list:s==='button.primary'?button:s==='[role=status]'?status:failures};
 let retry=false,calls=[];c.researchPrivateAPI=async(path,opts)=>{const body=JSON.parse(opts.body);assert.deepEqual(Object.keys(body),['code']);calls.push(body.code);if(body.code==='US.B' && !retry)throw Error('temporary outage');return {item:{code:body.code}};};
 await c.researchChangeBulkAdd();assert.deepEqual(Array.from(bulk.done),['US.A','US.C']);assert.match(status.textContent,/2 of 3 additions confirmed/);assert.equal(bulk.failures.length,1);
 retry=true;await c.researchChangeBulkAdd();assert.deepEqual(calls,['US.A','US.B','US.C','US.B']);assert.equal(bulk.done.length,3);
 c.__researchSession.user.id='other';await c.researchChangeBulkAdd();assert.equal(calls.length,4);assert.match(status.textContent,/account changed/);
 c.__changeLoading=true;await c.researchChangeBulkAdd();assert.equal(calls.length,4);assert.match(status.textContent,/finish loading/);
});

test('Changes origin rejects malformed private selection and restores only the matching owner',async()=>{
 const c=harness();c.__researchSession={user:{id:'owner'}};c.__researchAccountReady=Promise.resolve();
 const valid={kind:'changes',private:true,state:{presentation:'changes'},rows:[{code:'US.A'}],selected:['US.A'],scroll:0,changeState:{key:'query',status:'all',q:'',direction:2,offset:500,limit:500},changeSelection:{key:'selection',rows:[{code:'US.A'}]}};
 let context=valid;c.sessionStorage.getItem=()=>JSON.stringify({version:1,owner:'owner',context});await c.researchOriginRestore();assert.equal(c.__researchContext.changeState.offset,500);
 for(const bad of [{...valid,state:null},{...valid,private:'true'},{...valid,changeSelection:{key:'selection',rows:[{code:'US.A'},{code:'US.A'}]}},{...valid,changeState:{...valid.changeState,offset:-1}}]){context=bad;c.__researchContext=null;await c.researchOriginRestore();assert.equal(c.__researchContext,null);}
 context=valid;c.__researchSession.user.id='other';await c.researchOriginRestore();assert.equal(c.__researchContext,null);
});

test('closing Changes bulk dialog stops later batches and mismatched confirmations remain retryable',async()=>{
 const c=harness(),codes=['US.A','US.B','US.C','US.D','US.E'];c.__researchSession={user:{id:'owner'}};c.__changePayload={comparable:true,definition:{market:'US'},previous_id:'1',current_id:'2',rows:codes.map(code=>({code}))};c.researchChangeSelectPage(true);
 const bulk={owner:'owner',key:c.researchChangeSelection().key,codes,done:[],failures:[]};c.__researchChangeBulk=bulk;
 const status={},button={isConnected:false},list={value:'00000000-0000-4000-8000-000000000003'},dialog={querySelector:s=>s==='select'?list:s==='button.primary'?button:s==='[role=status]'?status:{}};c.__researchDialog=dialog;
 const pending=[],calls=[];c.researchPrivateAPI=(path,opts)=>new Promise(resolve=>{calls.push(JSON.parse(opts.body).code);pending.push(resolve);});
 const operation=c.researchChangeBulkAdd();assert.deepEqual(calls,codes.slice(0,4));c.__researchDialog=null;
 pending.forEach((resolve,i)=>resolve({item:{code:i===1?'US.WRONG':codes[i]}}));await operation;
 assert.deepEqual(calls,codes.slice(0,4));assert.deepEqual(Array.from(bulk.done),['US.A','US.C','US.D']);assert.equal(bulk.failures[0].code,'US.B');assert.equal(bulk.running,false);
 c.__researchDialog=dialog;c.researchPrivateAPI=async(path,opts)=>{const code=JSON.parse(opts.body).code;calls.push(code);return {item:{code}};};await c.researchChangeBulkAdd();assert.deepEqual(calls.slice(4),['US.B','US.E']);assert.equal(bulk.done.length,5);
});

test('Explorer sector context qualifies source and freshness without provider-list substitution',()=>{
 const c=harness(),now=Date.now(),fresh=new Date(now-1000).toISOString(),row={code:'US.A',sector:' Technology ',plate:'Vendor theme',display_field_sources:{sector:{source:'yfinance',cache_at:fresh}}};
 assert.equal(c.researchExploreSector(row,now),'Technology');assert.equal(c.researchExploreSector({...row,sector:null},now),'Unknown');
 for(const origin of [{source:'moomoo',cache_at:fresh},{source:'yfinance',cache_at:'invalid'},{source:'yfinance',cache_at:new Date(now+1000).toISOString()},{source:'yfinance',cache_at:new Date(now-8*86400000).toISOString()}])assert.equal(c.researchExploreSector({...row,display_field_sources:{sector:origin}},now),'Unknown');
 const rows=[row,{code:'US.B',plate:'Technology'}],encoding=c.researchExploreEncoding(rows,{plotted:[row]},now);
 assert.equal(encoding.sectors.reduce((n,g)=>n+g.loaded,0),2);assert.equal(encoding.sectors.reduce((n,g)=>n+g.plotted,0),1);assert.equal(encoding.sectors.find(g=>g.sector==='Unknown').loaded,1);
 assert.equal(c.researchExploreSectorColor('Technology'),c.researchExploreSectorColor('Technology'));assert.match(c.researchExploreEncodingHTML(rows,{plotted:[row]},{}),/1\/2 loaded classified/);
});

test('Explorer cap encoding requires complete identity-attributed single-currency positive caps',()=>{
 const c=harness(),row=(code,cap,currency)=>({code,market_cap:cap,field_observations:{market_cap:{code,field:'market_cap',unit:'currency',value:cap,currency}}}),a=row('US.A',10,'USD'),b=row('US.B',20,'USD');
 const encoding=rows=>c.researchExploreEncoding(rows,{plotted:rows});assert.equal(encoding([a,b]).capReady,true);assert.equal(encoding([a,b]).currency,'USD');assert.equal(encoding([a,b]).maxCap,20);
 for(const invalid of [row('HK.B',20,'HKD'),{...b,field_observations:{}},row('US.B',0,'USD'),row('US.B',-1,'USD'),row('US.B',true,'USD'),{...b,field_observations:{market_cap:{...b.field_observations.market_cap,code:'US.OTHER'}}}])assert.equal(encoding([a,invalid]).capReady,false);
 assert.equal(encoding([]).capReady,false);assert.match(c.researchExploreEncodingHTML([a,{...b,field_observations:{}}],{plotted:[a,{...b,field_observations:{}}]},{}),/value="cap"[^>]*disabled/);
});

test('market-cap Explorer axis, region filters and saved definition retain explicit currency membership',async()=>{
 const c=harness(),row=(code,currency)=>({code,symbol:code.slice(3),market_cap:10,pct:0,field_observations:{market_cap:{code,field:'market_cap',unit:'currency',value:10,currency}}}),rows=[row('US.A','USD'),row('US.B','HKD'),row('US.C',null)];
 const st={x:'market_cap',y:'pct',xs:'linear',ys:'linear',capCurrency:'USD',bounds:{x:{min:1,max:20},y:{min:0,max:0}}};
 const model=c.researchExploreModel(rows,st);assert.deepEqual(Array.from(model.plotted,r=>r.code),['US.A']);assert.equal(model.currencyExcluded,2);
 const rules=c.researchExploreCriteria(st);assert.equal(rules[0].currency,'USD');assert.deepEqual(Array.from(c.scrFieldPass(rows,rules),r=>r.code),['US.A']);assert.throws(()=>c.researchExploreCriteria({...st,capCurrency:''}),/Choose an attributed/);
 assert.equal(c.researchExploreModel(rows,{...st,capCurrency:''}).plotted.length,0);
 c.__scr.filters=JSON.parse(JSON.stringify(rules));const saved={...JSON.parse(JSON.stringify(c.scrCurrentScreenerState())),id:'currency',name:'Currency'};c.scrResetAll();c.__savedScreeners=[saved];await c.scrApplySaved('currency');assert.equal(c.__scr.filters[0].currency,'USD');assert.deepEqual(Array.from(c.scrFieldPass(rows,c.__scr.filters),r=>r.code),['US.A']);
});

test('market-cap region CSV records chosen currency scope and excludes other or unknown currencies',async()=>{
 const c=harness(),rows=['USD','HKD',null].map((currency,i)=>({code:'US.A'+i,symbol:'A'+i,market_cap:10,pct:0,field_observations:{market_cap:{code:'US.A'+i,field:'market_cap',unit:'currency',value:10,currency}}}));
 Object.assign(c.researchExploreState(),{x:'market_cap',y:'pct',capCurrency:'USD',bounds:{x:{min:1,max:20},y:{min:0,max:0}}});c.scrClientRows=()=>rows;let blob;c.Blob=Blob;c.URL={createObjectURL:b=>{blob=b;return 'blob:test';},revokeObjectURL(){}};c.document.createElement=()=>({click(){},remove(){}});c.scrExport('csv','explore');
 const csv=await blob.text();assert.match(csv,/explore_context/);assert.match(csv,/cap_currency/);assert.match(csv,/USD/);assert.match(csv,/US.A0/);assert.doesNotMatch(csv,/US.A1|US.A2|HKD/);
});

test('client CSV preserves same-response provider context without inventing factor periods',async()=>{
 const c=harness(),context={code:'HK.00700',fields:{currency:'HKD',financialCurrency:'CNY'},scope:'calendar not metric period'},rows=[{code:'HK.00700',symbol:'00700',forward_pe:12,supplemental_provider_context:context}];
 c.scrClientRows=()=>rows;c.__scr.cols=['symbol','forward_pe'];let blob;c.Blob=Blob;c.URL={createObjectURL:b=>{blob=b;return 'blob:test';},revokeObjectURL(){}};c.document.createElement=()=>({click(){},remove(){}});c.scrExport('csv','loaded');const csv=await blob.text();
 assert.match(csv,/supplemental_provider_context/);assert.match(csv,/HKD/);assert.match(csv,/CNY/);assert.match(csv,/calendar not metric period/);assert.equal(rows[0].forward_pe,12);assert.equal(rows[0].period,undefined);
});


test('private capture history refreshes absent schedules and fences late source responses',async()=>{
 const c=harness();c.__researchSession={user:{id:'owner'}};const st=c.researchChangeState();st.source='private';c.__changeGen=2;
 let calls=0;c.researchPrivateAPI=async()=>{calls++;return {schedules:[]};};
 assert.equal((await c.researchLoadPrivateChanges(st,2)).comparable,false);
 await c.researchLoadPrivateChanges(st,2);assert.equal(calls,2);
 let release;c.researchPrivateAPI=()=>new Promise(r=>release=r);
 const pending=c.researchLoadPrivateChanges(st,2);c.researchChangeSource('manual');release({schedules:[{id:'late'}]});
 await assert.rejects(pending,/Comparison changed/);assert.equal(c.researchChangeState().source,'manual');assert.equal(c.__researchCaptureSchedule.schedule,null);
});

test('capture source switches clear obsolete rows/actions immediately and retain scoped drafts',()=>{
 const c=harness();c.__researchSession={user:{id:'owner'}};const results={innerHTML:'shared note and shared rows'},notice={innerHTML:''};
 c.document.getElementById=id=>id==='research-change-results'?results:id==='research-change-load-status'?notice:null;
 const st=c.researchChangeState();Object.assign(st,{review_status:'scope_conflict',previous_id:'before',current_id:'after',offset:100,history_offset:100});
 c.__changePayload={rows:[{code:'US.A'}]};c.__researchChangeSelection={codes:['US.A']};c.__researchPairDraftKey='original';c.__researchPairDrafts={original:{note:'retained private draft'}};
 let cancelled;c.__changeSearchTimer=42;c.clearTimeout=value=>cancelled=value;
 c.researchChangeSource('private');
 assert.equal(cancelled,42);assert.equal(st.review_status,'all');assert.equal(st.previous_id,'');assert.equal(st.current_id,'');assert.equal(st.offset,0);assert.equal(st.history_offset,0);
 assert.equal(c.__changePayload,null);assert.equal(c.__researchChangeSelection,null);assert.equal(c.__researchPairDraftKey,null);assert.equal(c.__changeLoading,true);
 assert.equal(results.innerHTML,'Loading capture history…');assert.match(notice.innerHTML,/Loading your private capture history/);assert.equal(c.__researchPairDrafts.original.note,'retained private draft');
});

test('account transitions refresh capture source controls before loading new results',()=>{
 const c=harness();let header='';const target={querySelector:()=>({textContent:'Changes in All stocks'}),set outerHTML(value){header=value;}};
 c.document.querySelector=s=>s==='.change-context'?target:null;c.document.getElementById=id=>id==='research-change-results'?{}:null;c.researchLoadChanges=()=>{};
 c.researchSessionSet(privateSession());c.researchChangeState().source='private';c.researchRefreshChangeHeader();assert.match(header,/value="private" selected/);
 c.researchPrivateClear();assert.match(header,/value="manual" selected/);assert.match(header,/value="private"[^>]*disabled/);assert.match(header,/Capture schedule<\/button>/);assert.match(header,/onclick="researchCaptureScheduleOpen\(\)" disabled/);
});

test('private Next unreviewed retains the full capture timeline and paging',async()=>{
 const c=harness();c.__researchSession={user:{id:'owner'}};
 const pair={review_scope:'private_schedule_pair',schedule_id:'schedule',previous_id:'before',current_id:'after',definition:{market:'US'},history:[{id:'older'},{id:'before'},{id:'after'}],history_offset:100,history_has_more:true};
 c.__changePayload=pair;c.researchChangeState().source='private';
 c.researchPrivateAPI=async path=>{assert.match(path,/capture-schedules\/schedule\/pair-reviews/);return {...pair,history:[{id:'before'},{id:'after'}],offset:20,next_review_code:'US.B'};};
 await c.researchPairNext();assert.equal(c.__changePayload.history,pair.history);assert.equal(c.__changePayload.history_offset,100);assert.equal(c.__changePayload.history_has_more,true);assert.equal(c.researchChangeState().offset,20);
});

test('private scheduled export sends exact selected scope and suppresses obsolete downloads',async()=>{
 const c=harness();c.__researchSession={user:{id:'owner'}};
 const pair={comparable:true,review_scope:'private_schedule_pair',schedule_id:'schedule',previous_id:'before',current_id:'after',definition:{market:'US'},review_revision_hash:'a'.repeat(64),rows:[{code:'US.A'}]};
 c.__changePayload=pair;c.researchChangeSelectPage(true);let clicks=0,body,filename;
 c.URL={createObjectURL:()=> 'blob:test',revokeObjectURL(){}};c.document.createElement=()=>({click(){clicks++;filename=this.download;},remove(){}});
 c.researchPrivateAPI=async(path,options)=>{assert.match(path,/schedule\/pair-export$/);assert.equal(options.responseType,'blob');body=JSON.parse(options.body);return {};};
 await c.researchChangesExport('selected','excel');assert.equal(clicks,1);assert.equal(body.scope,'selected');assert.deepEqual(body.codes,['US.A']);assert.equal(body.review_revision_hash,pair.review_revision_hash);assert.match(filename,/_selected\.xls$/);
 let release;c.researchPrivateAPI=()=>new Promise(r=>release=r);const pending=c.researchChangesExport();c.__changeGen=99;release({});await pending;assert.equal(clicks,1);assert.equal(c.__scheduledExportBusy,false);
});


test('capture cadence saves disabled settings and keeps drafts on conflict',async()=>{
 const c=harness();c.__researchSession={user:{id:'owner'}};
 const key=c.researchChangeState().key,ctx={owner:'owner',authGen:0,key,definition:c.researchDefinition(),schedule:{id:'schedule',revision:2}};c.__researchScheduleContext=ctx;
 const status={},button={isConnected:true},form={elements:{name:{value:'Review'},timezone:{value:'Pacific/Auckland'},time:{value:'09:15'}},querySelectorAll:()=>[{value:'0'},{value:'4'}],querySelector:()=>button};
 const dialog={querySelector:()=>status};c.__researchDialog=dialog;let body;
 c.researchPrivateAPI=async(path,opts)=>{assert.equal(path,'/api/research/capture-schedules/schedule');assert.equal(opts.method,'PATCH');body=JSON.parse(opts.body);throw c.researchAuthError('Schedule changed',409);};
 await c.researchCaptureScheduleSave(form);assert.equal(body.enabled,false);assert.equal(body.revision,2);assert.equal(body.cadence.hour,9);assert.deepEqual(body.cadence.weekdays,[0,4]);assert.match(status.textContent,/draft is kept/);assert.equal(c.__researchScheduleDrafts['owner|'+key].name,'Review');
 c.researchPrivateAPI=async()=>({runtime_available:false,schedule:{id:'schedule',owner_id:'owner',revision:3}});
 await c.researchCaptureScheduleSave(form);assert.equal(ctx.schedule.revision,3);assert.equal(c.__researchScheduleDrafts['owner|'+key],undefined);assert.match(status.textContent,/no captures will run/);
});

test('capture cadence rejects no weekdays and changed owner before any write',async()=>{
 const c=harness();c.__researchSession={user:{id:'owner'}};c.__researchScheduleContext={owner:'owner',authGen:0,key:c.researchChangeState().key};
 const status={},form={elements:{name:{value:'Draft'},timezone:{value:'UTC'},time:{value:'10:00'}},querySelectorAll:()=>[],querySelector:()=>({})};c.__researchDialog={querySelector:()=>status};let calls=0;c.researchPrivateAPI=async()=>calls++;
 await c.researchCaptureScheduleSave(form);assert.match(status.textContent,/weekday/);assert.equal(calls,0);
 c.__researchSession.user.id='other';await c.researchCaptureScheduleSave(form);assert.match(status.textContent,/Account or screen changed/);assert.equal(calls,0);
 c.__researchDialog=null;c.researchPrivateClear();assert.equal(c.__researchScheduleContext,null);assert.deepEqual(Object.keys(c.__researchScheduleDrafts),[]);
});


test('capture status distinguishes expired leases and failures without replacing success',()=>{
 const c=harness();const html=c.researchCaptureStatusHTML({last_success:{published_at:'2026-10-02T00:00:00Z',schedule_revision:1},latest_occurrence:{display_status:'awaiting_recovery',attempts:2,current_revision:false,error_code:'incomplete_data'}});
 assert.match(html,/Last successful publication/);assert.match(html,/Lease expired/);assert.match(html,/earlier schedule revision/);assert.match(html,/no capture published/);assert.match(html,/Prior successful captures remain/);
 assert.throws(()=>c.researchCaptureStatusHTML({latest_occurrence:{display_status:'failed',error_code:'untrusted raw error'}}),/not confirmed/);
});

test('capture status failure keeps settings editable and ignores an obsolete dialog',async()=>{
 const c=harness(),target={},el={querySelector:()=>target},ctx={authGen:0,schedule:{id:'schedule'}};c.__researchDialog=el;
 c.researchPrivateAPI=async()=>{throw Error('offline');};await c.researchCaptureScheduleStatus(ctx,el);assert.match(target.textContent,/Settings remain editable/);
 let release;c.researchPrivateAPI=()=>new Promise(r=>release=r);const pending=c.researchCaptureScheduleStatus(ctx,el);c.__researchDialog=null;release({scope:'authenticated_owner',schedule_id:'schedule',runtime_available:false});await pending;assert.equal(target.textContent,'Loading private capture status…');assert.equal(target.innerHTML,undefined);
});


test('cadence feedback and monitoring status use distinct regions',()=>{
 const c=harness();const html=c.researchCaptureScheduleFormHTML({schedule:null});assert.match(html,/data-capture-status role="status"/);assert.match(html,/role="status" data-schedule-message/);
});

test('late monitoring status cannot replace a newer status read',async()=>{
 const c=harness(),target={},el={querySelector:()=>target},ctx={authGen:0,schedule:{id:'schedule'}};c.__researchDialog=el;const replies=[];
 c.researchPrivateAPI=()=>new Promise(r=>replies.push(r));const first=c.researchCaptureScheduleStatus(ctx,el),second=c.researchCaptureScheduleStatus(ctx,el);
 replies[1]({scope:'authenticated_owner',schedule_id:'schedule',runtime_available:false,last_success:null,latest_occurrence:null});await second;const rendered=target.innerHTML;
 replies[0]({scope:'wrong'});await first;assert.equal(target.innerHTML,rendered);assert.equal(target.textContent,'Loading private capture status…');
});

test('comparison interruption offers retry and success clears the pending notice',async()=>{
 const c=harness(),results={innerHTML:'last successful rows'},notice={innerHTML:''},checkbox={disabled:false};
 c.document.querySelectorAll=selector=>selector==='input[data-change-code]'?[checkbox]:[];c.__changePayload={comparable:true,history:[{id:'retained'}]};
 c.document.getElementById=id=>id==='research-change-results'?results:id==='research-change-load-status'?notice:null;
 let reject;c.api=()=>new Promise((_resolve,r)=>reject=r);c.researchChangesRender=(el,d)=>el.innerHTML=d.comparable?'recovered rows':d.reason;
 const pending=c.researchLoadChanges();assert.match(notice.innerHTML,/previous successful request/);assert.equal(results.innerHTML,'last successful rows');assert.equal(c.__changeLoading,true);assert.equal(checkbox.disabled,true);
 reject(Error('Network interrupted'));await pending;assert.match(notice.innerHTML,/Retry comparison/);assert.match(results.innerHTML,/Network interrupted/);assert.equal(c.__changeLoading,false);assert.equal(c.__changePayload,null);assert.equal(checkbox.disabled,false);
 c.api=async()=>({comparable:true});await c.researchLoadChanges();assert.equal(notice.innerHTML,'');assert.equal(results.innerHTML,'recovered rows');
});
test('late failed comparison cannot replace recovered rows or restore an obsolete retry notice',async()=>{
 const c=harness(),results={innerHTML:''},notice={innerHTML:''};c.document.getElementById=id=>id==='research-change-results'?results:id==='research-change-load-status'?notice:null;
 const requests=[];c.api=()=>new Promise((resolve,reject)=>requests.push({resolve,reject}));c.researchChangesRender=(el,d)=>el.innerHTML=d.tag;
 const first=c.researchLoadChanges();c.researchChangeState().status='exited';const second=c.researchLoadChanges();requests[1].resolve({tag:'latest exited rows'});await second;
 requests[0].reject(Error('Obsolete failure'));await first;assert.equal(results.innerHTML,'latest exited rows');assert.equal(notice.innerHTML,'');assert.equal(c.__changeLoading,false);
});
test('comparison search immediately labels retained rows before the debounce request',()=>{
 const c=harness(),notice={innerHTML:''};c.document.getElementById=id=>id==='research-change-load-status'?notice:null;c.researchChangeSearch({value:'ABC'});
 assert.equal(c.__changeLoading,true);assert.equal(c.researchChangeState().q,'ABC');assert.match(notice.innerHTML,/Updating comparison search/);assert.match(notice.innerHTML,/selection and exports are paused/);
});

test('captured monetary display and CSV retain attributed currency without inferring legacy currency',()=>{
 const c=harness(),record={code:'US.A',metrics:{market_cap:2000000000},metric_observations:{market_cap:{code:'US.A',field:'market_cap',value:2000000000,unit:'currency',currency:'USD'}}};
 assert.match(c.researchCapturedMoneyHTML(record,'market_cap'),/USD/);assert.match(c.researchCapturedMoneyHTML({...record,metric_observations:{}},'market_cap'),/Currency not supplied/);
 assert.match(c.researchCapturedMoneyHTML({...record,metric_observations:{market_cap:{...record.metric_observations.market_cap,code:'US.B'}}},'market_cap'),/Currency not supplied/);
 const csv=c.researchChangesCSV({market_cap_sort:{ready:true,currencies:['USD']}},[{code:'US.A',current:record}]);
 assert.match(csv,/previous_metric_observations,current_metric_observations,market_cap_sort_json/);assert.match(csv,/USD/);
});

test('Captured criterion sorts disclose qualification and monetary cells retain exact attribution',()=>{
 const c=harness(),el={innerHTML:'',querySelector:()=>null};c.document.activeElement=null;
 const criterion={field:'price',max:10},observation={criterion,value:4,unit:'currency',currency:'USD'};
 const d={comparable:true,previous_id:'a',current_id:'b',counts:{new:0,exited:0,all:1,unchanged:1},matched:1,definition:{filters:[criterion]},criterion_sorts:{'criterion:before:price':{ready:true},'criterion:after:price':{ready:false}},rows:[{code:'US.A',symbol:'A',status:'unchanged',previous:{evidence:{price:4},criterion_observations:{c0:observation}},current:{evidence:{price:5}}}]};
 c.researchChangesRender(el,d);
 assert.match(el.innerHTML,/value="criterion:before:price"\s+>Price · before/);
 assert.match(el.innerHTML,/value="criterion:after:price" disabled/);
 assert.match(el.innerHTML,/USD 4/);assert.match(el.innerHTML,/Currency not supplied for this value/);
 assert.match(c.researchChangesCSV(d,d.rows),/criterion_sorts_json/);
 assert.doesNotMatch(c.researchCriterionValueHTML(criterion,4,{...observation,value:999}),/USD/);
 assert.doesNotMatch(c.researchCriterionValueHTML(criterion,4,{...observation,criterion:{field:'price',max:100}}),/USD/);
});

test('Equivalent labelled criteria retain captured currency and cross-history review scope is explicit',()=>{
 const c=harness(),original={field:'price',max:10},decorated={field:'price',max:10,min:null,_label:'Price'};
 assert.match(c.researchCriterionValueHTML(decorated,8,{criterion:original,value:8,unit:'currency',currency:'USD'}),/USD 8/);
 assert.doesNotMatch(c.researchCriterionValueHTML({...decorated,max:9},8,{criterion:original,value:8,unit:'currency',currency:'USD'}),/USD/);
 const html=c.researchPairToolsHTML({review_unavailable_reason:'Separate histories; original notes retained'},{});
 assert.match(html,/original notes retained/);assert.doesNotMatch(html,/Sign in to review|Next unreviewed/);
});


test('Reload saved review refreshes filtered rows and fingerprint without replacing the draft',async()=>{
 const c=harness(),results={innerHTML:'old reviewed row'},notice={innerHTML:''};
 c.document.getElementById=id=>id==='research-change-results'?results:id==='research-change-load-status'?notice:null;
 c.__researchSession={user:{id:'owner'}};
 const pair={comparable:true,definition:{market:'US',filters:[]},previous_id:'before',current_id:'after',review_scope:'private_capture_pair',review_contract:'cross_history',review_revision_hash:'old',rows:[{code:'US.A',review:{revision:1,note:'saved',review_status:'reviewed'}}]};
 c.researchDefinition=()=>pair.definition;c.__changePayload=pair;c.researchPairFormHTML(pair,pair.rows[0]);const key=c.__researchPairDraftKey;
 const form={isConnected:true,elements:{note:{value:'my retained draft'},review_status:{value:'reviewed'}},querySelector:()=>({})};
 c.researchChangeState().review_status='reviewed';c.researchDefinition=()=>pair.definition;
 c.api=async()=>pair;let fullReads=0;
 c.researchPrivateAPI=async path=>{const query=new URLSearchParams(path.split('?')[1]);
  if(query.has('code'))return {rows:[{code:'US.A',review:{revision:2,note:'concurrent edit',review_status:'in_review'}}]};
  fullReads++;assert.equal(query.get('review_status'),'reviewed');return {...pair,review_revision_hash:'new',matched:0,rows:[]};
 };
 c.researchChangesRender=(el,d)=>el.innerHTML=d.matched===0?'No reviewed matches': 'stale';
 await c.researchPairReload(form);
 assert.equal(fullReads,1);assert.equal(results.innerHTML,'No reviewed matches');assert.equal(c.__changePayload.review_revision_hash,'new');
 assert.equal(c.__researchPairDrafts[key].note,'my retained draft');assert.equal(c.__researchPairDrafts[key].latest.note,'concurrent edit');assert.equal(c.__researchPairDrafts[key].revision,2);
});


test('Comparison CSV retains the exact before/after instrument classification evidence',()=>{
 const c=harness(),before={version:'instrument_classification_v1',code:'US.PLD',provider_type:'ETF',stock_type:'STOCK',subtype_context:{fields:{quoteType:'EQUITY'}}},after={...before,reason:'qualified_trust_fund_subtype'};
 const csv=c.researchChangesCSV({},[{code:'US.PLD',previous:{instrument_classification:before},current:{instrument_classification:after}}]);
 assert.match(csv.split('\n')[0],/previous_instrument_classification,current_instrument_classification,review_anchor_json,review_variants_json$/);
 assert.match(csv,/EQUITY/);assert.match(csv,/qualified_trust_fund_subtype/);assert.match(csv,/provider_type/);
});

test('Duplicate review scope choices preserve separate drafts and export every original variant',()=>{
 const c=harness();c.__researchSession={user:{id:'owner'}};
 const anchorA={previous_history_key:'original-a',current_history_key:'original-a'},anchorB={previous_history_key:'original-b',current_history_key:'original-b'};
 const variants=[{revision:2,note:'First original',review_status:'reviewed',review_anchor:anchorA},{revision:4,note:'Second original',review_status:'in_review',review_anchor:anchorB}];
 const row={code:'US.A',review:{scope_conflict:true,review_status:'scope_conflict',revision:0,note:'',review_variants:variants}};
 const pair={previous_id:'before',current_id:'after',owner_id:'owner',review_scope:'private_capture_pair',rows:[row],review_scope_conflicts:1};c.__changePayload=pair;c.__researchChangeCode=row.code;
 assert.match(c.researchPairFormHTML(pair,row),/Choose an original review/);assert.equal(c.__researchPairDraftKey,null);
 c.researchChangeInspect=()=>c.researchPairFormHTML(pair,row);
 c.researchPairChooseScope(0);const first=c.__researchPairDraftKey;c.__researchPairDrafts[first].note='First retained draft';
 c.researchPairChooseScope(1);const second=c.__researchPairDraftKey;assert.notEqual(second,first);assert.equal(c.__researchPairDrafts[second].note,'Second original');
 c.researchPairChooseScope(0);assert.equal(c.__researchPairDraftKey,first);assert.equal(c.__researchPairDrafts[first].note,'First retained draft');
 c.researchChangeState=()=>({key:'changed display label'});assert.equal(c.researchPairDraftKey(pair,row.code,anchorA),first);
 const csv=c.researchChangesCSV(pair,[row]);assert.match(csv,/review_anchor_json,review_variants_json/);assert.match(csv,/First original/);assert.match(csv,/Second original/);assert.match(csv,/original-a/);assert.match(csv,/original-b/);
 c.researchPrivateClear();assert.equal(Object.keys(c.__researchPairScopeChoices).length,0);
});

test('Original-anchor save sends the chosen scope and a late result cannot restore another comparison',async()=>{
 const c=harness();c.__researchSession={user:{id:'owner'}};const anchor={previous_history_key:'old',current_history_key:'old'};
 const pair={previous_id:'before',current_id:'after',definition:{market:'US'},owner_id:'owner',review_scope:'private_capture_pair',rows:[{code:'US.A',review:{revision:2,note:'saved',review_status:'reviewed',review_anchor:anchor}}]};c.__changePayload=pair;
 c.researchPairFormHTML(pair,pair.rows[0]);const key=c.__researchPairDraftKey,button={isConnected:true},status={};
 const form={isConnected:true,elements:{note:{value:'submitted'},review_status:{value:'in_review'}},querySelector:s=>s==='button[type=submit]'?button:status};
 let finish,body;c.researchPrivateAPI=(_path,options)=>{body=JSON.parse(options.body);return new Promise(resolve=>finish=resolve);};
 const saving=c.researchPairSave(form);assert.deepEqual(body.review_anchor,anchor);
 c.__changePayload={previous_id:'other',current_id:'pair',rows:[]};c.__changeGen=(c.__changeGen || 0)+1;
 finish({review:{revision:3,note:'submitted',review_status:'in_review',review_anchor:anchor}});await saving;
 assert.equal(c.__changePayload.previous_id,'other');assert.equal(c.__researchPairDrafts[key].revision,2);
});

test('Original-scope reload adopts only the chosen revision and retains independent drafts',async()=>{
 const c=harness();c.__researchSession={user:{id:'owner'}};
 const a={previous_history_key:'a',current_history_key:'a'},b={previous_history_key:'a',current_history_key:'b'};
 const variants=[{revision:2,note:'same saved',review_status:'reviewed',review_anchor:a},{revision:5,note:'cross saved',review_status:'in_review',review_anchor:b}];
 const row={code:'US.A',review:{scope_conflict:true,review_status:'scope_conflict',review_variants:variants}};
 const pair={previous_id:'before',current_id:'after',owner_id:'owner',review_scope:'private_capture_pair',definition:{market:'US'},rows:[row]};c.__changePayload=pair;c.__researchChangeCode='US.A';
 c.researchChangeInspect=()=>c.researchPairFormHTML(pair,row);
 c.researchPairChooseScope(0);const first=c.__researchPairDraftKey;c.__researchPairDrafts[first].note='same draft';
 c.researchPairChooseScope(1);const second=c.__researchPairDraftKey;
 const form={isConnected:true,elements:{note:{value:'cross draft'},review_status:{value:'in_review'}},querySelector:()=>({})};
 c.researchPrivateAPI=async()=>({rows:[{code:'US.A',review:{...row.review,review_variants:[{...variants[0],revision:99},{...variants[1],revision:6,note:'concurrent cross edit'}]}}]});
 await c.researchPairReload(form);
 assert.equal(c.__researchPairDrafts[second].revision,6);assert.equal(c.__researchPairDrafts[second].note,'cross draft');assert.equal(c.__researchPairDrafts[second].latest.note,'concurrent cross edit');
 assert.equal(c.__researchPairDrafts[first].revision,2);assert.equal(c.__researchPairDrafts[first].note,'same draft');
});

test('Delayed save and reload failures cannot alter a switched pair or scope',async()=>{
 for(const operation of ['researchPairSave','researchPairReload'])for(const change of ['payload','generation','scope']){
  const c=harness();c.__researchSession={user:{id:'owner'}};
  const pair={previous_id:'before',current_id:'after',definition:{market:'US'},review_scope:'private_capture_pair',rows:[{code:'US.A',review:{revision:2,note:'saved',review_status:'reviewed'}}]};
  c.__changePayload=pair;c.researchPairFormHTML(pair,pair.rows[0]);const key=c.__researchPairDraftKey,draft=c.__researchPairDrafts[key],status={},button={isConnected:true};
  const form={isConnected:true,elements:{note:{value:'retained draft'},review_status:{value:'reviewed'}},querySelector:s=>s==='button[type=submit]'?button:status};
  let reject;c.researchPrivateAPI=()=>new Promise((_resolve,r)=>reject=r);const request=c[operation](form);const originalStatus=status.textContent,originalMessage=draft.message;
  if(change==='payload')c.__changePayload={...pair};if(change==='generation')c.__changeGen=(c.__changeGen || 0)+1;if(change==='scope')c.__researchPairDraftKey='another original scope';
  reject(Object.assign(new Error('obsolete conflict'),{status:409}));await request;
  assert.equal(status.textContent,originalStatus);assert.equal(draft.message,originalMessage);assert.equal(draft.note,'retained draft');assert.equal(draft.revision,2);
 }
});

 test('Desk MVP redirects deferred presentations without changing saved criteria or sorts',()=>{
 const c=harness();c.__researchExtendedWorkspace=false;
 for(const mode of ['explore','changes']){
  c.location.hash='#/screener?m=HK&mode='+mode+'&s=pe_ttm&d=1&f='+encodeURIComponent(JSON.stringify([{field:'pb',max:1}]));
  c.scrRestoreFromHash();assert.equal(c.__scr.presentation,'table');assert.equal(c.__scr.market,'HK');assert.equal(c.__scr.sort,'pe_ttm');assert.equal(c.__scr.dir,1);assert.equal(c.__scr.filters[0].max,1);
  c.__scr.presentation=mode;const desk=c.researchDeskHTML({st:c.__scr,scr:{rows:[],matched:0},table:'',allChips:'',msPanel:''});
  assert.equal(c.__scr.presentation,'table');assert.doesNotMatch(desk,/researchMode\('explore'\)|researchMode\('changes'\)|Research shortlists|Capture snapshot/);assert.match(desk,/scrResetAll/);assert.match(desk,/scrExport/);
 }
 c.researchMode('changes');assert.equal(c.__scr.presentation,'table');
 const saved={market:'HK',filters:c.__scr.filters,sort:c.__scr.sort,direction:c.__scr.dir,settings:{presentation:'explore'}};
 assert.equal(c.researchSavedModified(saved,c.__scr),false);assert.equal(saved.settings.presentation,'explore');
});

test('unsupported RSI presets stay visible, disabled and never warmed or applied',()=>{
 const c=harness();c.__researchExtendedWorkspace=false;
 c.__scrPresets=[{key:'rsi-30',name:'Oversold',sort:'pct',filters:[{field:'rsi14',max:30}]},{key:'small-growth',name:'Small growth',filters:[{field:'rsi14',min:50}]},{key:'penny',name:'Penny',filters:[{field:'price',max:5}]}];
 const before=JSON.stringify(c.__scr);for(const key of ['rsi-30','small-growth']){c.scrWarmPreset(key,'US');c.scrApplyPreset(key);}
 assert.equal(JSON.stringify(c.__scr),before);assert.equal(c.__presetWarmQueue,undefined);
 const library=c.researchLibraryHTML(c.__scr,c.__scrPresets);assert.equal((library.match(/Unavailable — RSI provider unsupported/g)||[]).length,2);
 for(const key of ['rsi-30','small-growth'])assert.match(library,new RegExp('data-screen-key="'+key+'" disabled'));
 assert.doesNotMatch(library,/data-screen-key="penny" disabled/);
 assert.equal(c.__scrPresets[0].filters[0].max,30);
});

test('cold unavailable market stays unavailable through actual Desk rendering and cannot export',async()=>{
 const c=harness();c.__researchExtendedWorkspace=false;c.__scr.market='HK';c.scrLoadDataset=async()=>null;
 c.scrPanelFetch=async()=>({rail:{presets:[]}});c.scrIdb=()=>assert.fail('Unavailable response persisted');
 c.api=async()=>({available:false,rows:[],refresh_required:true,reason:'No stored HK market data is available.'});
 const result=await vm.runInContext('pages.home()',c);assert.equal(c.__homeCtx.scr.available,false);assert.equal(c.__scrDataset.available,false);
 assert.match(result,/Data unavailable/);assert.match(result,/Load HK market/);assert.match(result,/Market data unavailable/);assert.doesNotMatch(result,/0 stocks/);
 let alert;c.alert=message=>{alert=message;};c.scrExport('csv','all');assert.match(alert,/No stored HK/);
 // Failed results must be rejected before touching IndexedDB.
 c.scrIdb=()=>assert.fail('Unavailable response persisted');await vm.runInContext('scrPersistDataset(window.__scrDataset)',c);
});
test('failed background market refresh retains the previous successful cohort and clock',async()=>{
 const c=harness(),saved={key:'US|0|moo',ts:Date.now()-120000,asOf:'2026-10-02T00:00:00Z',rows:[stock('A',10,1,{code:'US.A'})]};
 c.scrLoadDataset=async()=>saved;c.__panelCache={market:'US',rail:{presets:[]}};c.scrStreamPanels=()=>{};
 let finish;c.api=()=>new Promise(resolve=>{finish=resolve;});c.scrPersistDataset=()=>assert.fail('Failed refresh replaced stored success');
 await vm.runInContext('pages.home()',c);const original=c.__scrDataset;assert.equal(c.__homeCtx.scr.matched,1);
 finish({available:false,rows:[],reason:'Provider unavailable'});await Promise.resolve();await Promise.resolve();
 assert.equal(c.__scrDataset,original);assert.equal(c.__scrDataset.rows[0].code,'US.A');assert.equal(c.__scrDataset.asOf,saved.asOf);assert.equal(c.__scrDataset.refreshError,'Provider unavailable');
});

 test('failed initial provider screen is unavailable rather than zero and retries without changing screen state',async()=>{
 const c=harness();c.__researchExtendedWorkspace=false;Object.assign(c.__scr,{activePreset:'p',market:'HK',filters:[{field:'pb',max:1}],sort:'pct',dir:2});
 c.__scrPresets=[{key:'p',name:'Screen',filters:[{field:'pb',max:1}]}];c.__panelCache={market:'HK',rail:{presets:c.__scrPresets}};c.scrStreamPanels=()=>{};
 let calls=0;c.api=async()=>++calls===1?{available:false,reason:'Provider failed <source>'}:{available:true,rows:[stock('00700',10,1,{code:'HK.00700',pb:0.5})],filters:[{field:'pb',max:1}],name:'Screen'};
 const before=JSON.stringify(c.__scr);const failed=await vm.runInContext('pages.home()',c);
 assert.equal(c.__homeCtx.scr.available,false);assert.match(failed,/Data unavailable/);assert.doesNotMatch(failed,/0 stocks/);assert.match(failed,/Retry screen/);assert.match(failed,/Provider failed &lt;source&gt;/);assert.match(failed,/onclick="scrExport\('csv','all'\)"/);
 const buttons=[...failed.matchAll(/<button[^>]+onclick="scrExport[^>]+>/g)];assert.equal(buttons.length,4);buttons.forEach(([button])=>assert.match(button,/disabled/));
 let message;c.alert=text=>{message=text;};c.scrExport('csv','all');assert.match(message,/unavailable/);
 c.showPage=async()=>vm.runInContext('pages.home()',c);const button={disabled:false,isConnected:true};await c.researchRetryPreset(button);
 assert.equal(c.__homeCtx.scr.available,true);assert.equal(c.__homeCtx.scr.matched,1);assert.equal(JSON.stringify(c.__scr),before);assert.equal(button.disabled,false);assert.equal(calls,2);
 });


test('cold or failed screen library never reports zero preserved presets and retry bypasses stale cache',()=>{
 const c=harness();c.__scrPresetLibraryStatus='loading';
 assert.match(c.researchLibraryHTML(c.__scr,[]),/Loading…/);
 assert.doesNotMatch(c.researchLibraryHTML(c.__scr,[]),/0 screens/);
 c.__scrPresetLibraryStatus='unavailable';
 assert.match(c.researchLibraryHTML(c.__scr,[]),/Retry screen library/);
 const preserved=[{key:'penny',name:'Penny',filters:[]}];
 assert.match(c.researchLibraryHTML(c.__scr,preserved),/data-screen-key="penny"/);
 c.__panelCache={market:c.__scr.market,ts:Date.now(),rail:{available:false,presets:[]}};
 let called; c.scrStreamPanels=market=>{called=market};c.scrRetryPresetLibrary();
 assert.equal(called,c.__scr.market);assert.equal(c.__panelCache.ts,0);
});

test('column chooser coverage counts loaded supplied values without numeric coercion or qualification',()=>{
 const c=harness();
 const rows=[{price:0,roe:-1,volume:0,name:'A',concepts:['Banks'],new_high:false},{price:2,roe:0,volume:1,name:' ',concepts:[],new_high:'0'},{price:null,roe:NaN,volume:true,name:null,concepts:[' '],new_high:null},{price:NaN,roe:false,volume:'100',concepts:[1]},{price:true,roe:Infinity,volume:Infinity}];
 const coverage=c.scrColumnCoverage(rows);
 assert.equal(coverage.price,'2/5 supplied');assert.equal(coverage.roe,'2/5 supplied');assert.equal(coverage.volume,'2/5 supplied');
 assert.equal(coverage.name,'1/5 supplied');assert.equal(coverage.concepts,'1/5 supplied');assert.equal(coverage.new_high,'2/5 supplied');
 assert.equal(coverage.eps,'Not supplied');assert.equal(c.scrColumnCoverage([]).price,'No rows loaded');
 assert.equal(c.scrColumnCoverage(null).symbol,'No rows loaded');
});

test('column chooser computes loaded coverage once per opening and preserves it while drafting columns',()=>{
 const c=harness(),modal={innerHTML:'',remove(){}};let reads=0;
 c.scrClientRows=()=>{reads++;return [{price:0},{price:null}];};
 c.document.createElement=()=>modal;c.document.body.appendChild=()=>{};
 c.scrToggleColPick();assert.equal(reads,1);assert.match(modal.innerHTML,/Coverage in loaded results only/);
 assert.match(modal.innerHTML,/1\/2 supplied/);assert.match(modal.innerHTML,/Not supplied/);
 assert.doesNotMatch(modal.innerHTML,/disabled/);
 const before=c.__scr.cols.join(','),draft={textContent:'in table'},coverage={textContent:'1/2 supplied'};
 c.document.querySelectorAll=()=>[{getAttribute:()=>"scrDragStart(event,'price','picker')",querySelector:selector=>selector==='.col-draft-status'?draft:coverage}];
 c.scrColDraftCheck('price',false);assert.equal(draft.textContent,'');assert.equal(coverage.textContent,'1/2 supplied');
 c.scrColDraftCheck('rsi14',true);assert.equal(c.__scr.cols.join(','),before);assert.equal(reads,1);
});

test('HK to US cold market switch paints ready quotes before unrelated side panels finish',async()=>{
 const c=harness();c.__researchExtendedWorkspace=false;
 const payload=market=>({available:true,rows:[stock(market==='HK'?'00700':'AAPL',10,1,{code:market==='HK'?'HK.00700':'US.AAPL'})],universe_as_of:'2026-10-03T00:00:00Z'});
 Object.assign(c.__scr,{market:'HK',activePreset:null});
 c.__scrDataset={key:'HK|0|moo',ts:Date.now(),available:true,rows:payload('HK').rows};
 c.__panelCache={market:'HK',ts:Date.now(),rail:{presets:[]}};
 c.scrLoadDataset=async()=>null;c.scrPersistDataset=()=>{};c.scrLoadTaxonomy=c.scrLoadMyPresets=()=>{};
 let resolvePanel;const slowPanel=new Promise(resolve=>{resolvePanel=resolve;});
 const quoteCalls=[];
 c.api=async url=>{
  if(url==='/api/candidates')return slowPanel;
  if(url.startsWith('/api/screener?')){const market=new URLSearchParams(url.split('?')[1]).get('market');quoteCalls.push(market);return payload(market);}
  if(url.startsWith('/api/decisions'))return {decisions:[]};
  if(url.startsWith('/api/screener/presets'))return {presets:[]};
  return {available:false};
 };
 await c.render('home');assert.match(c.document.querySelector('#page').innerHTML,/HK\.00700/);
 let pending;c.showPage=page=>pending=c.render(page);c.scrSet('market','US');
 let completed=false;pending.then(()=>{completed=true;});
 for(let i=0;i<20;i++)await Promise.resolve();
 assert.equal(completed,true,'An unrelated pending panel must not block the new market');
 const html=c.document.querySelector('#page').innerHTML;
 assert.match(html,/US\.AAPL/);assert.doesNotMatch(html,/HK\.00700/);
 assert.equal(c.__homeCtx.scr.rows[0].code,'US.AAPL');assert.equal(c.__scrDataset.key,'US|0|moo');
 assert.match(c.location.hash,/m=US/);assert.deepEqual(quoteCalls,['US']);
 // A late US panel cannot restore US quotes after switching back to HK.
 c.scrSet('market','HK');for(let i=0;i<20;i++)await Promise.resolve();
 resolvePanel({candidates:[]});for(let i=0;i<20;i++)await Promise.resolve();
 assert.match(c.document.querySelector('#page').innerHTML,/HK\.00700/);
 assert.doesNotMatch(c.document.querySelector('#page').innerHTML,/US\.AAPL/);
 assert.equal(c.__scrDataset.key,'HK|0|moo');assert.equal(c.__scr.market,'HK');
});
