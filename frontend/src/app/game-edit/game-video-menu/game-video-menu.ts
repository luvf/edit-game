import {
  ChangeDetectionStrategy,
  Component,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { MatButtonModule } from '@angular/material/button';
import { Game } from '../../core/models/models';
import { GamesService } from '../../core/services/misc-hateoas-models.service';
import { renderPresets } from '../../core/services/preset-service';

/**
 * Le menu Video d'un match : generer le proxy dans une qualite, creer
 * l'archive. Pose sous le lecteur, a cote du choix de qualite de lecture :
 * c'est la que l'on remarque qu'il manque une qualite.
 */
@Component({
  selector: 'app-game-video-menu',
  standalone: true,
  imports: [FormsModule, OverlayModule, MatButtonModule],
  templateUrl: './game-video-menu.html',
  styleUrl: './game-video-menu.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GameVideoMenuComponent {
  readonly game = input<Game | null | undefined>(null);

  readonly open = signal(false);
  /** Ce que la derniere demande a donne, affiche dans le menu. */
  readonly message = signal<{ text: string; error: boolean } | null>(null);
  proxyQuality = signal<'low' | 'medium' | 'high'>('medium');

  protected readonly renderPresets = renderPresets;
  /** Cale sur le bord droit du bouton : le lecteur finit a droite. */
  protected readonly positions: ConnectedPosition[] = [
    {
      originX: 'end',
      originY: 'bottom',
      overlayX: 'end',
      overlayY: 'top',
      offsetY: 8,
    },
    {
      originX: 'end',
      originY: 'top',
      overlayX: 'end',
      overlayY: 'bottom',
      offsetY: -8,
    },
  ];

  private gamesService = inject(GamesService);

  toggle(): void {
    this.open.set(!this.open());
    this.message.set(null);
  }

  close(): void {
    this.open.set(false);
  }

  /** Met le proxy en file de rendu, dans la qualite choisie. */
  onGenerateProxy(): void {
    const current = this.game();
    if (!current) return;
    const quality = this.proxyQuality();
    const label =
      renderPresets.find((preset) => preset.value === quality)?.label ??
      quality;
    this.gamesService.generateProxy(current, { quality }).subscribe({
      next: () =>
        this.message.set({
          text: `Proxy ${label} ajouté à la file de rendu.`,
          error: false,
        }),
      error: (e) => {
        console.error('Erreur lors de la génération du proxy', e);
        this.message.set({
          text: e?.error?.error ?? 'Génération du proxy impossible.',
          error: true,
        });
      },
    });
  }

  /**
   * Met l'archive en file de rendu. Le serveur refuse s'il y en a deja une
   * (409) : son message le dit, et c'est lui qu'on affiche.
   */
  onCreateArchive(): void {
    const current = this.game();
    if (!current) return;
    this.gamesService.create_archive(current).subscribe({
      next: (response: unknown) =>
        this.message.set({
          text:
            (response as { detail?: string } | null)?.detail ??
            'Archive ajoutée à la file de rendu.',
          error: false,
        }),
      error: (e) => {
        console.error("Erreur lors de la création de l'archive", e);
        this.message.set({
          text: e?.error?.detail ?? "Création de l'archive impossible.",
          error: true,
        });
      },
    });
  }
}
