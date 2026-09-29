import { DOCUMENT, Injectable, computed, inject, signal } from '@angular/core';

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'theme';

/**
 * Le theme affiche. Sans choix enregistre, on suit le systeme ; un clic sur le
 * bouton de la barre le fixe, et le choix survit au rechargement.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly document = inject(DOCUMENT);
  private readonly media = this.document.defaultView?.matchMedia(
    '(prefers-color-scheme: dark)',
  );
  private readonly systemDark = signal(this.media?.matches ?? false);
  private readonly chosen = signal<Theme | null>(readStoredTheme());

  readonly theme = computed<Theme>(
    () => this.chosen() ?? (this.systemDark() ? 'dark' : 'light'),
  );

  constructor() {
    this.media?.addEventListener('change', (event) =>
      this.systemDark.set(event.matches),
    );
  }

  toggle() {
    const next: Theme = this.theme() === 'dark' ? 'light' : 'dark';
    this.chosen.set(next);
    this.document.documentElement.dataset['theme'] = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Stockage indisponible : le choix vaut pour la session.
    }
  }
}

function readStoredTheme(): Theme | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === 'light' || stored === 'dark' ? stored : null;
  } catch {
    return null;
  }
}
