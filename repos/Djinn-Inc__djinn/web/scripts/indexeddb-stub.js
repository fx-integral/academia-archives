// No-op IndexedDB stub for the IPFS static build.
//
// Server-side prerender runs in Node where IndexedDB doesn't exist,
// but wagmi/walletconnect import it at module level. This stub gets
// injected via webpack ProvidePlugin so modules that reference
// `indexedDB` see this object instead of throwing ReferenceError.
//
// At runtime in the browser, the real IndexedDB is used (this stub
// only ships in the server compilation).

const noop = () => {};

const fakeRequest = {
  onsuccess: noop,
  onerror: noop,
  onupgradeneeded: noop,
  result: null,
  error: null,
};

const fakeDb = {
  close: noop,
  createObjectStore: () => ({
    add: () => fakeRequest,
    put: () => fakeRequest,
    get: () => fakeRequest,
    delete: () => fakeRequest,
    clear: () => fakeRequest,
    createIndex: noop,
  }),
  transaction: () => ({
    objectStore: () => ({
      add: () => fakeRequest,
      put: () => fakeRequest,
      get: () => fakeRequest,
      delete: () => fakeRequest,
      clear: () => fakeRequest,
    }),
    oncomplete: noop,
    onerror: noop,
  }),
  deleteObjectStore: noop,
  objectStoreNames: { contains: () => false, length: 0 },
};

const indexedDB = {
  open: () => {
    const req = { ...fakeRequest, result: fakeDb };
    setTimeout(() => req.onsuccess && req.onsuccess(), 0);
    return req;
  },
  deleteDatabase: () => fakeRequest,
  databases: () => Promise.resolve([]),
  cmp: () => 0,
};

module.exports = indexedDB;
module.exports.default = indexedDB;
