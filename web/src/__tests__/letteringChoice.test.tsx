import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { I18nProvider } from '../i18n';
import { LetteringChoice } from '../components/wizard/LetteringChoice';

describe('lettering comparison', () => {
  it('keeps sample exploration separate from the project choice and discloses preparation', async () => {
    const user = userEvent.setup();
    const choose = vi.fn();
    render(<I18nProvider><LetteringChoice value={null} onChange={choose} disabled={false} /></I18nProvider>);
    expect(screen.getAllByRole('radio').every(el => !(el as HTMLInputElement).checked)).toBe(true);
    expect(screen.getByText(/Prepared comparison:/).textContent).toContain('not an automatic conversion');
    await user.click(screen.getByRole('button', { name: 'Two speakers' }));
    await user.click(screen.getByRole('button', { name: 'Compare close-ups' }));
    const links = within(screen.getByRole('region', { name: 'See the difference on a real page' })).getAllByRole('link', { name: /Open full-size sample/ });
    expect(links.map(el => el.getAttribute('href'))).toEqual(['/lettering-comparison/cthulhu-25-integrated.webp', '/lettering-comparison/cthulhu-25-editable.webp']);
    expect(choose).not.toHaveBeenCalled();
    Element.prototype.scrollIntoView = vi.fn();
    await user.click(screen.getByRole("button", { name: "Choose lettering" }));
    expect(document.activeElement).toBe(screen.getByRole("radio", { name: /Integrated lettering/ }));
    await user.click(screen.getByRole('radio', { name: /Integrated lettering/ }));
    expect(choose).toHaveBeenCalledWith('integrated');
  });

  it('keeps the decision usable if a sample fails to load', () => {
    render(<I18nProvider><LetteringChoice value='editable' onChange={vi.fn()} disabled={true} /></I18nProvider>);
    fireEvent.error(screen.getAllByRole('img')[0]);
    expect(screen.getByText(/This sample could not load/)).toBeTruthy();
    expect(screen.getByText('What this means for your book')).toBeTruthy();
    expect((screen.getByRole('radio', { name: /Editable lettering/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole('radio', { name: /Editable lettering/ }).closest('fieldset')?.disabled).toBe(true);
  });

  it('shows the DCC effects and reveals only the editable artwork without changing the choice', async () => {
    const user = userEvent.setup();
    const choose = vi.fn();
    render(<I18nProvider><LetteringChoice value='integrated' onChange={choose} disabled={false} /></I18nProvider>);
    await user.click(screen.getByRole('button', { name: 'Sound & motion' }));
    const comparison = within(screen.getByRole('region', { name: 'See the difference on a real page' }));
    const sources = () => comparison.getAllByRole('img').map(image => image.getAttribute('src'));
    expect(sources()).toEqual(['/lettering-comparison/dcc-3-integrated.webp', '/lettering-comparison/dcc-3-editable.webp']);
    expect(comparison.getByText(/The editable version uses Bangers/)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Compare close-ups' }));
    await user.click(screen.getByRole('button', { name: 'LEAP in motion' }));
    expect(screen.getByRole('button', { name: 'LEAP in motion' }).getAttribute('aria-pressed')).toBe('true');
    await user.click(screen.getByRole('checkbox', { name: 'Hide the editable lettering layer' }));
    expect(sources()).toEqual(['/lettering-comparison/dcc-3-integrated.webp', '/lettering-comparison/dcc-3-base.webp']);
    expect(comparison.getByRole('status').textContent).toContain('Integrated lettering cannot be switched off');
    await user.click(screen.getByRole('button', { name: 'Narration & detail' }));
    expect(sources()).toEqual(['/lettering-comparison/cthulhu-26-integrated.webp', '/lettering-comparison/cthulhu-26-base.webp']);
    await user.click(screen.getByRole('checkbox', { name: 'Hide the editable lettering layer' }));
    expect(sources()[1]).toBe('/lettering-comparison/cthulhu-26-editable.webp');
    expect(choose).not.toHaveBeenCalled();
    expect((screen.getByRole('radio', { name: /Integrated lettering/ }) as HTMLInputElement).checked).toBe(true);
  });
});
