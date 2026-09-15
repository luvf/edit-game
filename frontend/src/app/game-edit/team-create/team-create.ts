import { Component, EventEmitter, Output, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { OverlayModule } from '@angular/cdk/overlay';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { Team } from '../../core/models/models';
import { TeamService } from '../../core/services/misc-hateoas-models.service';

/** Longueur maximale d'un nom court, celle du modele cote serveur. */
const SHORT_NAME_LENGTH = 10;

/**
 * Un nom court propose a partir du nom : les initiales des mots quand il y en
 * a plusieurs, sinon le debut du mot. Juste une proposition, modifiable.
 */
export function suggestShortName(name: string): string {
  const words = name
    .split(/[\s\-_'’.!]+/)
    .map((word) => word.trim())
    .filter(Boolean);
  if (words.length === 0) return '';
  if (words.length === 1) return words[0].slice(0, SHORT_NAME_LENGTH);
  return words
    .map((word) => word[0])
    .join('')
    .toUpperCase()
    .slice(0, SHORT_NAME_LENGTH);
}

/** Les erreurs de validation du serveur, en une ligne lisible. */
function describeError(error: any): string {
  const body = error?.error;
  if (body && typeof body === 'object') {
    const messages = Object.entries(body).map(
      ([field, value]) =>
        `${field} : ${Array.isArray(value) ? value.join(', ') : value}`,
    );
    if (messages.length) return messages.join(' — ');
  }
  return error?.message ? String(error.message) : 'Création impossible.';
}

/**
 * Un bouton « + » qui ouvre une bulle pour creer une equipe.
 *
 * Le logo est facultatif : une equipe sans logo en recoit un genere au rendu,
 * et celui-ci peut etre ajoute plus tard. Plus besoin d'une equipe fictive
 * dont on corrige le nom a la main.
 */
@Component({
  selector: 'app-team-create',
  standalone: true,
  imports: [
    FormsModule,
    OverlayModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
  ],
  templateUrl: './team-create.html',
  styleUrl: './team-create.css',
})
export class TeamCreateComponent {
  /** L'equipe creee, telle que le serveur l'a renvoyee. */
  @Output() created = new EventEmitter<Team>();

  protected readonly shortNameLength = SHORT_NAME_LENGTH;
  readonly open = signal(false);
  readonly pending = signal(false);
  readonly error = signal<string | null>(null);

  name = '';
  shortName = '';
  logo: File | null = null;

  private teamService = inject(TeamService);

  toggle(): void {
    this.open.set(!this.open());
    this.error.set(null);
  }

  close(): void {
    this.open.set(false);
  }

  /** Propose un nom court tant que personne n'en a tape un. */
  onNameChange(name: string): void {
    const previous = suggestShortName(this.name);
    this.name = name;
    if (!this.shortName || this.shortName === previous) {
      this.shortName = suggestShortName(name);
    }
  }

  onLogoSelected(event: Event): void {
    this.logo = (event.target as HTMLInputElement | null)?.files?.[0] ?? null;
  }

  create(): void {
    const name = this.name.trim();
    if (!name) {
      this.error.set("Le nom de l'équipe est obligatoire.");
      return;
    }
    const shortName = (this.shortName.trim() || suggestShortName(name)).slice(
      0,
      SHORT_NAME_LENGTH,
    );
    const form = new FormData();
    form.append('name', name);
    form.append('short_name', shortName);
    if (this.logo) form.append('image', this.logo);

    this.pending.set(true);
    this.error.set(null);
    this.teamService.post(form as unknown as Partial<Team>).subscribe({
      next: (team) => {
        this.pending.set(false);
        this.created.emit(team);
        this.name = '';
        this.shortName = '';
        this.logo = null;
        this.close();
      },
      error: (e) => {
        this.pending.set(false);
        this.error.set(describeError(e));
      },
    });
  }
}
