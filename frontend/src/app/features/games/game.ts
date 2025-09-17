import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {HateoasService} from '../../core/hateoas.service';
import {Game} from './game.model';
import {Tournament} from '../tournaments/tournament.model';
import {Cut} from '../cuts/cut.model';


/**
 * Service providing HATEOAS-powered operations for Game resources.
 *
 * Features:
 * - Configures the collection endpoint for listing/creating games.
 * - Inherits generic helpers to follow relations and invoke link-based actions.
 */

@Injectable({providedIn: 'root'})
export class GameService extends HateoasService<Game> {

  /**
   * Creates the service and sets the default collection URL for games.
   *
   * Replace the URL as needed to match your backend configuration.
   *
   * @param http - Angular HttpClient instance injected by DI.
   */
  constructor(http: HttpClient) {
    super(http);
    this.setCollectionUrl('http://localhost:8000/api/games/');
  }

  /**
   * Follows the 'tournament' relation to fetch the associated Tournament for a given Game.
   * @param resourceOrUrl
   * @returns An observable emitting the associated {@link Tournament}.
   */
  tournament(resourceOrUrl: string | Game) {
    return this.follow<Tournament>(resourceOrUrl, 'tournament');
  }

  /*
  * Follows the 'cuts' relation to fetch the associated Cuts for a given Game.
  * @param resourceOrUrl
  * @returns An observable emitting the associated {@link Cut[]}.
  * */
  cuts(resourceOrUrl: string | Game) {
    // Renvoie Observable<Cut[]>
    return this.follow<Cut[]>(resourceOrUrl, 'cuts');
  }

}
