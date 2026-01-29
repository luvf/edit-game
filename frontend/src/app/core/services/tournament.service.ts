import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {Game, Tournament, VideoMetadata} from '../models/models';
import {Observable} from 'rxjs';
import {HateoasService} from '../hateoas.service';
import {PaginatedResult} from '../hateoas.service';


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
    this.setCollectionUrl("http://localhost:8000/api/tournaments/");

    /*this.resources = [
      {type: InstanceType<OtherModel[]>, key: "games"},
      {type: InstanceType<VideoMetadata[]>, key: "video_metadatas"},
    ]*/
  }

  games(resource: Tournament, reload: boolean = false): Observable<Game[]> {
    return this.follow_resource<Game[]>(resource, 'games', reload);
  }

  video_metadatas(resource: Tournament, reload: boolean = false) {
    return this.follow_resource<VideoMetadata[]>(resource, 'video_metadatas', reload);
  }

  generate_games(resource: Tournament, body: unknown = {}) {
    return this.invoke_resource(resource, 'generate_games', body);
  }

  syncVideos(resource: Tournament, body: unknown = {}) {
    return this.invoke_resource(resource, 'sync_videos', body);
  }

  youtubeUpdate(resource: Tournament, body: unknown = {}) {
    return this.invoke_resource(resource, 'youtube_update', body);
  }

  listPage(pageIndex: number, pageSize: number): Observable<PaginatedResult<Tournament>> {
    const page = pageIndex + 1;
    const url = `${this.baseUrl}?page=${page}&page_size=${pageSize}`;
    return super.listPaginated(url);
  }
}
