import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {HateoasService} from '../../core/hateoas.service';
import {TeamLogo} from './team-logo.model';
import {Team} from '../teams/team.model';

// Remplacez par votre vrai type Team si vous avez un modèle dédié


/**
 * Service providing HATEOAS-powered operations for TeamLogo resources.
 *
 * Features:
 * - Configures the collection endpoint for listing/creating team logos.
 * - Exposes helpers to follow domain-specific relations (e.g., `teams`).
 */
@Injectable({providedIn: 'root'})
export class TeamLogoService extends HateoasService<TeamLogo> {

  /**
   * Creates the service and sets the default collection URL for team logos.
   *
   * Replace the URL as needed to match your backend configuration.
   *
   * @param http - Angular HttpClient instance injected by DI.
   */
  constructor(http: HttpClient) {
    super(http);
    this.setCollectionUrl('http://localhost:8000/api/team_logos/');
  }

  /**
   * Follows the 'teams' relation to retrieve the list of teams associated with a logo.
   *
   * @param resourceOrUrl - A TeamLogo resource instance or its URL.
   * @returns An observable emitting the associated list of {@link Team}.
   */
  teams(resourceOrUrl: string | TeamLogo) {
    return this.follow<Team[]>(resourceOrUrl, 'teams');
  }


}
