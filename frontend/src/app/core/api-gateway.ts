import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {ApiDirectoryService} from './api-directory';

import {TeamLogoService} from "../features/team-logos/team-logo";
import {VideoMetadataService} from '../features/video-metadatas/video-metadata';
import {TmpImageService} from '../features/tmp-images/tmp-image';
import {YtVideoService} from '../features/videos/yt-video';
import {TournamentService} from '../features/tournaments/tournament';
import {GameService} from '../features/games/game';
import {TeamService} from '../features/teams/team';
import {CutService} from '../features/cuts/cut';

@Injectable({providedIn: 'root'})
export class ApiGatewayService {
  constructor(
    private readonly http: HttpClient,
    private readonly directory: ApiDirectoryService
  ) {
  }

  // À appeler au démarrage (ou via APP_INITIALIZER)
  init(rootUrl: string) {
    return this.directory.load(rootUrl);
  }

  // Chaque méthode retourne une instance configurée avec l’URL de collection issue de la racine
  teamLogos(): TeamLogoService {
    this.ensureReady();
    const svc = new TeamLogoService(this.http);
    svc.setCollectionUrl(this.directory.url('team_logos'));
    return svc;
  }

  videoMetadatas(): VideoMetadataService {
    this.ensureReady();
    const svc = new VideoMetadataService(this.http);
    svc.setCollectionUrl(this.directory.url('video_metadatas'));
    return svc;
  }

  tmpImages(): TmpImageService {
    this.ensureReady();
    const svc = new TmpImageService(this.http);
    svc.setCollectionUrl(this.directory.url('tmp_images'));
    return svc;
  }

  ytVideos(): YtVideoService {
    this.ensureReady();
    const svc = new YtVideoService(this.http);
    svc.setCollectionUrl(this.directory.url('yt_videos'));
    return svc;
  }

  tournaments(): TournamentService {
    this.ensureReady();
    const svc = new TournamentService(this.http);
    svc.setCollectionUrl(this.directory.url('tournaments'));
    return svc;
  }

  games(): GameService {
    this.ensureReady();
    const svc = new GameService(this.http);
    svc.setCollectionUrl(this.directory.url('games'));
    return svc;
  }

  teams(): TeamService {
    this.ensureReady();
    const svc = new TeamService(this.http);
    svc.setCollectionUrl(this.directory.url('teams'));
    return svc;
  }

  cuts(): CutService {
    this.ensureReady();
    const svc = new CutService(this.http);
    svc.setCollectionUrl(this.directory.url('cuts'));
    return svc;
  }

  private ensureReady() {
    if (!this.directory.ready()) {
      throw new Error('ApiDirectoryService non initialisé. Appelez ApiGatewayService.init(<API_ROOT_URL>).');
    }
  }
}
