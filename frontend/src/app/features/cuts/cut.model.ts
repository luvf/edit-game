import {HateoasResource, Link, LinksMap} from '../../core/hateoas.model';


/**
 * Link relations available on a Cut resource.
 *
 * Includes the standard `self` relation and a domain-specific `game` relation.
 */
export interface CutLinks extends LinksMap {
  self?: Link;
  game?: Link;
}


/**
 * Discriminator for the cut type.
 *
 * Common values:
 * - 'MAN' for manual cuts
 * - 'AUTO' for automatic cuts
 *
 * Custom or backend-provided values are allowed as strings.
 */
export type TypeCut = 'MAN' | 'AUTO' | string;


/**
 * Domain model representing a video/game cut.
 *
 * Extends the generic {@link HateoasResource} to carry HATEOAS links.
 */
export interface Cut extends HateoasResource<CutLinks> {
  pk: number;
  name: string;
  type_cut: TypeCut;
  json_file: string; // URL absolue vers le fichier JSON
  slug: string;
}
