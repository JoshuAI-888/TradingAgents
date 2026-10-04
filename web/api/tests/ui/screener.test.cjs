const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../../static/index.html'), 'utf8');
const helper = fs.readFileSync(require('node:path').join(__dirname, '../../static/research-workspace.js'),'utf8');
const script = helper + '\n' + [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].slice(1).map(m=>m[1]).join('\n');
function harness(saved = {}, hash = '') {
  const page = {innerHTML:'existing screener'};
  const elements = new Map([['page',page]]);
  const document = {querySelector: s => s === '#page' ? page : null, querySelectorAll:()=>[],
    getElementById:id=>elements.get(id), addEventListener(){}, visibilityState:'visible',
    createElement:()=>({style:{},remove(){}}), body:{appendChild(){}}};
  const c = {document, localStorage:{getItem:k=>k==='scrState'?JSON.stringify(saved):null,setItem(){}},
    location:{hash,pathname:'/',search:''}, history:{replaceState(_a,_b,h){c.location.hash=h;}},
    URLSearchParams, URL, console, setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},
    fetch:async()=>({ok:true,json:async()=>({})})};
  c.window=c; c.addEventListener=()=>{}; c.scrollTo=()=>{};
  vm.createContext(c);
  vm.runInContext(script.slice(0, script.indexOf('document.querySelectorAll(".nav button").forEach(b => b.onclick')),c);
  c.render = vm.runInContext('showPage',c);
  c.showPage=()=>{};
  return c;
}
const stock = (symbol,cap,pct,extra={})=>({symbol,market_cap:cap,pct,stock_type:'STOCK',...extra});
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
