// TypeScript
import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {HateoasService} from '../../core/hateoas.service'; // adapte le chemin si besoin
import {Cut} from './cut.model';
import {Game} from '../games/game.model';


/**
 * Service providing HATEOAS-powered operations for Cut resources.
 *
 * Features:
 * - Configures the collection endpoint for listing/creating cuts.
 * - Exposes helpers to follow domain-specific relations (e.g., `game`).
 */
@Injectable({providedIn: 'root'})
export class CutService extends HateoasService<Cut> {

  /**
   * Creates the service and sets the default collection URL for cuts.
   *
   * Replace the URL as needed to match your backend configuration.
   *
   * @param http - Angular HttpClient instance injected by DI.
   */
  constructor(http: HttpClient) {
    // Remplacez l’URL ci‑dessous par celle de votre collection si différente
    super(http);
    this.setCollectionUrl('/api/cuts/');
  }


  /**
   * Follows the 'game' relation to fetch the associated Game for a given Cut.
   *
   * @param resourceOrUrl - A Cut resource instance or its URL.
   * @returns An observable emitting the associated {@link Game}.
   */
  game(resourceOrUrl: string | Cut) {
    return this.follow<Game>(resourceOrUrl, 'game');
  }

}
