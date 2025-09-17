import {HateoasResource, Link, LinksMap} from '../../core/hateoas.model';


/**
 * Link relations available on a Tournament resource.
 *
 * Extend this interface if your backend exposes more relations.
 */
export interface TournamentLinks extends LinksMap {
  self?: Link;
  games?: Link;
  sync_videos?: Link;
  youtube_update?: Link;
  videos?: Link;
  // ajoutez d’autres rel si votre API en propose
}

/**
 * Domain model representing a tournament.
 *
 * Extends the generic {@link HateoasResource} to carry HATEOAS links.
 */
export interface Tournament extends HateoasResource<TournamentLinks> {
  pk: number;
  name: string;
  date: string;
  place: string;

  /** url of jtr page for this tournament. */
  JTR: string;
  /** url of tugeny page for this tournament. */
  tugeny_link: string;
  color: string;
  slug: string;
}
