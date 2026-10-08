/* Executes the rendered worker, rather than matching implementation strings. */
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(0, 'utf8');
const origin = 'https://motionmate.example';
const handlers = {};
const stores = new Map();
const fetches = [];
let network = async () => new Response('network');
const context = {
  URL, Response, Promise, Error,
  self: { location: { origin }, addEventListener: (name, fn) => { handlers[name] = fn; },
    skipWaiting: async () => {}, clients: { claim: async () => {} } },
  caches: {
    keys: async () => [...stores.keys()],
    delete: async key => stores.delete(key),
    open: async key => {
      if (!stores.has(key)) stores.set(key, new Map());
      const store = stores.get(key);
      return {
        put: async (request, response) => store.set(request.url || request, response.clone()),
        match: async request => store.get(request.url || request)?.clone()
      };
    }
  },
  fetch: async (request, options) => {
    fetches.push({ url: request.url || request, options });
    return network(request, options);
  }
};
vm.runInNewContext(source, context);
async function lifecycle(name) {
  let done;
  handlers[name]({waitUntil: promise => { done = promise; }});
  await done;
}
function request(path, method = 'GET', mode = 'navigate') {
  let result;
  handlers.fetch({request: {url: new URL(path, origin).href, method, mode},
    respondWith: promise => { result = promise; }});
  return result;
}
const cachedURLs = () => [...stores.values()].flatMap(store => [...store.keys()]);
(async () => {
  await lifecycle('install');
  assert.equal(cachedURLs().length, 7);
  assert(cachedURLs().every(url => url === origin + '/offline/' || url.startsWith(origin + '/static/assets/')));
  assert(fetches.every(call => call.options.credentials === 'omit' && call.options.cache === 'no-store'));
  stores.set('motionmate-pwa-old', new Map());
  stores.set('other-application', new Map());
  await lifecycle('activate');
  assert(!stores.has('motionmate-pwa-old'));
  assert(stores.has('other-application'));
  const before = cachedURLs();
  const privateRoutes = ['/crm/staff/clients/', '/logistics/parcels/', '/logistics/shipments/',
    '/billings/invoices/', '/accounts/profile', '/businesses/settings/', '/api/private.json'];
  for (const route of privateRoutes) {
    assert.equal(await (await request(route)).text(), 'network');
    assert.equal(fetches.at(-1).options.cache, 'no-store');
  }
  assert.deepEqual(cachedURLs(), before);
  network = async () => { throw new Error('offline'); };
  for (const route of privateRoutes.slice(0, -1)) {
    const response = await request(route);
    assert.equal(response.status, 503);
    assert.equal(response.headers.get('Cache-Control'), 'no-store');
  }
  for (const route of ['/api/private.json', '/logistics/track/', '/home/', '/book/demo/']) {
    await assert.rejects(request(route));
  }
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
    await assert.rejects(request('/logistics/parcels/1/update/', method));
  }
  await assert.rejects(request('/crm/staff/clients/', 'GET', 'cors'));
  assert.equal(request('/static/assets/css/pwa.css?version=other', 'GET', 'cors'), undefined);
  assert.equal((await request('/static/assets/css/pwa.css', 'GET', 'cors')).status, 200);
  assert.equal(request('https://external.example/script.js', 'GET', 'cors'), undefined);
  network = async () => new Response('denied', { status: 403 });
  assert.equal((await request('/logistics/parcels/')).status, 403);
  assert.deepEqual(cachedURLs(), before);
  await assert.rejects(lifecycle('install'));
  console.log('Worker policy checks passed: static allowlist, cleanup, private network-only, offline navigation, mutation/API failures, public separation, HTTP errors.');
})().catch(error => { console.error(error); process.exitCode = 1; });
