import '@testing-library/jest-dom/vitest'

// Node's own experimental global `localStorage` (gated behind
// --experimental-webstorage) can shadow jsdom's per-window implementation
// under Vitest, silently returning undefined instead of a working Storage.
// Force a real in-memory Storage so tests can rely on window.localStorage.
if (typeof window !== 'undefined') {
  class MemoryStorage {
    #store = new Map()

    get length() {
      return this.#store.size
    }

    getItem(key) {
      return this.#store.has(key) ? this.#store.get(key) : null
    }

    setItem(key, value) {
      this.#store.set(String(key), String(value))
    }

    removeItem(key) {
      this.#store.delete(key)
    }

    clear() {
      this.#store.clear()
    }

    key(index) {
      return [...this.#store.keys()][index] ?? null
    }
  }

  try {
    Object.defineProperty(window, 'localStorage', {
      value: new MemoryStorage(),
      configurable: true,
      writable: true,
    })
  } catch {
    // If the environment refuses to redefine it, tests relying on
    // localStorage will surface that failure directly.
  }
}
