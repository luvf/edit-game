// TypeScript
import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {HateoasService} from '../../core/hateoas.service'; // <-- adapte le chemin si nécessaire
import {Tournament} from './tournament.model';
import {Game} from '../games/game.model';
import {VideoMetadata} from '../video-metadatas/video-metadata.model';

/**
 * Service providing HATEOAS-powered operations for Tournament resources.
 *
 * Features:
 * - Configures the collection endpoint for listing/creating tournaments.
 * - Exposes helpers to follow relations (`games`, `videos`) and invoke actions (`sync_videos`, `youtube_update`).
 */
@Injectable({providedIn: 'root'})
export class TournamentService extends HateoasService<Tournament> {
  /**
   * Creates the service and sets the default collection URL for tournaments.
   *
   * Replace the URL as needed to match your backend configuration.
   *
   * @param http - Angular HttpClient instance injected by DI.
   */
  constructor(http: HttpClient) {
    super(http);
    this.setCollectionUrl('http://localhost:8000/api/tournaments/');
  }


  /**
   * Follows the 'games' relation to fetch games associated with a tournament.
   *
   * @param resourceOrUrl - A Tournament resource instance or its URL.
   * @returns An observable emitting the list of {@link Game}.
   */
  games(resourceOrUrl: string | Tournament) {
    return this.follow<Game[]>(resourceOrUrl, 'games');
  }

  /**
   * Follows the 'videos' relation to fetch video metadata associated with a tournament.
   *
   * @param resourceOrUrl - A Tournament resource instance or its URL.
   * @returns An observable emitting the list of {@link VideoMetadata}.
   */
  videos(resourceOrUrl: string | Tournament) {
    return this.follow<VideoMetadata[]>(resourceOrUrl, 'videos');
  }

  /**
   * Invokes the 'sync_videos' action to synchronize tournament videos.
   *
   * @param resourceOrUrl - A Tournament resource instance or its URL.
   * @param body - Optional payload to send to the action.
   * @returns An observable emitting the backend response.
   */
  syncVideos(resourceOrUrl: string | Tournament, body: unknown = {}) {
    return this.invoke(resourceOrUrl, 'sync_videos', body);
  }

  /**
   * Invokes the 'youtube_update' action to refresh YouTube-related data.
   *
   * @param resourceOrUrl - A Tournament resource instance or its URL.
   * @param body - Optional payload to send to the action.
   * @returns An observable emitting the backend response.
   */
  youtubeUpdate(resourceOrUrl: string | Tournament, body: unknown = {}) {
    return this.invoke(resourceOrUrl, 'youtube_update', body);
  }
}
