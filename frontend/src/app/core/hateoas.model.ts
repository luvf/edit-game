/**
 * Union of supported HTTP methods used when invoking HATEOAS link actions.
 */
export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';


/**
 * Describes a HAL/HATEOAS link object.
 *
 * See the HAL specification for details on standard fields.
 */
export interface Link {
  /** Absolute or relative URL of the target resource. */
  href: string;

  /** Indicates if the link is a URI template. */
  templated?: boolean;

  /** Media type of the target resource. */
  type?: string;

  /** URL pointing to deprecation information for this link relation. */
  deprecation?: string;

  /** Secondary identifier for the link, often used to disambiguate. */
  name?: string;

  /** URL identifying the profile (metadata) of the target resource. */
  profile?: string;

  /** Human-readable title for the link. */
  title?: string;

  /** Language of the target resource. */
  hreflang?: string;

  /** Add additional fields if your API exposes more link metadata. */
}


/**
 * Dictionary of HATEOAS links, keyed by relation name (rel).
 */
export type LinksMap = Record<string, Link | undefined>;


/**
 * Generic HATEOAS resource shape.
 *
 * @typeParam TLinks - The shape of the `_links` object. Defaults to a generic {@link LinksMap}.
 */
export interface HateoasResource<TLinks extends LinksMap = LinksMap> {
  _links?: TLinks;
}

