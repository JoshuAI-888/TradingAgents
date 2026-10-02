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
 assert.equal(csv.toString('utf8').replace(/^\ufeff/,'').split('\n').slice(1).join('\n'),'1,BRK.A,10\n2,BRK.B,9');assert.match(filename,/_selected\.csv$/);
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
 c.scrExport('csv','explore');assert.equal((await blob.text()).replace(/^\ufeff/,'').split('\n').slice(1).join('\n'),'1,A,10,0\n2,B,20,2');assert.match(filename,/_region\.csv$/);assert.equal(c.__scr.cols.join(','),'symbol');
 c.researchExploreState().bounds.x.min=99;c.scrExport('csv','explore');assert.equal(clicked,1);
});
test('Clear discards the Explorer region and zoom as well as defaulting the query',()=>{
 const c=harness();const st=c.researchExploreState();st.bounds={x:{min:10,max:20},y:{min:0,max:1}};st.zoom=true;st.x='market_cap';st.ys='log';
 c.scrResetAll();const next=c.researchExploreState();assert.equal(next.bounds,null);assert.equal(next.zoom,false);assert.equal(next.x,'pe_ttm');assert.equal(next.ys,'linear');assert.equal(c.__scr.presentation,'table');
});
