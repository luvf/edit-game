import {HateoasResource, Link} from '../../core/hateoas.model';


/**
 * Link relations available on a VideoMetadata resource.
 *
 * Extend this interface if your backend exposes additional relations.
 */
export interface VideoMetadataLinks {
  self?: Link;
  tournament?: Link;
  miniature_image?: Link;
  base_image?: Link;
  team1?: Link;
  team2?: Link;
  reset_url?: Link;
  upload_description?: Link;
  upload_miniature?: Link;
  find_ytvid?: Link;
  generate_miniature?: Link;
  linked_yt_videos?: Link;
  reset_title_description?: Link;

  // Permet de conserver la compatibilité avec des rel non prévus
  [rel: string]: Link | undefined;
}

/**
 * Domain model describing video publication and rendering metadata.
 *
 * Extends the generic {@link HateoasResource} to carry HATEOAS links.
 */
export interface VideoMetadata extends HateoasResource<VideoMetadataLinks> {
  pk: number;
  name: string;
  tc: number; // timecode / offset en secondes
  video_name: string;
  description: string;
  publication_date: string; // ISO 8601
}
