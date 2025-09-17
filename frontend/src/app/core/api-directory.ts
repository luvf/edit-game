import {Injectable, signal} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {tap} from 'rxjs/operators';
import {Observable} from 'rxjs';

export interface ApiRoot {
  team_logos: string;
  video_metadatas: string;
  tmp_images: string;
  yt_videos: string;
  tournaments: string;
  games: string;
  teams: string;
  cuts: string;

  [k: string]: string;
}

@Injectable({providedIn: 'root'})
export class ApiDirectoryService {
  private readonly endpoints = new Map<string, string>();
  private readonly _ready = signal(false);
  readonly ready = this._ready.asReadonly();

  constructor(private readonly http: HttpClient) {
  }

  private _rootUrl = '';

  get rootUrl(): string {
    return this._rootUrl;
  }

  /*
  * loads the root url.
  * returns an observable that completes when the root url is loaded.
  * @param rootUrl the root url of the api
  * */
  load(rootUrl: string): Observable<ApiRoot> {
    this._rootUrl = rootUrl;
    return this.http.get<ApiRoot>(rootUrl).pipe(
      tap((root) => {
        this.endpoints.clear();
        Object.entries(root).forEach(([k, v]) => this.endpoints.set(k, v));
        this._ready.set(true);
      })
    );
  }

  url(key: keyof ApiRoot | string): string {
    const value = this.endpoints.get(String(key));
    if (!value) {
      throw new Error(`Endpoint introuvable pour la clé "${String(key)}". Avez-vous appelé load(rootUrl) ?`);
    }
    return value;
  }

  has(key: keyof ApiRoot | string): boolean {
    return this.endpoints.has(String(key));
  }
}
