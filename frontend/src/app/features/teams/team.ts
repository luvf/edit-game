import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {HateoasService} from '../../core/hateoas.service';
import {Team} from './team.model';
import {TeamLogo} from '../team-logos/team-logo.model';


/**
 * Service providing HATEOAS-powered operations for Team resources.
 *
 * Features:
 * - Configures the collection endpoint for listing/creating teams.
 * - Inherits generic helpers to follow relations and invoke link-based actions.
 */

@Injectable({providedIn: 'root'})
export class TeamService extends HateoasService<Team> {


  /**
   * Creates the service and sets the default collection URL for teams.
   *
   * Replace the URL as needed to match your backend configuration.
   *
   * @param http - Angular HttpClient instance injected by DI.
   */
  constructor(http: HttpClient) {
    super(http);
    this.setCollectionUrl('http://localhost:8000/api/teams/');
  }

  /*
  * Follows the 'logos' relation to fetch the associated TeamLogo for a given Team.
  * @param resourceOrUrl
  * @returns An observable emitting the associated {@link TeamLogo}.
  * */
  logo(resourceOrUrl: string | Team) {
    return this.follow<TeamLogo[]>(resourceOrUrl, 'logos');
  }

}
