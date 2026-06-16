// TypeScript
import {AfterViewInit, Component, inject, OnDestroy, OnInit, signal, ViewChild,} from '@angular/core';
import {ActivatedRoute, Router} from '@angular/router';

import {MatTableDataSource, MatTableModule} from '@angular/material/table';
import {MatSort, MatSortModule} from '@angular/material/sort';
import {TournamentService} from '../core/services/tournament.service';
import {Game, Team, Tournament, Video, VideoMetadata,} from '../core/models/models';
import {of} from 'rxjs';
import {MatButtonModule} from '@angular/material/button';
import {MatInputModule} from '@angular/material/input';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatCheckboxModule} from '@angular/material/checkbox';
import {MatSelectModule} from '@angular/material/select';
import {FormsModule} from '@angular/forms';
import {GamesService} from '../core/services/misc-hateoas-models.service';
import {NavService} from '../core/services/nav.service';

@Component({
  selector: 'app-tournament-edit-games-view',
  imports: [
    FormsModule,
    MatTableModule,
    MatSortModule,
    MatButtonModule,
    MatInputModule,
    MatCheckboxModule,
    MatFormFieldModule,
    MatSelectModule,
  ],
  templateUrl: './tournament-edit-games-view.html',
  styleUrl: './tournament-edit-games-view.css',
})
export class TournamentEditGamesView
  implements OnInit, AfterViewInit, OnDestroy
{
  tournament = signal<Tournament | null>(null);
  games = signal<Game[]>([]);
  videos = signal<Record<string, Video>>({});
  team1_names = signal<Record<string, string>>({});
  team2_names = signal<Record<string, string>>({});
  cuts_count = signal<Record<number, number>>({});
  sourceFiles = signal<string[]>([]);
  selectedSourceFiles = signal<string[]>([]);
  dataSource = new MatTableDataSource<Game>([]);
  proxyQuality = signal<'low' | 'medium' | 'high'>('medium');
  newGameName = '';
  selectedSourceFile = '';
  sourceFilePreviewUrl = '';
  @ViewChild(MatSort) sort!: MatSort;
  protected readonly Object = Object;
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private tournamentService = inject(TournamentService);
  private GameService = inject(GamesService);
  private navService = inject(NavService);

  /**
   * Initializes by reading the tournament URL and loading its videos.
   * Includes basic error handling for both tournament and videos fetch.
   */
  ngOnInit(): void {
    const tournament_url = this.route.snapshot.queryParamMap.get('url');
    if (!tournament_url) return;

    // Load the tournament, then its videos (with error handling)
    this.tournamentService.get(tournament_url).subscribe({
      next: (current_tournament: Tournament | null) => {
        if (!current_tournament) return;
        this.tournament.set(current_tournament);
        this.updateNav(tournament_url);
        this.resetCreateGameForm();
        this.tournament_loaded(current_tournament);
        this.loadSourceFiles(current_tournament);
      },
      error: (e) => {
        console.error('Erreur lors de la récupération du tournoi', e);
        return of(null);
      },
    });
    // videos() uses follow() and returns Observable<VideoMetadata[]>
  }

  ngOnDestroy(): void {
    this.navService.clear();
  }

  ngAfterViewInit(): void {
    this.dataSource.sort = this.sort;
    this.dataSource.sortingDataAccessor = (item, property) => {
      switch (property) {
        case 'teams': {
          const team1 = this.team1_names()[item.pk] ?? '';
          const team2 = this.team2_names()[item.pk] ?? '';
          return `${team1} vs ${team2}`.toLowerCase();
        }
        case 'proxy':
          return Object.keys(this.videos()[item.pk].files ?? {}).length > 0
            ? 1
            : 0;

        case 'file_name': {
          const sourceName = (item as unknown as { source_name?: string })
            .source_name;
          return sourceName?.toLowerCase() ?? item.files?.toLowerCase() ?? '';
        }
        case 'name':
          return item.name?.toLowerCase() ?? '';
        case 'cuts':
          return this.cuts_count()[item.pk] ?? 0;
        default:
          return (
            (item as unknown as Record<string, string | number>)[property] ?? ''
          );
      }
    };
  }

  /**
   * Triggers the 'generate_gamse' action on a tournament.
   *
   */
  onGenerateGames(): void {
    const tournament = this.tournament();
    if (!tournament) return;
    this.tournamentService.generate_games(tournament, {}).subscribe({
      next: () => {},
      error: (e) => {
        console.error('Erreur lors de la génération des matchs', e);
      },
    });
  }

  onSourceFileSelected(filename: string): void {
    this.selectedSourceFile = filename;
    const tournament = this.tournament();
    if (!tournament || !filename) {
      this.sourceFilePreviewUrl = '';
      return;
    }
    this.sourceFilePreviewUrl = this.tournamentService.sourceFileUrl(
      tournament,
      filename,
    );
  }

  onAddSourceFile(): void {
    const filename = this.selectedSourceFile.trim();
    if (!filename) return;
    const current = this.selectedSourceFiles();
    if (current.includes(filename)) return;
    this.selectedSourceFiles.set([...current, filename]);
  }

  onRemoveSourceFile(filename: string): void {
    this.selectedSourceFiles.set(
      this.selectedSourceFiles().filter((item) => item !== filename),
    );
  }

  onCreateGame(): void {
    const tournament = this.tournament();
    if (!tournament) return;

    const newGameName = this.newGameName.trim();
    const files = this.selectedSourceFiles();

    this.tournamentService
      .create_game(tournament, {
        name: newGameName,
        files: files,
      })
      .subscribe({
        next: () => {
          this.resetCreateGameForm();
          this.tournament_loaded(tournament);
          this.loadSourceFiles(tournament);
        },
        error: (e) => {
          console.error('Erreur lors de la création du match', e);
        },
      });
  }

  onGenerateAllProxy(): void {
    const items = this.games();
    if (!items.length) return;
    const quality = this.proxyQuality();
    items.forEach((game) => {
      this.GameService.generateProxy(game, { quality }).subscribe({
        next: () => {},
        error: (e) => {
          console.error(
            `Erreur lors de la génération du proxy pour ${game.pk}`,
            e,
          );
        },
      });
    });
  }

  onQueueAllProxy(): void {
    const items = this.games();
    if (!items.length) return;
    const quality = this.proxyQuality();
    items.forEach((game) => {
      this.GameService.generateProxy(game, {
        quality,
        to_queue: true,
      }).subscribe({
        next: () => {},
        error: (e) => {
          console.error(
            `Erreur lors de la mise en file du proxy pour ${game.pk}`,
            e,
          );
        },
      });
    });
  }

  openGameEdit(game: Game): void {
    const url = game?._links?.self?.href;
    if (!url) return;
    this.router.navigate(['/game-edit'], {
      queryParams: { url },
    });
  }

  /*
   * loads viedos datas after the tournaent is loaded
   *
   * @param tournament - The tournament to load videos for.
   * */
  private tournament_loaded(tournament: Tournament): void {
    this.tournamentService.games(tournament, true).subscribe({
      next: (games: Game[]) => {
        this.games.set(games);
        this.dataSource.data = games;
        games.forEach((v) => this.loadTeamsNames(v));
        games.forEach((v) => this.loadCutsCount(v));
        games.forEach((v) => this.loadProxy(v));

        // Load team names and status for each video, and the miniature
        //videos.forEach(v => this.Action(v));
      },

      error: (e) => {
        console.error('Erreur lors du chargement des vidéos', e);
        return of([] as VideoMetadata[]);
      },
    });
  }

  private loadSourceFiles(tournament: Tournament): void {
    this.tournamentService.source_files(tournament, true).subscribe({
      next: (files: string[]) => {
        this.sourceFiles.set(files);
        if (!files.length) {
          this.onSourceFileSelected('');
          return;
        }
        if (
          this.selectedSourceFile &&
          files.includes(this.selectedSourceFile)
        ) {
          this.onSourceFileSelected(this.selectedSourceFile);
          return;
        }
        this.onSourceFileSelected(files[0]);
      },
      error: (e) => {
        console.error('Erreur lors du chargement des fichiers source', e);
      },
    });
  }

  /**
   * Resolves and stores Team 1 and Team 2 names for a given video.
   *
   * @param game - The video metadata entry.
   */
  private loadTeamsNames(game: Game): void {
    this.GameService.team1(game).subscribe({
      next: (team1: Team) => {
        const next1 = { ...this.team1_names() };
        next1[game.pk] = team1.name;
        this.team1_names.set(next1);
        this.dataSource.data = [...this.dataSource.data];
      },
      error: (e) => {
        console.error(`Erreur team1 pour video ${game.pk}`, e);
      },
    });
    this.GameService.team2(game).subscribe({
      next: (team2: Team) => {
        const next2 = { ...this.team2_names() };
        next2[game.pk] = team2.name;
        this.team2_names.set(next2);
        this.dataSource.data = [...this.dataSource.data];
      },
      error: (e) => {
        console.error(`Erreur team2 pour video ${game.pk}`, e);
      },
    });
  }

  private loadCutsCount(game: Game): void {
    this.GameService.cuts(game).subscribe({
      next: (cuts) => {
        const nextCounts = { ...this.cuts_count() };
        nextCounts[game.pk] = Array.isArray(cuts) ? cuts.length : 0;
        this.cuts_count.set(nextCounts);
        this.dataSource.data = [...this.dataSource.data];
      },
      error: (e) => {
        console.error(`Erreur cuts pour video ${game.pk}`, e);
      },
    });
  }

  private loadProxy(game: Game): void {
    this.GameService.proxy_video(game).subscribe({
      next: (video) => {
        const next1 = { ...this.videos() };
        next1[game.pk] = video;
        this.videos.set(next1);
        this.dataSource.data = [...this.dataSource.data];
      },
      error: (e) => {
        console.error(`Erreur video pour video ${game.pk}`, e);
      },
    });
  }

  private updateNav(tournamentUrl: string): void {
    this.navService.setLinks([
      {
        label: 'Miniature edit',
        routerLink: ['/tournament/games'],
        queryParams: { url: tournamentUrl },
      },
    ]);
    this.navService.setActions([
      {
        label: 'Update games',
        onClick: () => this.onGenerateGames(),
      },
    ]);
  }

  private resetCreateGameForm(): void {
    this.newGameName = '';
    this.selectedSourceFile = '';
    this.selectedSourceFiles.set([]);
    this.sourceFilePreviewUrl = '';
    this.sourceFiles.set([]);
  }
}
