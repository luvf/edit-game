import {Component, inject, OnInit, signal} from '@angular/core';
import {TournamentService} from '../features/tournaments/tournament';
import {Tournament} from '../features/tournaments/tournament.model';
import {Router} from '@angular/router';

/**
 * Container view that lists tournaments and provides actions per tournament.
 *
 * Responsibilities:
 * - Load tournaments from the API (HATEOAS collection).
 * - Display counts of related games per tournament.
 * - Trigger domain actions such as syncing videos or updating YouTube data.
 * - Navigate to the tournament games view.
 */

@Component({
  selector: 'app-tournaments_view',
  templateUrl: './tournament-view.component.html',
  styleUrl: './tournament-view.component.css',
})
export class TournamentViewComponent implements OnInit {
  tournaments = signal<Tournament []>([]);
  counts = signal<Record<string, number>>({});

  private tournamentService = inject(TournamentService);
  private router = inject(Router);


  /**
   * Initializes the component by loading the tournaments list.
   *
   * Note: HateoasService.list returns Observable<Tournament[]> based on the provided implementation.
   */
  ngOnInit(): void {
    // Load the list (HateoasService.list returns Observable<Tournament[]> in the proposed implementation)
    this.tournamentService.list().subscribe({
      next: (data: Tournament[]) => {
        this.tournaments.set(data);
        data.forEach(t => this.loadGamesCount(t));
      },
      error: (e) => {
        console.error('Erreur lors du chargement des tournois', e);
      },
    });
  }


  /**
   * Triggers the 'sync_videos' action on a tournament.
   *
   * @param tournament - Target tournament.
   */
  onSyncVideos(tournament: Tournament): void {
    this.tournamentService.syncVideos(tournament, {}).subscribe({
      next: () => {
      },
      error: (e) => {
        console.error('sync_videos failed', e);
      }
    });
  }

  /**
   * Triggers the 'youtube_update' action on a tournament.
   *
   * @param tournament - Target tournament.
   */
  onYoutubeUpdate(tournament: Tournament): void {
    this.tournamentService.youtubeUpdate(tournament, {}).subscribe({
      next: () => {
      },
      error: (e) => {
        console.error('youtube_update failed', e);
      }
    });
  }

  /**
   * Navigates to the tournament games view using the tournament self link.
   *
   * @param tournament - Tournament to open.
   */
  openTournamentGames(tournament: Tournament): void {
    if (!tournament?._links?.self) return;
    this.router.navigate(['/tournament/games'], {
      queryParams: {url: tournament._links.self.href},
    });
  }

  /**
   * Loads the number of games for a given tournament and updates the counts map.
   *
   * @param tournament - Tournament for which the games count is requested.
   */
  private loadGamesCount(tournament: Tournament): void {
    // games() suit la relation 'games' et retourne un Observable<Game[]>
    this.tournamentService.games(tournament).subscribe({
      next: (games) => {
        const len = Array.isArray(games) ? games.length : 0;
        const next = {...this.counts()};
        next[tournament.pk] = len;
        this.counts.set(next);
      },
      error: (e) => {
        console.error(`Erreur lors du chargement des jeux pour tournament ${tournament.pk}`, e);
      }
    });
  }
}

