import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { I18nProvider } from '../i18n';
import { LetteringChoice } from '../components/wizard/LetteringChoice';

async function openDetails(user: ReturnType<typeof userEvent.setup>) {
  const details = screen.getByText('Compare in detail').closest('details')!;
  await user.click(screen.getByText('Compare in detail'));
  // jsdom does not toggle <details> on summary clicks; mirror the browser.
  if (!details.open) { details.open = true; fireEvent(details, new Event('toggle')); }
}

describe('lettering choice', () => {
  it('leads with each option’s strengths, cost and fit, and states permanence once', async () => {
    const user = userEvent.setup();
    const choose = vi.fn();
    render(<I18nProvider><LetteringChoice value={null} onChange={choose} disabled={false} /></I18nProvider>);
    expect(screen.getAllByRole('radio').every(el => !(el as HTMLInputElement).checked)).toBe(true);
    const editable = screen.getByRole('radio', { name: /Editable lettering/ });
    expect(editable.getAttribute('aria-describedby')).toBe('lettering-editable-details');
    expect(document.getElementById('lettering-editable-details')?.textContent).toContain('Fix typos or rewrite lines instantly, without credits');
    expect(screen.getAllByRole('img', { name: /out of 5/ }).map(meter => meter.getAttribute('aria-label'))).toEqual(['5 out of 5', '1 out of 5', '3 out of 5', '5 out of 5']);
    expect(document.getElementById('lettering-integrated-details')?.textContent).toContain('Changing a word means redrawing the page');
    expect(screen.getByText('This choice is permanent for this project.')).toBeTruthy();
    expect(screen.getByText(/Not sure\? Choose editable lettering/)).toBeTruthy();
    // The detailed comparison stays out of the way until asked for.
    expect(screen.queryByText('What this means for your book')).toBeNull();
    await user.click(screen.getByRole('radio', { name: /Integrated lettering/ }));
    expect(choose).toHaveBeenCalledWith('integrated');
  });

  it('compares sound, captions and translation on the same real pages', async () => {
    const user = userEvent.setup();
    render(<I18nProvider><LetteringChoice value={null} onChange={vi.fn()} disabled={false} /></I18nProvider>);
    const choices = () => screen.getAllByRole('img').filter(image => image.tagName === 'IMG').map(image => image.getAttribute('src'));
    expect(choices()).toEqual(['/lettering-comparison/dcc-3-integrated.webp', '/lettering-comparison/dcc-3-editable.webp']);
    await user.click(screen.getByRole('button', { name: 'Translation' }));
    expect(choices()).toEqual(['/lettering-comparison/cthulhu-26-integrated.webp', '/lettering-comparison/cthulhu-26-editable-es.webp']);
    await user.click(screen.getByRole('button', { name: 'Captions' }));
    expect(screen.getAllByRole('img', { name: /movable speech balloon/ })[0].getAttribute('src')).toBe('/lettering-comparison/cthulhu-26-editable.webp');
  });

  it('keeps the full comparison available on request and discloses preparation', async () => {
    const user = userEvent.setup();
    const choose = vi.fn();
    render(<I18nProvider><LetteringChoice value='integrated' onChange={choose} disabled={false} /></I18nProvider>);
    await openDetails(user);
    expect(screen.getByText(/Prepared comparison:/).textContent).toContain('not an automatic conversion');
    expect(screen.getByText('What this means for your book')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Sound & motion' }));
    const comparison = within(screen.getByRole('region', { name: 'See the difference on a real page' }));
    const sources = () => comparison.getAllByRole('img').map(image => image.getAttribute('src'));
    expect(sources()).toEqual(['/lettering-comparison/dcc-3-integrated.webp', '/lettering-comparison/dcc-3-editable.webp']);
    await user.click(screen.getByRole('button', { name: 'Compare close-ups' }));
    await user.click(screen.getByRole('button', { name: 'LEAP in motion' }));
    await user.click(screen.getByRole('checkbox', { name: 'Hide the editable lettering layer' }));
    expect(sources()).toEqual(['/lettering-comparison/dcc-3-integrated.webp', '/lettering-comparison/dcc-3-base.webp']);
    expect(comparison.getByRole('status').textContent).toContain('Integrated lettering cannot be switched off');
    expect(choose).not.toHaveBeenCalled();
    expect((screen.getByRole('radio', { name: /Integrated lettering/ }) as HTMLInputElement).checked).toBe(true);
  });

  it('keeps the decision usable if a sample fails to load', async () => {
    const user = userEvent.setup();
    render(<I18nProvider><LetteringChoice value='editable' onChange={vi.fn()} disabled={true} /></I18nProvider>);
    await openDetails(user);
    fireEvent.error(within(screen.getByRole('region', { name: 'See the difference on a real page' })).getAllByRole('img')[0]);
    expect(screen.getByText(/This sample could not load/)).toBeTruthy();
    expect((screen.getByRole('radio', { name: /Editable lettering/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole('radio', { name: /Editable lettering/ }).closest('fieldset')?.disabled).toBe(true);
  });
});
