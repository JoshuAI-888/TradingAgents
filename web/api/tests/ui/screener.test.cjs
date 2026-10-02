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
 assert.match(html,/research-workspace\.js\?v=20261002-explorer-currency/);assert.match(html,/research-account\.js\?v=20261002-explorer-currency/);
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
 const key=c.__researchPairDraftKey;c.researchPairDraftUpdate({elements:{note:{value:'unsaved'},review_status:{value:'reviewed'}}});
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
