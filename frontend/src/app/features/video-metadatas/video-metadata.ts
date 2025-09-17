// TypeScript
import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {HateoasService} from '../../core/hateoas.service';
import {VideoMetadata} from './video-metadata.model';
import {Tournament} from '../tournaments/tournament.model';
import {TeamLogo} from '../team-logos/team-logo.model';
import {YtVideo} from '../videos/yt-video.model';


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

    this.setCollectionUrl('http://localhost:8000/api/video-metadatas/');
  }


  /**
   * Convenience alias if the API exposes 'videos' as a relation on Tournament.
   *
   * @param resourceOrUrl - Tournament instance or its URL.
   * @returns An observable emitting an array of {@link VideoMetadata}.
   */
  forTournamentVideos(resourceOrUrl: string | Tournament) {
    return this.follow<VideoMetadata[]>(resourceOrUrl as any, 'videos');
  }


  /**
   * Follows the 'team1' relation from a VideoMetadata and returns the associated TeamLogo.
   *
   * @param resourceOrUrl - VideoMetadata instance or its URL.
   * @returns An observable emitting the {@link TeamLogo}.
   */
  team1(resourceOrUrl: string | VideoMetadata) {
    return this.follow<TeamLogo>(resourceOrUrl as any, 'team1');
  }

  /**
   * Follows the 'team2' relation from a VideoMetadata and returns the associated TeamLogo.
   *
   * @param resourceOrUrl - VideoMetadata instance or its URL.
   * @returns An observable emitting the {@link TeamLogo}.
   */
  team2(resourceOrUrl: string | VideoMetadata) {
    return this.follow<TeamLogo>(resourceOrUrl as any, 'team2');
  }

  /**
   * Follows the 'miniature_image' relation and returns the thumbnail URL.
   *
   * @param resourceOrUrl - VideoMetadata instance or its URL.
   * @returns An observable emitting the thumbnail URL as string.
   */
  miniature_image(resourceOrUrl: string | VideoMetadata) {
    return this.follow<string>(resourceOrUrl as any, 'miniature_image');
  }

  /**
   * Follows the 'base_image' relation and returns the base image URL.
   *
   * @param resourceOrUrl - VideoMetadata instance or its URL.
   * @returns An observable emitting the base image URL as string.
   */
  base_image(resourceOrUrl: string | VideoMetadata) {
    return this.follow<string>(resourceOrUrl as any, 'base_image');
  }

  /**
   * Invokes the 'generate_miniature' action to produce a thumbnail with given parameters.
   *
   * @param resourceOrUrl - VideoMetadata instance or its URL.
   * @param payload - Generation parameters:
   *   - xoffset: Horizontal offset (0..1).
   *   - yoffset: Vertical offset (0..1).
   *   - zoom: Zoom factor (>= 1).
   *   - time_code: Optional timecode (seconds or normalized, depending on backend).
   * @returns An observable emitting the backend response (e.g., updated links/URLs).
   */
  generate_miniature(
    resourceOrUrl: string | VideoMetadata,
    payload: { xoffset: number; yoffset: number; zoom: number; time_code?: number }
  ) {
    return this.invoke<any>(resourceOrUrl, 'generate_miniature', payload);
  }

  /**
   * Invokes the 'upload_description' action to push the current description to the platform.
   *
   * Note: method name contains a typo for backward compatibility.
   *
   * @param resourceOrUrl - VideoMetadata instance or its URL.
   * @returns An observable emitting the backend response.
   */
  upload_descripton(resourceOrUrl: string | VideoMetadata) {
    return this.invoke<any>(resourceOrUrl, 'upload_description', {}, "PATCH");
  }

  /**
   * Invokes the 'upload_miniature' action to push the current thumbnail to the platform.
   *
   * @param resourceOrUrl - VideoMetadata instance or its URL.
   * @returns An observable emitting the backend response.
   */
  upload_miniature(resourceOrUrl: string | VideoMetadata) {
    return this.invoke<any>(resourceOrUrl, 'upload_miniature', {}, "PATCH");
  }

  /**
   * Invokes the 'reset_title_description' action to reset title and description.
   *
   * Note: method name contains a typo for backward compatibility.
   *
   * @param resourceOrUrl - VideoMetadata instance or its URL.
   * @returns An observable emitting the backend response.
   */
  reset_title_descriptiont(resourceOrUrl: string | VideoMetadata) {
    return this.invoke<any>(resourceOrUrl, 'reset_title_description', {}, "PATCH");
  }

  /**
   * Follows the 'linked_yt_videos' relation to fetch associated YouTube videos.
   *
   * @param resourceOrUrl - VideoMetadata instance or its URL.
   * @returns An observable emitting an array of {@link YtVideo}.
   */
  linked_yt_videos(resourceOrUrl: string | VideoMetadata) {
    return this.follow<YtVideo[]>(resourceOrUrl, 'linked_yt_videos');
  }

}
