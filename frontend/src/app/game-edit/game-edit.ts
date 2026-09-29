import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  OnDestroy,
  OnInit,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { Game, Team } from '../core/models/models';
import {
  GamesService,
  TeamService,
} from '../core/services/misc-hateoas-models.service';
import { NavService } from '../core/services/nav.service';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { GameEditCutsComponent } from './game-edit-cuts/game-edit-cuts';
import { TeamSelectComponent } from '../game-miniature/team-select/team-select';
import { TeamCreateComponent } from './team-create/team-create';
import { formatSetScores, pairStartScore, parseSetScores } from './scoreboard';
import { GAME_NUMBER_MAX, gameNumber, numberPart } from './game-number';

@Component({
  selector: 'app-game-edit',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    GameEditCutsComponent,
    TeamSelectComponent,
    TeamCreateComponent,
  ],
  templateUrl: './game-edit.html',
  styleUrl: './game-edit.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GameEditComponent implements OnInit, OnDestroy {
  game = signal<Game | null>(null);
  nameDraft = signal('');

  teams = signal<Team[]>([]);
  team1Draft = signal<string | null>(null);
  team2Draft = signal<string | null>(null);
  conditionDraft = signal('');
  setsToWinDraft = signal<number | null>(null);
  /** Scores de depart tels qu'on les tape : `10-3`, un tiret par set. */
  startTeam1Draft = signal('');
  startTeam2Draft = signal('');
  /** Terrain, jour et game dans la journee : le numero TTJGG du match. */
  fieldNumberDraft = signal<number | null>(null);
  dayNumberDraft = signal<number | null>(null);
  gameNumberDraft = signal<number | null>(null);
  winConditionDraft = signal('');
  /** Le numero tel qu'il ouvrira le nom des rendus. */
  numberPreview = computed(() =>
    gameNumber(
      this.fieldNumberDraft(),
      this.dayNumberDraft(),
      this.gameNumberDraft(),
    ),
  );
  readonly numberMax = GAME_NUMBER_MAX;
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
          this.resetDrafts(game);
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

    const sets = Number(this.setsToWinDraft());
    const payload = {
      name: nextName,
      team1: this.team1Draft(),
      team2: this.team2Draft(),
      condition: this.conditionDraft().trim(),
      sets_to_win: Number.isInteger(sets) && sets > 0 ? sets : null,
      start_score:
        pairStartScore(
          parseSetScores(this.startTeam1Draft()),
          parseSetScores(this.startTeam2Draft()),
        ) ?? null,
      field_number: numberPart(this.fieldNumberDraft(), GAME_NUMBER_MAX.field),
      day_number: numberPart(this.dayNumberDraft(), GAME_NUMBER_MAX.day),
      game_number: numberPart(this.gameNumberDraft(), GAME_NUMBER_MAX.game),
      win_condition: this.winConditionDraft().trim(),
    };

    this.gamesService.update(current, payload).subscribe({
      next: (game) => {
        this.game.set(game);
        this.resetDrafts(game);
      },
      error: (e) => console.error('Erreur lors de la sauvegarde du nom', e),
    });
  }

  /**
   * Echange les deux equipes et enregistre dans la foulee.
   *
   * L'ordre n'est pas cosmetique : l'equipe 1 est celle qui commence a
   * gauche, donc c'est elle qui recoit un point marque `left`. Se tromper
   * d'ordre inverse tout le tableau de score du montage, et on ne s'en
   * apercoit qu'en regardant la video entiere.
   */
  /**
   * Ajoute l'equipe tout juste creee a la liste et la place du cote ou on l'a
   * creee. Rien n'est enregistre sur la game avant « Save », comme pour un
   * choix d'equipe dans la liste.
   */
  onTeamCreated(slot: 1 | 2, team: Team): void {
    this.teams.set(
      [...this.teams(), team].sort((a, b) =>
        (a.name ?? '').localeCompare(b.name ?? ''),
      ),
    );
    const href = team._links?.self?.href ?? null;
    (slot === 1 ? this.team1Draft : this.team2Draft).set(href);
  }

  onSwapTeams(): void {
    const team1 = this.team1Draft();
    this.team1Draft.set(this.team2Draft());
    this.team2Draft.set(team1);
    // Le score de depart appartient aux equipes, pas aux cotes : il suit.
    const start1 = this.startTeam1Draft();
    this.startTeam1Draft.set(this.startTeam2Draft());
    this.startTeam2Draft.set(start1);
    this.onSaveNameTeam();
  }

  /**
   * Complete l'equipe qui a le moins de sets par des zeros a droite, a la
   * sortie du champ : pendant la frappe, `10-` deviendrait `10-0` avant qu'on
   * ait tape le 3.
   */
  padStartScores(): void {
    const start = pairStartScore(
      parseSetScores(this.startTeam1Draft()),
      parseSetScores(this.startTeam2Draft()),
    );
    this.startTeam1Draft.set(formatSetScores(start?.team1));
    this.startTeam2Draft.set(formatSetScores(start?.team2));
  }

  /** Remet les champs sur ce que la game enregistree dit. */
  private resetDrafts(game: Game): void {
    this.nameDraft.set(game.name ?? '');
    this.team1Draft.set(game._links?.team1?.href ?? null);
    this.team2Draft.set(game._links?.team2?.href ?? null);
    this.conditionDraft.set(game.condition ?? '');
    this.setsToWinDraft.set(game.sets_to_win ?? null);
    this.startTeam1Draft.set(formatSetScores(game.start_score?.team1));
    this.startTeam2Draft.set(formatSetScores(game.start_score?.team2));
    this.fieldNumberDraft.set(game.field_number ?? 0);
    this.dayNumberDraft.set(game.day_number ?? 0);
    this.gameNumberDraft.set(game.game_number ?? 0);
    this.winConditionDraft.set(game.win_condition ?? '');
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
