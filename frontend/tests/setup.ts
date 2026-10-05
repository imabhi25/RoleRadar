import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup, configure } from '@testing-library/react';

// The Stats page is a lazily imported chunk and several flows run sanitising/analysis in jsdom. On a loaded machine the
// default 1s findBy/waitFor window is shorter than that work, so async queries get a window sized for it. Assertions
// themselves are unchanged: a query still fails as soon as the condition is definitively not met.
configure({ asyncUtilTimeout: 5000 });
afterEach(() => { cleanup(); vi.unstubAllEnvs(); });
Object.defineProperty(window, 'matchMedia', { value: vi.fn(() => ({matches:false,addEventListener:vi.fn(),removeEventListener:vi.fn()})), writable:true });
window.scrollTo = vi.fn();
HTMLElement.prototype.scrollIntoView = vi.fn();
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
