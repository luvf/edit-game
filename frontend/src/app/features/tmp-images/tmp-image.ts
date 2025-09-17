import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {HateoasService} from '../../core/hateoas.service';
import {TmpImage} from './tmp-image.model';


/**
 * Service providing HATEOAS-powered operations for TmpImage resources.
 *
 * Features:
 * - Configures the collection endpoint for listing/creating temporary images.
 * - Inherits generic helpers to follow relations and invoke link-based actions.
 */
@Injectable({providedIn: 'root'})
export class TmpImageService extends HateoasService<TmpImage> {
  /**
   * Creates the service and sets the default collection URL for temporary images.
   *
   * Replace the URL as needed to match your backend configuration.
   *
   * @param http - Angular HttpClient instance injected by DI.
   */
  constructor(http: HttpClient) {
    super(http);
    this.setCollectionUrl('http://localhost:8000/api/tmp-images/');

  }


}
