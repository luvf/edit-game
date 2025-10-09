// TypeScript
import {Component, inject, OnInit, signal} from '@angular/core';
import {ActivatedRoute, Router} from '@angular/router';
import {of} from 'rxjs';

import {MatTableModule} from '@angular/material/table';
import {TeamLogo, TmpImage, Tournament, VideoMetadata, Yt_Video} from '../core/models/models';
import {VideoMetadataService} from '../core/services/video-metadata.service';
import {TeamLogoService, TmpImageService} from '../core/services/misc-hateoas-models.service';
import {TournamentService} from '../core/services/tournament.service';

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
  private teamLogoService = inject(TeamLogoService);
  private tmpImageService = inject(TmpImageService);

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
          this.tournament_loaded(current_tournament);
        },
        error: (e) => {
          console.error('Erreur lors de la récupération du tournoi', e);
          return of(null);
        },
      }
    );
    // videos() uses follow() and returns Observable<VideoMetadata[]>

  }

  /**
   * Opens the single game view for the selected video metadata.
   *
   * @param game - Video metadata entry to open.
   */
  openGame(game: VideoMetadata): void {
    if (!game?._links?.self.href) return;
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
    this.videoMetadataService.miniature_image(videoMetadata).subscribe({
      next: (tmpImage: TmpImage | null) => {
        if (!tmpImage) return;
        const next1 = {...this.miniature_names()};
        next1[videoMetadata.pk] = tmpImage.image;
        this.miniature_names.set(next1)
      },
    });
  }

  private tournament_loaded(tournament: Tournament): void {
    this.tournamentService.video_metadatas(tournament, true).subscribe({
      next: (videos: VideoMetadata[]) => {
        this.videos.set(videos);
        // Load team names and status for each video, and the miniature
        videos.forEach(v => this.loadVideoStatus(v));
        videos.forEach(v => this.loadTeamsNames(v));
        videos.forEach(v => this.loadMiniature(v));
      },

      error: (e) => {
        console.error('Erreur lors du chargement des vidéos', e);
        return of([] as VideoMetadata[]);
      },
    })
  }

  /**
   * Loads the YouTube publishing status for a given video and stores a label per pk.
   *
   * @param video - The video metadata entry.
   */
  private loadVideoStatus(video: VideoMetadata): void {
    this.videoMetadataService.linked_yt_videos(video).subscribe({
        next: (yt_videos: Yt_Video[]) => {
          for (let yt_vid of yt_videos) {
            const next1 = {...this.video_status()};
            next1[video.pk] = this.getYTVideoStatus(yt_vid);
            this.video_status.set(next1);
          }
        },
        error: (e) => {
          console.error(`Erreur linked_yt_videos pour video ${video.pk}`, e);
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
  private getYTVideoStatus(yt_video: Yt_Video): string {
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
    this.videoMetadataService.team1(video).subscribe({
      next: (team1: TeamLogo | null) => {
        if (team1) {
          const next1 = {...this.team1_names()};
          next1[video.pk] = team1.name;
          this.team1_names.set(next1);
        }
      }, error: (e) => {
        console.error(`Erreur team1 pour video ${video.pk}`, e);
      }
    });
    this.videoMetadataService.team2(video).subscribe({
      next: (team2: TeamLogo | null) => {
        if (team2) {
          const next2 = {...this.team2_names()};
          next2[video.pk] = team2.name;
          this.team2_names.set(next2);
        }
      },
      error: (e) => {
        console.error(`Erreur team2 pour video ${video.pk}`, e);
      }
    });
  }


}
