const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../../static/index.html'), 'utf8');
const script = ['research-workspace.js', 'research-account.js']
  .map(name => fs.readFileSync(path.join(__dirname, '../../static', name), 'utf8')).join('\n')
  + '\n' + [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].slice(1).map(m => m[1]).join('\n');

function harness() {
  const page = {innerHTML: ''}, table = {scrollTop: 0, scrollLeft: 0}, storage = new Map();
  const document = {
    querySelector: selector => selector === '#page' ? page : selector === '.scr-scroll' ? table : null,
    querySelectorAll: () => [], getElementById: () => null, addEventListener() {},
    createElement: () => ({style: {}, remove() {}}), body: {appendChild() {}}, visibilityState: 'visible',
  };
  const context = {
    document, localStorage: {getItem: () => null, setItem() {}},
    sessionStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
    location: {hash: '', pathname: '/', search: ''}, URLSearchParams, URL, console,
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
    fetch: async () => ({ok: true, json: async () => ({})}), addEventListener() {}, scrollTo() {},
  };
  context.history = {replaceState(_a, _b, hash) {context.location.hash = hash;}, pushState(_a, _b, hash) {context.location.hash = hash;}};
  context.window = context;
  vm.createContext(context);
  vm.runInContext(script.slice(0, script.indexOf('document.querySelectorAll(".nav button").forEach(b => b.onclick')), context);
  context.showPage = () => {};
  return {context, table};
}

// An independent CSV parser checks actual downloaded values, including quoting.
function csvRecords(text) {
  const records = [], row = []; let cell = '', quoted = false;
  text = text.replace(/^\ufeff/, '');
  for (let index = 0; index < text.length; index++) {
    const char = text[index];
    if (char === '"') {
      if (quoted && text[index + 1] === '"') {cell += '"'; index++;}
      else quoted = !quoted;
    } else if (!quoted && (char === ',' || char === '\n')) {
      row.push(cell); cell = '';
      if (char === '\n') {records.push(row.splice(0));}
    } else cell += char;
  }
  row.push(cell); records.push(row);
  const headers = records.shift();
  return records.map(values => Object.fromEntries(headers.map((key, index) => [key, values[index]])));
}
function xmlRecords(text) {
  const rows = [...text.matchAll(/<Row>([\s\S]*?)<\/Row>/g)].map(match =>
    [...match[1].matchAll(/<Cell><Data ss:Type="(Number|String)">([\s\S]*?)<\/Data><\/Cell>/g)]
      .map(cell => ({type: cell[1], value: cell[2].replaceAll('&amp;', '&').replaceAll('&lt;', '<').replaceAll('&gt;', '>')})));
  const headers = rows.shift().map(cell => cell.value);
  return rows.map(values => Object.fromEntries(headers.map((key, index) => [key, values[index]])));
}

for (const market of ['US', 'HK']) {
  test(`${market} Desk CSV and Excel all/page/selected downloads retain multi-page cohort order and values`, async () => {
    const {context: c} = harness(), generation = '11111111-1111-4111-8111-111111111111';
    const rows = Array.from({length: 225}, (_, index) => {
      const symbol = market === 'HK' ? String(index + 1).padStart(5, '0') : index === 220 ? 'BRK.B' : `S${index}`;
      return {code: `${market}.${symbol}`, symbol, stock_type: 'STOCK', price: index, pct: index / 10,
        market_cap: index * 1e6, currency: market === 'HK' ? 'HKD' : 'USD',
        field_observations: {price: {code: `${market}.${symbol}`, field: 'price', value: index, unit: 'currency', currency: market === 'HK' ? 'HKD' : 'USD'}},
        generation_id: generation, quote_cache_at: '2026-10-03T00:00:00Z'};
    });
    c.__scrDataset = {key: `${market}|0|moo`, rows: [...rows,
      {...rows[224], code: `${market}.ETF`, stock_type: 'ETF'},
      {...rows[224], code: `${market}.UNKNOWN`, stock_type: 'UNKNOWN'}]};
    Object.assign(c.__scr, {market, presentation: 'table', page: 2, pageSize: 100,
      sort: 'market_cap', dir: 2, filters: [{field: 'price', min: 10, max: 220}],
      cols: ['symbol', 'price', 'pct', 'market_cap']});
    const expected = rows.filter(row => row.price >= 10 && row.price <= 220).reverse();
    assert.deepEqual(Array.from(c.scrClientRows(), row => row.code), expected.map(row => row.code));
    const selected = [expected.at(-1).code, expected[0].code, expected[110].code];
    c.__researchSelected = selected;
    const downloads = [];
    c.Blob = Blob;
    c.URL = {createObjectURL(blob) {downloads.push({blob}); return 'blob:desk-test';}, revokeObjectURL() {}};
    c.document.createElement = () => ({click() {downloads.at(-1).filename = this.download;}, remove() {}});
    c.alert = message => assert.fail(message);
    for (const scope of ['all', 'page', 'selected']) {
      const scopeRows = scope === 'all' ? expected : scope === 'page' ? expected.slice(100, 200)
        : expected.filter(row => selected.includes(row.code));
      for (const kind of ['csv', 'xls']) {
        c.scrExport(kind, scope);
        const download = downloads.at(-1), text = await download.blob.text();
        assert.match(download.filename, new RegExp(`^screener_${market}_${scopeRows.length}rows_.*\\.${kind}$`));
        const parsed = kind === 'csv' ? csvRecords(text) : xmlRecords(text);
        const value = (record, key) => kind === 'csv' ? record[key] : record[key].value;
        assert.equal(parsed.length, scopeRows.length);
        assert.deepEqual(parsed.map(record => value(record, 'code')), scopeRows.map(row => row.code));
        parsed.forEach((record, index) => {
          const expectedRow = scopeRows[index];
          for (const [header, field] of [['Symbol', 'symbol'], ['Price', 'price'], ['% Chg', 'pct'], ['Market Cap', 'market_cap']]) {
            assert.equal(value(record, header), String(expectedRow[field]));
            if (kind === 'xls') assert.equal(record[header].type, field === 'symbol' ? 'String' : 'Number');
          }
          assert.equal(value(record, 'No.'), String(expected.indexOf(expectedRow) + 1));
          assert.equal(value(record, 'price_currency'), market === 'HK' ? 'HKD' : 'USD');
          assert.equal(value(record, 'market_cap_currency'), 'Unavailable');
          assert.equal(value(record, 'generation_id'), generation);
          assert.equal(value(record, 'quote_cache_at'), expectedRow.quote_cache_at);
        });
      }
    }
    assert.equal(downloads.length, 6);
    assert.equal(c.__scr.page, 2);
  });

  test(`${market} full research return restores exact Desk preset/sort/page/selection and both scroll positions`, async () => {
    const {context: c, table} = harness();
    Object.assign(c.__scr, {market, activePreset: 'penny', savedScreenId: 'retained-screen',
      filters: [{field: 'price', max: 10}], colFilters: {pb: {max: 2}}, sort: 'pct', dir: 1,
      page: 3, pageSize: 100, cols: ['symbol', 'price', 'pb'], presentation: 'table'});
    c.__researchSelected = [`${market}.A`, `${market}.B`];
    c.researchRows = () => [{code: `${market}.A`, symbol: 'A'}, {code: `${market}.B`, symbol: 'B'}];
    c.scrollY = 310; table.scrollTop = 220; table.scrollLeft = 140;
    vm.runInContext("state.page='home'", c);
    let opened; c.openStock = code => {opened = code; vm.runInContext("state.page='stock'", c);};
    c.researchOpen(`${market}.B`);
    assert.equal(opened, `${market}.B`);
    const expected = JSON.parse(JSON.stringify(c.__scr));
    c.__scr.filters[0].max = 999; c.__scr.colFilters.pb.max = 99;
    Object.assign(c.__scr, {market: market === 'US' ? 'HK' : 'US', activePreset: null, sort: 'market_cap', dir: 2, page: 1});
    c.__researchSelected = []; table.scrollTop = 0; table.scrollLeft = 0;
    const actions = [];
    c.showPage = async page => {actions.push(page); assert.deepEqual(JSON.parse(JSON.stringify(c.__scr)), expected); await Promise.resolve();};
    c.scrollTo = (x, y) => {actions.push([x, y]);};
    await c.researchReturn();
    assert.deepEqual(actions, ['home', [0, 310]]);
    assert.deepEqual(JSON.parse(JSON.stringify(c.__scr)), expected);
    assert.deepEqual(Array.from(c.__researchSelected), [`${market}.A`, `${market}.B`]);
    assert.equal(table.scrollTop, 220); assert.equal(table.scrollLeft, 140);
    assert.notEqual(c.__scr, c.__researchContext.state);
    assert.match(c.location.hash, new RegExp(`m=${market}`));
    assert.match(c.location.hash, /p=3/);
  });
}

test('Why evidence merges pinned source observations only onto unchanged attributed values', () => {
  const {context: c} = harness();
  const row = {code:'US.AAPL',generation_id:'11111111-1111-4111-8111-111111111111',pct:2.5,price:10};
  const o = {code:row.code,field:'pct',value:2.5,source:'moomoo_cloud_snapshot',unit:'percentage_points',currency:null,observed_at:'2026-10-03T00:01:00Z'};
  const payload = {code:row.code,generation_id:row.generation_id,values:{pct:2.5},field_observations:{pct:o}};
  const merged = c.researchMergeObservations(row,payload);
  assert.equal(merged.field_observations.pct.source,o.source);
  assert.equal(c.researchEvidence(merged,{field:'pct',min:1},null).source,o.source);
  assert.equal(c.researchMergeObservations({...row,pct:99},payload).field_observations.pct,undefined);
  assert.equal(c.researchMergeObservations(row,{...payload,generation_id:'other'}),row);
  assert.equal(row.field_observations,undefined);
});

test('Why asynchronous evidence ignores closed inspectors and changed generation responses', async () => {
  const {context: c} = harness();
  const row = {code:'US.AAPL',generation_id:'11111111-1111-4111-8111-111111111111',pct:2.5};
  let resolve; c.api = () => new Promise(done => {resolve=done;});
  c.__inspectGen=1;c.__researchInspectCode=row.code;c.__inspectRow=row;c.__inspectTab='why';
  const target={innerHTML:'original'};c.document.getElementById=id=>id==='inspector-content'?target:null;
  const pending=c.researchObservationMount(row,1);c.__inspectGen=2;
  resolve({code:row.code,generation_id:row.generation_id,values:{pct:2.5},field_observations:{pct:{code:row.code,field:'pct',value:2.5}}});
  await pending;assert.equal(target.innerHTML,'original');
  c.__researchObservationCache.clear();c.__inspectGen=3;
  const second=c.researchObservationMount(row,3);
  c.__scrDataset={rows:[{...row,generation_id:'22222222-2222-4222-8222-222222222222'}]};
  c.researchRows=()=>c.__scrDataset.rows;
  resolve({code:row.code,generation_id:row.generation_id,values:{pct:2.5},field_observations:{}});
  await second;assert.equal(target.innerHTML,'original');
});

test('Why hydrates original evidence without replacing inspector controls and bounds its cache', async () => {
  const {context: c} = harness(), target={innerHTML:'loading'}, generation='11111111-1111-4111-8111-111111111111';
  c.document.getElementById=id=>id==='inspector-content'?target:null;
  c.scrEffFilters=()=>[{field:'pct',min:1}];c.researchRows=()=>[];
  let requests=0;
  c.api=async url=>{requests++;const code=new URL('https://example.test'+url).searchParams.get('code');return {code,generation_id:generation,values:{pct:2.5},field_observations:{pct:{code,field:'pct',value:2.5,source:'moomoo_cloud_snapshot',currency:null,observed_at:'2026-10-03T00:01:00Z'}}};};
  for(let i=0;i<35;i++){
    const row={code:'US.S'+i,generation_id:generation,pct:2.5};
    c.__inspectGen=i;c.__researchInspectCode=row.code;c.__inspectRow=row;c.__inspectTab='why';
    await c.researchObservationMount(row,i);
  }
  assert.equal(c.__researchObservationCache.size,32);
  assert.match(target.innerHTML,/moomoo_cloud_snapshot/);
  const last=c.__inspectRow;c.__inspectRow={...last,pct:99,field_observations:{}};
  await c.researchObservationMount(c.__inspectRow,34);
  assert.equal(requests,35);
  assert.equal(c.__inspectRow.pct,99);
  assert.equal(c.__inspectRow.field_observations.pct,undefined);
  assert.doesNotMatch(target.innerHTML,/moomoo_cloud_snapshot/);
});
