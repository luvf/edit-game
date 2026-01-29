import {HttpClient} from '@angular/common/http';
import {Team, TmpImage, VideoMetadata, Yt_Video} from '../models/models';
import {HateoasService} from '../hateoas.service';
import {Injectable} from '@angular/core';
import {Observable} from 'rxjs';


/**
 * Service providing HATEOAS-powered operations for VideoMetadata resources.
 *
 * Features:
 * - Configures the collection endpoint for listing/creating video metadata.
 * - Exposes helpers to follow domain-specific relations (teams, images, linked videos).
 * - Exposes actions to generate/upload/reset metadata-related assets.
 */
@Injectable({providedIn: 'root'})
export class VideoMetadataService extends HateoasService<VideoMetadata> {
  /**
   * Creates the service and sets the default collection URL for video metadata.
   *
   * Replace the URL as needed to match your backend configuration.
   *
   * @param http - Angular HttpClient instance injected by DI.
   */
  constructor(http: HttpClient) {
    super(http);
    this.setCollectionUrl("http://localhost:8000/api/video_metadatas/");

  }

  team1(resource: VideoMetadata, reload: boolean = false): Observable<Team> {
    return this.follow_resource<Team>(resource, 'team1', reload);
  }

  team2(resource: VideoMetadata, reload: boolean = false): Observable<Team> {
    return this.follow_resource<Team>(resource, 'team2', reload);
  }

  miniature_image(resource: VideoMetadata, reload: boolean = false) {
    return this.follow_resource<TmpImage>(resource, 'miniature_image', reload);
  }


  base_image(resource: VideoMetadata, reload: boolean = false) {
    return this.follow_resource<TmpImage>(resource, 'base_image', reload);
  }


  linked_yt_videos(resource: VideoMetadata, reload: boolean = false) {
    return this.follow_resource<Yt_Video[]>(resource, 'linked_yt_videos', reload);
  }

  /**
   * Invokes the 'generate_miniature' action to produce a thumbnail with given parameters.
   *
   * @param resource - VideoMetadata instance .
   * @param payload - Generation parameters:
   *   - xoffset: Horizontal offset (0..1).
   *   - yoffset: Vertical offset (0..1).
   *   - zoom: Zoom factor (>= 1).
   *   - time_code: Optional timecode (seconds or normalized, depending on backend).
   * @returns An observable emitting the backend response (e.g., updated links/URLs).
   */
  generate_miniature(
    resource: VideoMetadata,
    payload: Partial<VideoMetadata>
  ) {
    return this.invoke_resource<any>(resource, 'generate_miniature', payload);
  }

  /**
   * Invokes the 'upload_description' action to push the current description to the platform.
   *
   * Note: method name contains a typo for backward compatibility.
   *
   * @param resource - VideoMetadata instance or its URL.
   * @returns An observable emitting the backend response.
   */
  upload_description(resource: VideoMetadata) {
    return this.invoke_resource<any>(resource, 'upload_description', {}, "PATCH");
  }

  /**
   * Invokes the 'upload_miniature' action to push the current thumbnail to the platform.
   *
   * @param resource - VideoMetadata instance or its URL.
   * @returns An observable emitting the backend response.
   */
  upload_miniature(resource: VideoMetadata) {
    return this.invoke_resource<any>(resource, 'upload_miniature', {}, "PATCH");
  }

  /**
   * Invokes the 'reset_title_description' action to reset title and description.
   *
   * Note: method name contains a typo for backward compatibility.
   *
   * @param resource - VideoMetadata instance or its URL.
   * @returns An observable emitting the backend response.
   */
  reset_title_description(resource: VideoMetadata) {
    return this.invoke_resource<any>(resource, 'reset_title_description', {}, "PATCH");
  }

}
