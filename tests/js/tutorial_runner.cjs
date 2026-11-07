// Synthetic browser surfaces; Web Crypto and the documented scripts run in Node.
const {webcrypto} = require('node:crypto');
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const session = new Map(Object.entries(input.session || {}));
const local = new Map(Object.entries(input.local || {}));
const storage = map => ({
    getItem: key => map.get(key) ?? null,
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: key => map.delete(key),
});
let listener;
const requests = [];
const errors = [];
const location = {origin: 'https://client.example', search: input.search || ''};
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const run = new AsyncFunction('crypto', 'document', 'window', 'sessionStorage',
    'localStorage', 'fetch', 'console', input.script);
(async () => {
    await run(webcrypto, {getElementById: () => ({addEventListener: (_, fn) => {listener = fn;}})},
        {location}, storage(session), storage(local), async (url, options) => {
            requests.push({url, body: Object.fromEntries(options.body), headers: options.headers});
            if (input.networkError) throw new Error('Synthetic network failure');
            return {ok: input.ok ?? true, json: async () => input.result};
        }, {error: error => errors.push(String(error))});
    if (listener) await listener({preventDefault() {}, target: {me: {value: 'https://client.example/'}}});
    process.stdout.write(JSON.stringify({session: Object.fromEntries(session),
        local: Object.fromEntries(local), href: location.href, requests, errors}));
})().catch(error => { console.error(error); process.exitCode = 1; });
