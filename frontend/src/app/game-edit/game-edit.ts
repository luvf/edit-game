import {Component, inject, OnDestroy, OnInit, signal} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {ActivatedRoute} from '@angular/router';
import {Game, Team} from '../core/models/models';
import {GamesService, TeamService,} from '../core/services/misc-hateoas-models.service';
import {NavService} from '../core/services/nav.service';
import {MatButtonModule} from '@angular/material/button';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatSelectModule} from '@angular/material/select';
import {MatInputModule} from '@angular/material/input';
import {GameEditCutsComponent} from './game-edit-cuts/game-edit-cuts';
import {TeamSelectComponent} from '../game-miniature/team-select/team-select';
import {renderPresets} from '../core/services/preset-service';

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
    TeamSelectComponent,

  ],
  templateUrl: './game-edit.html',
  styleUrl: './game-edit.css',
})
export class GameEditComponent implements OnInit, OnDestroy {
  game = signal<Game | null>(null);
  nameDraft = signal('');
  proxyQuality = signal<'low' | 'medium' | 'high'>('medium');

  teams = signal<Team[]>([]);
  team1Draft = signal<string | null>(null);
  team2Draft = signal<string | null>(null);
  protected readonly renderPresets = renderPresets;
  private route = inject(ActivatedRoute);
  private gamesService = inject(GamesService);
  private navService = inject(NavService);
  private teamService = inject(TeamService);

  ngOnInit(): void {
    this.route.queryParamMap.subscribe((params) => {
      const url = params.get('url');
      if (!url) return;

      this.teamService.list().subscribe({
        next: (teams) => this.teams.set(teams),
        error: (e) => console.error('Erreur lors du chargement des équipes', e),
      });
      this.gamesService.get(url).subscribe({
        next: (game) => {
          this.game.set(game);
          this.nameDraft.set(game.name ?? '');
          this.team1Draft.set(game._links?.team1?.href ?? null);
          this.team2Draft.set(game._links?.team2?.href ?? null);
          this.updateNav(game);
        },
        error: (e) => console.error('Erreur lors du chargement du match', e),
      });
    });
  }

  ngOnDestroy(): void {
    this.navService.clear();
  }

  onSaveNameTeam(): void {
    const current = this.game();
    if (!current) return;
    const nextName = this.nameDraft().trim();
    //if (!nextName || nextName === current.name) return;

    const payload = {
      name: nextName,
      team1: this.team1Draft(),
      team2: this.team2Draft(),
    };

    this.gamesService.update(current, payload).subscribe({
      next: (game) => {
        this.game.set(game);
        this.nameDraft.set(game.name ?? '');
        this.team1Draft.set(game._links?.team1?.href ?? null);
        this.team2Draft.set(game._links?.team2?.href ?? null);
      },
      error: (e) => console.error('Erreur lors de la sauvegarde du nom', e),
    });
  }

  onGenerateProxy(): void {
    const current = this.game();
    if (!current) return;
    this.gamesService
      .generateProxy(current, { quality: this.proxyQuality() })
      .subscribe({
        next: () => {},
        error: (e) => console.error('Erreur lors de la génération du proxy', e),
      });
  }

  onQueueProxy(): void {
    const current = this.game();
    if (!current) return;
    this.gamesService
      .generateProxy(current, { quality: this.proxyQuality(), to_queue: true })
      .subscribe({
        next: () => {},
        error: (e) =>
          console.error('Erreur lors de la mise en file du proxy', e),
      });
  }

  onCreateArchive(): void {
    const current = this.game();
    if (!current) return;
    this.gamesService.create_archive(current).subscribe({
      next: () => {},
      error: (e) => console.error("Erreur lors de la création de l'archive", e),
    });
  }

  private updateNav(game: Game) {
    const tournamentUrl = game._links?.tournament?.href;
    if (!tournamentUrl) {
      this.navService.clear();
      return;
    }
    const embedded = game._embedded;
    const tournament = embedded?.['tournament'] as
      | { name?: string }
      | undefined;
    const tournamentName = tournament?.name;
    const label = tournamentName ?? 'Tournoi';
    this.navService.setLinks([
      {
        label,
        routerLink: ['/tournament/video-editing'],
        queryParams: { url: tournamentUrl },
      },
    ]);
  }
}
