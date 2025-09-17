import {HateoasResource, Link, LinksMap} from '../../core/hateoas.model';


/**
 * Link relations available on a Team resource.
 *
 * Extend this interface if your backend exposes additional relations
 * (e.g., `players`, `logo`, `tournaments`, etc.).
 */
export interface TeamLinks extends LinksMap {
  self?: Link;
  logo?: Link;
}

/**
 * Domain model representing a team entity.
 *
 * Extends the generic {@link HateoasResource} to carry HATEOAS links.
 */
export interface Team extends HateoasResource<TeamLinks> {
  pk: number;
  name: string;
  slug: string;
}
