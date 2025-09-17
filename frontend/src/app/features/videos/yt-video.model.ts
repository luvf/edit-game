import {HateoasResource} from '../../core/hateoas.model'; // adapte le chemin si nécessaire


/**
 * Link relations available on a YtVideo resource.
 *
 * Extend this interface if your backend exposes additional relations
 * (e.g., `self`, `video_metadata`, `thumbnail`, etc.).
 */
export interface YtVideoLinks {
  self?: { href: string };

  // autres relations éventuelles
  [rel: string]: { href: string } | undefined;
}

/**
 * Privacy status of a YouTube video.
 *
 * Known values:
 * - 'public', 'unlisted', 'private'
 *
 * Extra/custom values from the backend are allowed as strings.
 */
export type PrivacyStatus = 'public' | 'unlisted' | 'private' | string;


/**
 * Domain model representing a YouTube video entry.
 *
 * Extends the generic {@link HateoasResource} to carry HATEOAS links.
 */
export interface YtVideo extends HateoasResource<YtVideoLinks> {
  pk: number;

  title: string;
  video_id: string;
  publication_date: string;      // ISO, ex: "2024-01-03T21:30:10Z"
  privacy_status: PrivacyStatus;
}
