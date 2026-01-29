import {Component, inject, OnDestroy, OnInit, signal} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {ActivatedRoute, RouterLink} from '@angular/router';
import {Game} from '../core/models/models';
import {GamesService} from '../core/services/misc-hateoas-models.service';
import {NavService} from '../core/services/nav.service';
import {MatButtonModule} from '@angular/material/button';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatSelectModule} from '@angular/material/select';
import {MatInputModule} from '@angular/material/input';
import {GameEditCutsComponent} from './game-edit-cuts/game-edit-cuts';

@Component({
  selector: 'app-game-edit',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatSelectModule,
    MatInputModule,
    GameEditCutsComponent,
    RouterLink,
  ],
  templateUrl: './game-edit.html',
  styleUrl: './game-edit.css',
})
export class GameEditComponent implements OnInit, OnDestroy {
  game = signal<Game | null>(null);
  nameDraft = signal('');
  proxyQuality = signal<'low' | 'medium' | 'high'>('medium');

  private route = inject(ActivatedRoute);
  private gamesService = inject(GamesService);
  private navService = inject(NavService);

  ngOnInit(): void {
    this.route.queryParamMap.subscribe((params) => {
      const url = params.get('url');
      if (!url) return;

      this.gamesService.get(url).subscribe({
        next: (game) => {
          this.game.set(game);
          this.nameDraft.set(game.name ?? '');
          this.updateNav(game);
        },
        error: (e) => console.error('Erreur lors du chargement du match', e),
      });
    });
  }

  ngOnDestroy(): void {
    this.navService.clear();
  }

  onSaveName(): void {
    const current = this.game();
    if (!current) return;
    const nextName = this.nameDraft().trim();
    if (!nextName || nextName === current.name) return;

    this.gamesService.update(current, {name: nextName}).subscribe({
      next: (game) => {
        this.game.set(game);
        this.nameDraft.set(game.name ?? '');
      },
      error: (e) => console.error('Erreur lors de la sauvegarde du nom', e),
    });
  }

  onGenerateProxy(): void {
    const current = this.game();
    if (!current) return;
    this.gamesService.generateProxy(current, {quality: this.proxyQuality()}).subscribe({
      next: () => {},
      error: (e) => console.error('Erreur lors de la génération du proxy', e),
    });
  }

  onQueueProxy(): void {
    const current = this.game();
    if (!current) return;
    this.gamesService
      .generateProxy(current, {quality: this.proxyQuality(), to_queue: true})
      .subscribe({
        next: () => {},
        error: (e) => console.error('Erreur lors de la mise en file du proxy', e),
      });
  }

  private updateNav(game: Game) {
    const tournamentUrl = game._links?.tournament?.href;
    if (!tournamentUrl) {
      this.navService.clear();
      return;
    }
    const embedded = game._embedded;
    const tournament = embedded?.['tournament'] as { name?: string } | undefined;
    const tournamentName = tournament?.name;
    const label = tournamentName ?? 'Tournoi';
    this.navService.setLinks([
      {
        label,
        routerLink: ['/tournament/video-editing'],
        queryParams: {url: tournamentUrl},
      },
    ]);
  }


}
