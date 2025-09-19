// TypeScript
import {HttpClient, HttpHeaders} from '@angular/common/http';
import {Injectable} from '@angular/core';
import halfred, {Resource} from 'halfred';
import {from, map, Observable, switchMap} from 'rxjs';
import {HateoasResource, HttpMethod} from './hateoas.model'; // <-- import du type central // <-- import du type central + HttpMethod

// ... existing code ...


/**
 * Represents a resource enriched by halfred parsing.
 * This augments the resource with an optional `_parsed` handle to the underlying halfred `Resource`.
 *
 * @typeParam T - The domain resource type that conforms to {@link HateoasResource}.
 */

type HateoasParsed<T> = T & { _parsed?: Resource };

/**
 * Generic HATEOAS service providing convenience methods to work with HAL/JSON APIs.
 *
 * Features:
 * - Collection fetch with flexible handling of plain arrays or HAL `_embedded` payloads.
 * - Single resource retrieval with parsed links.
 * - Relation following via `_links[rel]` or fallback to `_embedded`.
 * - Action invocation across arbitrary HTTP methods through HttpClient.request.
 *
 * Usage:
 * - Call `setCollectionUrl()` once to set the collection endpoint.
 * - Use `list()` and `get()` for reading resources.
 * - Use `post()`, `update()`, and `delete()` for mutations.
 * - Use `follow()` to traverse relations and `invoke()` to trigger link-based actions.
 *
 * @typeParam T - The domain resource type that conforms to {@link HateoasResource}.
 */
@Injectable({providedIn: 'root'})
export class HateoasService<T extends HateoasResource> {
  /**
   * Base collection URL used by default for list/post calls or as a fallback
   * when an explicit resource self link cannot be resolved.
   */
  protected baseUrl = '';

  constructor(protected http: HttpClient) {
  }

  /**
   * Sets the base collection URL used by `list()` and `post()` by default.
   *
   * @param url - The collection endpoint URL.
   */
  public setCollectionUrl(url: string): void {
    this.baseUrl = url;
  }

  /**
   * Retrieves a list of resources.
   *
   * Behavior:
   * - If the API returns a plain JSON array, items are returned as-is with `_parsed` attached.
   * - If the API returns a HAL document, items are extracted from the first array/object found in `_embedded`.
   * - If no items can be determined, an empty array is returned.
   *
   * @param url - Optional explicit URL. Defaults to the configured collection URL.
   * @returns An observable emitting an array of resources of type `T`.
   */
  list(url: string = this.baseUrl): Observable<T[]> {
    return this.http.get(url).pipe(
      map(body => {
        // 1) Case where api return directly a JSON array.
        if (Array.isArray(body)) {
          return (body as any[]).map((item: any) => {
            (item as HateoasParsed<T>)._parsed = this.parse(item);
            return item as T;
          });
        }

        // 2) Case HAL: we parse with halfred
        const parsed = this.parse(body);
        const original = (parsed as any).original ? parsed.original() : (body as any);

        // 3) extract with _embedded for any key and normalize the array
        let items: any[] = [];
        const embedded = original?._embedded;
        if (embedded && typeof embedded === 'object') {
          const keys = Object.keys(embedded);
          for (const k of keys) {
            const val = embedded[k];
            if (Array.isArray(val)) {
              items = val;
              break;
            } else if (val && typeof val === 'object') {
              items = [val];
              break;
            }
          }
        }

        // 4) Returns empty if no elements, otherwise attactch _parsed and cast
        if (items.length === 0) return [];

        return items.map((item: any) => {
          (item as HateoasParsed<T>)._parsed = this.parse(item);
          return item as T;
        });
      })
    );
  }

  /**
   * Retrieves a single resource by URL or by resource instance (resolving its `self` link).
   *
   * @param urlOrId - A string URL or a resource instance providing `_links.self.href`.
   * @returns An observable emitting the fetched resource of type `T`, with `_parsed` attached.
   */
  get(urlOrId: string | T): Observable<T> {
    const url = this.resolveUrl(urlOrId);
    return this.http.get(url).pipe(
      map(body => {
        const parsed = this.parse(body);
        const resource = parsed.original() as T;
        (resource as HateoasParsed<T>)._parsed = parsed;
        return resource;
      })
    );
  }

  /**
   * Creates a resource via POST to the collection URL (or a custom URL).
   *
   * Server responses:
   * - May return a plain resource or a HAL document. Both are normalized, with `_parsed` attached.
   *
   * @param body - Partial resource payload to submit.
   * @param url - Optional target URL. Defaults to the configured collection URL.
   * @returns An observable emitting the created resource of type `T`.
   */
  post(body: Partial<T>, url: string = this.baseUrl): Observable<T> {
    return this.http.post(url, body).pipe(
      map(resp => {
        // Certains serveurs renvoient directement l'objet, d'autres un HAL complet
        const parsed = this.parse(resp);
        const resource = (parsed as any).original ? (parsed as any).original() as T : (resp as T);
        (resource as HateoasParsed<T>)._parsed = parsed;
        return resource;
      })
    );
  }

  /**
   * Updates a resource via PATCH (default) or PUT using the resource's `self` URL.
   *
   * Notes:
   * - PATCH is recommended by default for partial updates in HATEOAS flows.
   * - The response is normalized to a resource with `_parsed` attached.
   *
   * @param resourceOrUrl - Resource instance or its `self` URL.
   * @param partial - The partial (or full for PUT) resource payload to send.
   * @param method - Update method: 'PATCH' (default) or 'PUT'.
   * @returns An observable emitting the updated resource of type `T`.
   */
  update(resourceOrUrl: string | T, partial: Partial<T>, method: 'PATCH' | 'PUT' = 'PATCH'): Observable<T> {
    const url = this.resolveUrl(resourceOrUrl);
    const req$ = method === 'PUT'
      ? this.http.put(url, partial)
      : this.http.patch(url, partial);

    return req$.pipe(
      map(resp => {
        const parsed = this.parse(resp);
        const resource = (parsed as any).original ? (parsed as any).original() as T : (resp as T);
        (resource as HateoasParsed<T>)._parsed = parsed;
        return resource;
      })
    );
  }

  /**
   * Deletes a resource via its `self` URL.
   *
   * @param resourceOrUrl - Resource instance or its `self` URL.
   * @returns An observable completing when the deletion is done.
   */
  delete(resourceOrUrl: string | T): Observable<void> {
    const url = this.resolveUrl(resourceOrUrl);
    return this.http.delete<void>(url);
  }

  /**
   * Follows a relation (`rel`) starting from a resource or URL.
   *
   * Resolution strategy:
   * - First, fetch and parse the resource, then check `_links[rel].href` and GET it.
   * - If not found in links, try `_embedded[rel]` and return it directly.
   * - Throws if no relation is found.
   *
   * @typeParam R - The expected shape of the related resource/result.
   * @param resourceOrUrl - Resource instance or URL from which the relation is followed.
   * @param rel - The link relation name to follow.
   * @returns An observable emitting the related data of type `R`.
   * @throws Error if the relation cannot be found.
   */
  follow<R = any>(resourceOrUrl: string | T, rel: string): Observable<R> {
    // Si on nous passe un objet déjà parsé avec le lien, court-circuiter
    if (resourceOrUrl && typeof resourceOrUrl === 'object') {
      const maybeLink = (resourceOrUrl as any)?._links?.[rel]?.href as string | undefined;
      if (maybeLink) {
        return this.http.get<R>(maybeLink);
      }
    }

    const url = this.resolveUrl(resourceOrUrl);
    return this.http.get(url).pipe(
      switchMap((body: unknown) => {
        const parsed = this.parse(body);
        const link = parsed.link(rel);
        if (link?.href) {
          return this.http.get<R>(link.href);
        }
        const emb = parsed.allEmbeddedResources();
        if (emb && emb[rel]) {
          return from([emb[rel] as R]);
        }
        throw new Error(`Relation '${rel}' introuvable sur ${url}`);
      })
    );
  }

  /**
   * Invokes a link-based action (e.g., POST/PUT/DELETE/GET) if present in `_links`.
   *
   * Implementation details:
   * - Resolves the resource, finds `_links[rel].href`, and performs an HTTP request with the specified method.
   * - For methods without a body (GET/DELETE), no body is sent; for others, the payload is included with JSON headers.
   * - Uses `HttpClient.request` to support all HTTP verbs while returning `Observable<R>`.
   *
   * @typeParam R - The expected response type.
   * @param resourceOrUrl - Resource instance or URL from which the action is resolved.
   * @param rel - The link relation name representing the action.
   * @param body - Optional request body for methods that support it.
   * @param method - HTTP method to use. Defaults to 'POST'.
   * @returns An observable emitting the action response of type `R`.
   * @throws Error if the link/action cannot be found on the resource.
   */
  invoke<R = any>(
    resourceOrUrl: string | T,
    rel: string,
    body: unknown = {},
    method: HttpMethod = 'POST'
  ): Observable<R> {
    const url = this.resolveUrl(resourceOrUrl);
    return this.http.get(url).pipe(
      switchMap((bodyGet: unknown) => {
        const parsed = this.parse(bodyGet);
        const link = parsed.link(rel);
        if (!link || !link.href) {
          throw new Error(`Action/link '${rel}' introuvable sur ${url}`);
        }

        // fix the body and header depending on the verb.
        const hasBody = !(method === 'GET' || method === 'DELETE');
        const headers = hasBody ? new HttpHeaders({'Content-Type': 'application/json'}) : undefined;

        // Explicit typing to force "observe: 'body'"
        const options: {
          headers?: HttpHeaders;
          body?: unknown;
          observe: 'body';
          responseType: 'json';
        } = {
          headers,
          observe: 'body',
          responseType: 'json'
        };
        if (hasBody) {
          options.body = body;
        }

        // Use HttpClient.request to support all verbs and return Observable<R>
        return this.http.request<R>(method, link.href, options);
      })
    );
  }

  /**
   * Parses an arbitrary JSON payload using halfred to obtain a `Resource` wrapper.
   *
   * @param body - JSON object or string payload to parse.
   * @returns The halfred {@link Resource} for further link and embedding exploration.
   */
  protected parse(body: unknown): Resource {
    // halfred.parse accepts a json object or string.
    return halfred.parse(body as any);
  }

  /**
   * Resolves a URL from a string or a resource instance.
   *
   * Strategy:
   * - If a string is provided, it is treated as the URL.
   * - If a resource has `_links.self.href`, that href is used.
   * - Otherwise falls back to the configured `baseUrl`.
   *
   * @param resourceOrUrl - The resource instance or explicit URL.
   * @returns A URL string to use for HTTP operations.
   */
  protected resolveUrl(resourceOrUrl: string | T): string {
    if (typeof resourceOrUrl === 'string') return resourceOrUrl;
    const links = (resourceOrUrl as any)._links;
    if (links && links.self && links.self.href) return links.self.href;

    return this.baseUrl;
  }
}
