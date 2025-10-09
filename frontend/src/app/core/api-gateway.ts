import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {ApiDirectoryService} from './api-directory';
import {
  CutsService,
  GamesService,
  TeamLogoService,
  TeamService,
  TmpImageService,
  YTVideoService
} from './services/misc-hateoas-models.service';
import {VideoMetadataService} from './services/video-metadata.service';
import {HateoasService} from './hateoas.service';
import {TournamentService} from './services/tournament.service';


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
    return this.createService(TeamLogoService, 'team_logos');
  }

  videoMetadatas(): VideoMetadataService {
    this.ensureReady();
    return this.createService(VideoMetadataService, 'video_metadatas');
  }

  tmpImages(): TmpImageService {
    this.ensureReady();
    return this.createService(TmpImageService, 'tmp_images');
  }

  ytVideos(): YTVideoService {
    this.ensureReady();
    return this.createService(YTVideoService, 'yt_videos');
  }

  tournaments(): TournamentService {
    this.ensureReady();
    return this.createService(TournamentService, 'tournaments');
  }

  games(): GamesService {
    this.ensureReady();
    return this.createService(GamesService, 'games');
  }

  teams(): TeamService {
    this.ensureReady();
    return this.createService(TeamService, 'teams');
  }

  cuts(): CutsService {
    this.ensureReady();
    return this.createService(CutsService, 'cuts');
  }

  private createService<T extends HateoasService<any>>(serviceType: new (http: HttpClient) => T, urlKey: string): T {
    const service = new serviceType(this.http);
    service.setCollectionUrl(this.directory.url(urlKey));
    return service
  }


  private ensureReady() {
    if (!this.directory.ready()) {
      throw new Error('ApiDirectoryService non initialisé. Appelez ApiGatewayService.init(<API_ROOT_URL>).');
    }
  }
}
