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
  const c = {document, localStorage:{getItem:k=>k==='scrState'?JSON.stringify(saved):null,setItem(){}},
    location:{hash,pathname:'/',search:''}, history:{replaceState(_a,_b,h){c.location.hash=h;}},
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
 const h={elId:'chart-a',state:()=>({sym:'AAPL',range:'Y'}),drawingScope:'scope-a',drawingIds:['trend'],
 chart:{getOverlayById:()=>({name:'segment',points:[{timestamp:1,value:100},{timestamp:2,value:110}]})}};
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
 assert.equal(e.value,'Numeric evidence unavailable');assert.equal(e.threshold,'> 5%');assert.equal(e.period,'Annual financial criterion');
 const v=c.researchEvidence({criterion_values:{volume:100001}},{field:'volume',min:100000,days:30},'penny');
 assert.equal(v.value,'100,001 shares');assert.equal(v.period,'30-day average');
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
 c.api=()=>new Promise(resolve=>pending.push(resolve));
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
 const c=harness();const rows=[stock('BRK.B',100,0,{code:'US.BRK.B',pe_ttm:8}),stock('BRK.A',90,0,{code:'US.BRK.A',pe_ttm:'8'}),stock('C',80,0,{code:'US.C',pe_ttm:8.000001}),stock('D',70,0,{code:'US.D',pe_ttm:null})];
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
