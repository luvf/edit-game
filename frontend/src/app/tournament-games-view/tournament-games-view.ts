// TypeScript
import {Component, inject, OnInit, signal} from '@angular/core';
import {ActivatedRoute, Router} from '@angular/router';
import {catchError, of} from 'rxjs';
import {TournamentService} from '../features/tournaments/tournament';
import {VideoMetadataService} from '../features/video-metadatas/video-metadata';
import {Tournament} from '../features/tournaments/tournament.model';
import {VideoMetadata} from '../features/video-metadatas/video-metadata.model';
import {TeamLogo} from '../features/team-logos/team-logo.model';
import {TmpImageService} from '../features/tmp-images/tmp-image';
import {TmpImage} from '../features/tmp-images/tmp-image.model';
import {MatTableModule} from '@angular/material/table';
import {YtVideo} from '../features/videos/yt-video.model';


/**
 * Lists games (VideoMetadata) for a given Tournament and displays related info.
 *
 * Responsibilities:
 * - Read the tournament self URL from query params and load the tournament.
 * - Fetch related videos and resolve team names, status, and miniature images.
 * - Navigate to the single-game editor view on selection.
 */
@Component({
  styleUrl: './tournament-games-view.css',
  selector: 'app-tournament-games-view',
  imports: [MatTableModule],
  templateUrl: './tournament-games-view.html',
})
export class TournamentGamesViewComponent implements OnInit {
  videos = signal<VideoMetadata[]>([]);
  team1_names = signal<Record<string, string>>({});
  team2_names = signal<Record<string, string>>({});
  video_status = signal<Record<string, string>>({});
  miniature_names = signal<Record<string, string>>({});
  tournament = signal<Tournament | null>(null);
  displayedColumns = ['miniature', 'name', 'teams', 'status', 'description'];
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private tournamentService = inject(TournamentService);
  private videoMetadataService = inject(VideoMetadataService);
  private tmpImageService = inject(TmpImageService);

  /**
   * Initializes by reading the tournament URL and loading its videos.
   * Includes basic error handling for both tournament and videos fetch.
   */
  ngOnInit(): void {
    const tournament_url = this.route.snapshot.queryParamMap.get('url');
    if (!tournament_url) return;

    // Load the tournament, then its videos (with error handling)
    this.tournamentService.get(tournament_url).pipe(
      catchError(err => {
        console.error('Erreur lors de la récupération du tournoi', err);
        return of(null);
      })
    ).subscribe((current_tournament: Tournament | null) => {
      if (!current_tournament) return;
      this.tournament.set(current_tournament);

      // videos() uses follow() and returns Observable<VideoMetadata[]>
      this.tournamentService.videos(current_tournament).pipe(
        catchError(err => {
          console.error('Erreur lors du chargement des vidéos', err);
          return of([] as VideoMetadata[]);
        })
      ).subscribe((videos: VideoMetadata[]) => {
        this.videos.set(videos);
        // Load team names and status for each video, and the miniature
        videos.forEach(v => this.loadVideoStatus(v));
        videos.forEach(v => this.loadTeamsNames(v));
        videos.forEach(v => {
          this.loadMiniature(v)
        })
      });
    });
  }

  /**
   * Opens the single game view for the selected video metadata.
   *
   * @param game - Video metadata entry to open.
   */
  openGame(game: VideoMetadata): void {
    if (!game?._links?.self?.href) return;
    console.log('openGame');
    this.router.navigate(['/game'], {
      queryParams: {
        url: game._links.self.href,
      }
    });
  }

  /**
   * Loads the miniature image URL using the TmpImage service and updates the cache.
   *
   * @param videoMetadata - The video metadata whose miniature to resolve.
   */
  loadMiniature(videoMetadata: VideoMetadata): void {
    if (!videoMetadata?._links?.miniature_image?.href) return;
    this.tmpImageService.get(videoMetadata._links?.miniature_image?.href).subscribe({
      next: (tmpImage: TmpImage | null) => {
        if (!tmpImage) return;
        const next1 = {...this.miniature_names()};
        next1[videoMetadata.pk] = tmpImage.image;
        this.miniature_names.set(next1)
      },
    });
  }

  /**
   * Loads the YouTube publishing status for a given video and stores a label per pk.
   *
   * @param video - The video metadata entry.
   */
  private loadVideoStatus(video: VideoMetadata): void {
    this.videoMetadataService.linked_yt_videos(video).pipe(
      catchError(err => {
        console.error(`Erreur linked_yt_videos pour video ${video.pk}`, err);
        return of(null as any);
      })
    ).subscribe((
        yt_videos: YtVideo[]) => {
        for (let yt_vid of yt_videos) {
          const next1 = {...this.video_status()};
          next1[video.pk] = this.getYTVideoStatus(yt_vid);
          this.video_status.set(next1);
        }
      }
    )
  }

  /**
   * Computes a short status label from a YtVideo object.
   *
   * @param yt_video - The YouTube video entry.
   * @returns Status label string.
   */
  private getYTVideoStatus(yt_video: YtVideo): string {
    const date = Date.parse(yt_video.publication_date)

    if (yt_video.privacy_status == "public") {
      return "public"
    } else if (yt_video.privacy_status == "unlisted") {
      return "unlistede"
    } else if (yt_video.privacy_status == "private" && date >= Date.now()) {
      return "publiec"
    } else {
      return "schedulede"
    }

  }

  /**
   * Resolves and stores Team 1 and Team 2 names for a given video.
   *
   * @param video - The video metadata entry.
   */
  private loadTeamsNames(video: VideoMetadata): void {
    this.videoMetadataService.team1(video).pipe(
      catchError(err => {
        console.error(`Erreur team1 pour video ${video.pk}`, err);
        return of(null as any);
      })
    ).subscribe((team1: TeamLogo | null) => {
      if (team1) {
        const next1 = {...this.team1_names()};
        next1[video.pk] = team1.name;
        this.team1_names.set(next1);
      }
    });

    this.videoMetadataService.team2(video).pipe(
      catchError(err => {
        console.error(`Erreur team2 pour video ${video.pk}`, err);
        return of(null as any);
      })
    ).subscribe((team2: TeamLogo | null) => {
      if (team2) {
        const next2 = {...this.team2_names()};
        next2[video.pk] = team2.name;
        this.team2_names.set(next2);
      }
    });
  }


}
