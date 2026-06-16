import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Game, Tournament, VideoMetadata } from '../models/models';
import { Observable } from 'rxjs';
import { HateoasService, PaginatedResult } from '../hateoas.service';

/**
 * Service providing HATEOAS-powered operations for Tournament resources.
 *
 * Features:
 * - Configures the collection endpoint for listing/creating tournaments.
 * - Exposes helpers to follow relations (`games`, `videos`) and invoke actions (`sync_videos`, `youtube_update`).
 */
@Injectable({ providedIn: 'root' })
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

    /*this.resources = [
      {type: InstanceType<OtherModel[]>, key: "games"},
      {type: InstanceType<VideoMetadata[]>, key: "video_metadatas"},
    ]*/
  }

  games(resource: Tournament, reload: boolean = false): Observable<Game[]> {
    const link = resource._links?.games;
    if (link && 'href' in link) {
      const url = this.withQuery(link.href, {
        no_embed: '1',
        fields: 'pk,name,files,source_proxy',
      });
      return this.http.get<Game[]>(url);
    }
    return this.follow_resource<Game[]>(resource, 'games', reload);
  }

  video_metadatas(
    resource: Tournament,
    reload: boolean = false,
  ): Observable<VideoMetadata[]> {
    const link = resource._links?.video_metadatas;
    if (link && 'href' in link) {
      const url = this.withQuery(link.href, {
        no_embed: '1',
        fields: 'pk,name,description',
      });
      return this.http.get<VideoMetadata[]>(url);
    }
    return this.follow_resource<VideoMetadata[]>(
      resource,
      'video_metadatas',
      reload,
    );
  }

  rendered(resource: Tournament, reload: boolean = false) {
    return this.follow_resource<string[]>(resource, 'rendered', reload);
  }

  source_files(resource: Tournament, reload: boolean = false) {
    return this.follow_resource<string[]>(resource, 'source_files', reload);
  }

  sourceFileUrl(resource: Tournament, filename: string): string {
    const selfHref = resource._links?.self?.href;
    if (!selfHref) {
      throw new Error("Lien 'self' introuvable pour ce tournoi.");
    }
    const base = selfHref.endsWith('/') ? selfHref : `${selfHref}/`;
    return `${base}source-file/?filename=${encodeURIComponent(filename)}`;
  }

  generate_games(resource: Tournament, body: unknown = {}) {
    return this.invoke_resource(resource, 'generate_games', body);
  }

  create_game(resource: Tournament, body: unknown = {}) {
    return this.invoke_resource(resource, 'create_game', body);
  }

  syncVideos(resource: Tournament, body: unknown = {}) {
    return this.invoke_resource(resource, 'sync_videos', body);
  }

  youtubeUpdate(resource: Tournament, body: unknown = {}) {
    return this.invoke_resource(resource, 'youtube_update', body);
  }

  archive(resource: Tournament, body: unknown = {}) {
    return this.invoke_resource(resource, 'archive', body);
  }

  listPage(
    pageIndex: number,
    pageSize: number,
  ): Observable<PaginatedResult<Tournament>> {
    const page = pageIndex + 1;
    const fields = encodeURIComponent('pk,name,date,color,is_archived');
    const url = `${this.baseUrl}?page=${page}&page_size=${pageSize}&no_embed=1&fields=${fields}`;
    return super.listPaginated(url);
  }

  private withQuery(url: string, params: Record<string, string>): string {
    const query = new URLSearchParams(params).toString();
    if (!query) {
      return url;
    }
    return `${url}${url.includes('?') ? '&' : '?'}${query}`;
  }
}
