import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
// ... existing code ...
import { HateoasService } from '../../core/hateoas.service'; // <-- adapte le chemin si besoin
import { YtVideo } from './yt-video.model';

@Injectable({ providedIn: 'root' })
export class YtVideoService extends HateoasService<YtVideo> {
  constructor(http: HttpClient) {
    // Remplacez l’URL ci-dessous par celle de votre collection si différente
    super(http);

    this.setCollectionUrl('/api/yt_videos/');
  }

  // Exemple de helpers si votre API expose des rel supplémentaires:
  // channel(resourceOrUrl: string | YtVideo) {
  //   return this.follow<Channel>(resourceOrUrl, 'channel');
  // }
  // thumbnails(resourceOrUrl: string | YtVideo) {
  //   return this.follow<ThumbnailSet>(resourceOrUrl, 'thumbnails');
  // }
}
