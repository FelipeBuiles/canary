import fs from 'node:fs';
import path from 'node:path';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderOverlay, resolvePage, type Measure } from '@lettering-engine';
import { I18nProvider } from '../i18n';
import LetteringDemo from '../components/wizard/LetteringDemo';

const measure: Measure = (text, _font, size, spacing = 0) => text.length * size * .45 + Math.max(0, text.length - 1) * spacing;
vi.mock('@lettering-engine', async original => ({ ...await original<typeof import('@lettering-engine')>(), canvasMeasure: () => measure }));

const samples = path.resolve(import.meta.dirname, '../../public/lettering-comparison');
const read = (name: string) => JSON.parse(fs.readFileSync(path.join(samples, name), 'utf8'));
const CROP = { x: 400, y: 450, width: 600, height: 277 };
// SVG lines concatenate without spaces, so compare words with whitespace removed.
const balloonWords = () => (document.querySelector('svg')?.textContent ?? '').replace(/\s/g, '');
const balloon = () => screen.getByRole('button', { name: /Speech balloon/ });

function renderDemo(autoplay = false) {
  return render(<I18nProvider><LetteringDemo crop={CROP} autoplay={autoplay} fallback={<p>Still sample</p>} /></I18nProvider>);
}

describe('lettering demo sample', () => {
  it('still lays out with the current engine in both languages', () => {
    // Breaking lettering schema changes must rebuild the shipped sample (scripts/build_lettering_comparison.py).
    const page = read('cthulhu-26.json'), style = read('style.json');
    for (const locale of ['source', 'es']) {
      const resolved = resolvePage({ ...page, locale }, style, measure);
      const speech = resolved.elements.find(element => element.id === 'lettering_0135')!;
      expect(speech.text_by_locale[locale]).toBeTruthy();
      expect(speech.resolved?.overflow).toBe(false);
      expect(renderOverlay(resolved, style)).toContain('<svg');
    }
  });
});

describe('lettering demo', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => read(path.basename(url)) })));
    Object.defineProperty(document, 'fonts', { configurable: true, value: { load: vi.fn(async () => []), check: () => true } });
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it('rewrites the balloon live and resets to the untouched sample', async () => {
    const user = userEvent.setup();
    renderDemo();
    await waitFor(() => expect(balloon()).toBeTruthy());
    expect(balloonWords()).toContain('I cannot recall'.replace(/\s/g, ''));
    balloon().focus();
    await user.keyboard('{Enter}');
    const field = screen.getByRole('textbox', { name: 'Words in the balloon' });
    await user.clear(field);
    await user.type(field, 'Did that statue blink?');
    expect(balloonWords()).toContain('Did that statue blink?'.replace(/\s/g, ''));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('textbox')).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(balloon()));
    await user.click(screen.getByRole('button', { name: 'Reset' }));
    expect(balloonWords()).toContain('I cannot recall'.replace(/\s/g, ''));
    expect(screen.queryByRole('button', { name: 'Reset' })).toBeNull();
  });

  it('translates onto the same artwork', async () => {
    const user = userEvent.setup();
    renderDemo();
    await waitFor(() => expect(balloon()).toBeTruthy());
    const art = screen.getByRole('img', { name: /movable speech balloon/ }).getAttribute('src');
    await user.click(within(screen.getByRole('group', { name: 'Sample language' })).getByRole('button', { name: 'ES' }));
    expect(balloonWords()).toContain('No recuerdo'.replace(/\s/g, ''));
    expect(screen.getByRole('img', { name: /movable speech balloon/ }).getAttribute('src')).toBe(art);
  });

  it('moves the balloon but keeps it inside the visible panel', async () => {
    renderDemo();
    await waitFor(() => expect(balloon()).toBeTruthy());
    const left = () => parseFloat(balloon().style.left);
    const start = left();
    fireEvent.keyDown(balloon(), { key: 'ArrowLeft' });
    expect(left()).toBeLessThan(start);
    for (let step = 0; step < 20; step++) fireEvent.keyDown(balloon(), { key: 'ArrowLeft', shiftKey: true });
    expect(left()).toBeCloseTo(100 * CROP.x / 1024, 5);
  });

  it('plays a scripted edit until the first touch', async () => {
    vi.useFakeTimers();
    renderDemo(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(50); });
    expect(screen.getByText('Move the balloon')).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByText('Rewrite the words')).toBeTruthy();
    fireEvent.keyDown(balloon(), { key: 'ArrowRight' });
    expect(screen.queryByText('Rewrite the words')).toBeNull();
    expect(balloonWords()).toContain('under my hands'.replace(/\s/g, ''));
    await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
    expect(screen.getByText('Drag the balloon · tap it to edit the words')).toBeTruthy();
  });

  it('keeps the still sample when the demo cannot load', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false })));
    renderDemo();
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText('Still sample')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Speech balloon/ })).toBeNull();
  });
});
