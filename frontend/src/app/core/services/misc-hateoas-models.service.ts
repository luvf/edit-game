import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {Cut, Game, RenderQueueItem, Team, TmpImage, Yt_Video} from '../models/models';
import {HateoasService} from '../hateoas.service';
import {Observable} from 'rxjs';

/**
/**
 * Service providing HATEOAS-powered operations for Team resources.
 *
 * Features:
 * - Configures the collection endpoint for listing/creating teams.
 * - Inherits generic helpers to follow relations and invoke link-based actions.
 */
@Injectable({providedIn: 'root'})
export class TeamService extends HateoasService<Team> {
  /**
   * Creates the service and sets the default collection URL for teams.
   *
   * Replace the URL as needed to match your backend configuration.
   *
   * @param http - Angular HttpClient instance injected by DI.
   * @param url - Optional URL override for the collection endpoint.
   */
  constructor(http: HttpClient) {
    super(http);
    this.setCollectionUrl('http://localhost:8000/api/teams/')

  }
}

@Injectable({providedIn: 'root'})
export class YTVideoService extends HateoasService<Yt_Video> {
  constructor(http: HttpClient) {
    super(http);
    this.setCollectionUrl('http://localhost:8000/api/yt_videos/')
  }
}


@Injectable({providedIn: 'root'})
export class TmpImageService extends HateoasService<TmpImage> {
  constructor(http: HttpClient) {
    super(http);
    this.setCollectionUrl('http://localhost:8000/api/tmp_images/')
  }
}


@Injectable({providedIn: 'root'})
export class CutsService extends HateoasService<Cut> {
  constructor(http: HttpClient) {
    super(http)
    this.setCollectionUrl('http://localhost:8000/api/cuts/')

  }

  cut_types(): Observable<Array<{code: string; label: string}>> {
    return this.http.get<Array<{code: string; label: string}>>(`${this.baseUrl}cut-types/`);
  }

  render_cut(resource: Cut, body: unknown = {}):Observable<RenderQueueItem> {
    return this.invoke_resource<RenderQueueItem>(resource, 'render', body);
  }
}



@Injectable({providedIn: 'root'})
export class GamesService extends HateoasService<Game> {
  constructor(http: HttpClient) {
    super(http);
    this.setCollectionUrl('http://localhost:8000/api/games/')
  }

  team1(resource: Game, reload: boolean = false): Observable<Team> {
    return this.follow_resource<Team>(resource, 'team1', reload);
  }


  team2(resource: Game, reload: boolean = false): Observable<Team> {
    return this.follow_resource<Team>(resource, 'team2', reload);
  }

  generateProxy(resource: Game, body: unknown = {}) {
    return this.invoke_resource<Game>(resource, 'generate_proxy', body);
  }

  cuts(resource: Game, reload: boolean = false):Observable<Cut[]>{
    return this.follow_resource<Cut[]>(resource, 'cuts', reload);
  }

  create_cut(resource: Game, body: unknown = {}):Observable<Cut> {
    return this.invoke_resource<Cut>(resource, 'create_cut', body);
  }


}

@Injectable({providedIn: 'root'})
export class RenderQueueService extends HateoasService<RenderQueueItem> {
  constructor(http: HttpClient) {
    super(http);
    this.setCollectionUrl('http://localhost:8000/api/render-queue/')
  }


  run(item: RenderQueueItem):Observable<RenderQueueItem>{
    return this.invoke_resource<RenderQueueItem>(item, 'run');
  }

  reset(item: RenderQueueItem):Observable<RenderQueueItem> {
    return this.invoke_resource<RenderQueueItem>(item, 'reset');
  }
}
