import {HateoasResource, Link, LinksMap} from '../../core/hateoas.model';


/**
 * Link relations available on a TmpImage resource.
 *
 * Extend this interface if your backend exposes additional relations.
 */
export interface TmpImageLinks extends LinksMap {
  self?: Link;
}

/**
 * Domain model representing a temporary image.
 *
 * Extends the generic {@link HateoasResource} to carry HATEOAS links.
 */
export interface TmpImage extends HateoasResource<TmpImageLinks> {
  pk: number;
  name: string;

  /** Absolute URL to the temporary image. */
  image: string; // URL absolue vers l’image temporaire
}
