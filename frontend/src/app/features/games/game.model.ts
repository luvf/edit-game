import {HateoasResource, Link, LinksMap} from '../../core/hateoas.model';

/**
 * Link relations available on a Game resource.
 *
 * Includes the standard `self` relation. Extend this interface if your backend
 * exposes more relations (e.g., `cuts`, `render`, etc.).
 */
export interface GameLinks extends LinksMap {
  self?: Link;
  tournament?: Link;
  cuts?: Link;
}

/**
 * Domain model representing a game entity.
 *
 * Extends the generic {@link HateoasResource} to carry HATEOAS links.
 */

export interface Game extends HateoasResource<GameLinks> {
  pk: number;
  name: string;
  source_name: string;
  rendered: string;          // "" si non rendu
  json_file: string;         // URL absolue vers le JSON
  source_proxy: string | null;
}
