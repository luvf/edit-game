import {AfterViewInit, Component, inject, OnInit, signal, ViewChild} from '@angular/core';
import {Router} from '@angular/router';
import {Tournament} from '../core/models/models';
import {TournamentService} from '../core/services/tournament.service';
import {MatTableDataSource, MatTableModule} from '@angular/material/table';
import {MatSort, MatSortModule} from '@angular/material/sort';

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
    imports: [MatTableModule, MatSortModule],

  styleUrl: './tournament-view.component.css',
})
export class TournamentViewComponent implements OnInit, AfterViewInit {
  tournaments = signal<Tournament []>([]);
  counts = signal<Record<string, number>>({});
  dataSource = new MatTableDataSource<Tournament>([]);
  displayedColumns = ['color', 'name', 'date', 'nb_matches', 'actions'];

  private tournamentService = inject(TournamentService);
  private router = inject(Router);
  @ViewChild(MatSort) sort!: MatSort;


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
        this.dataSource.data = data;
        data.forEach(t => this.loadGamesCount(t));
      },
      error: (e) => {
        console.error('Erreur lors du chargement des tournois', e);
      },
    });
  }

  ngAfterViewInit(): void {
    this.sort.active = 'date';
    this.sort.direction = 'desc';
    this.dataSource.sort = this.sort;
    this.sort.sortChange.emit({active: this.sort.active, direction: this.sort.direction});
    this.dataSource.sortingDataAccessor = (item, property) => {
      switch (property) {
        case 'nb_matches':
          return this.counts()[item.pk] ?? 0;
        case 'date':
          return item.date ? new Date(item.date).getTime() : 0;
        case 'name':
          return item.name?.toLowerCase() ?? '';
        case 'color':
          return item.color?.toLowerCase() ?? '';
        default:
          return (item as unknown as Record<string, string | number>)[property] ?? '';
      }
    };
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
  goToVideoEditing(tournament: Tournament): void {
    if (!tournament?._links?.self) return;
    this.router.navigate(['/tournament/video-editing'], {
      queryParams: {url: tournament._links.self.href},
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
    this.tournamentService.video_metadatas(tournament).subscribe({
      next: (games) => {
        const len = Array.isArray(games) ? games.length : 0;
        const next = {...this.counts()};
        next[tournament.pk] = len;
        this.counts.set(next);
        this.dataSource.data = [...this.dataSource.data];
      },
      error: (e) => {
        console.error(`Erreur lors du chargement des jeux pour tournament ${tournament.pk}`, e);
      }
    });
  }
}
