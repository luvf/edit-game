import {HateoasResource, Link, LinksMap} from '../../core/hateoas.model';


/**
 * Link relations available on a TeamLogo resource.
 *
 * Extend this interface if your backend exposes additional relations
 * (e.g., `teams`, `self`, domain-specific rels).
 */
export interface TeamLogoLinks extends LinksMap {
  self?: Link;
  teams?: Link;
}


/**
 * Domain model representing a team logo.
 *
 * Extends the generic {@link HateoasResource} to carry HATEOAS links.
 */
export interface TeamLogo extends HateoasResource<TeamLogoLinks> {
  pk: number;
  name: string;
  short_name: string;
  image: string; // URL absolue vers le logo
}
