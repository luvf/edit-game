
import { provideBrowserGlobalErrorListeners, provideZonelessChangeDetection, ApplicationConfig, APP_INITIALIZER, inject } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { routes } from './app.routes';
import { firstValueFrom } from 'rxjs';
import { ApiGatewayService } from './core/api-gateway';
import { API_ROOT } from './core/api-tokens.token';

function initApiRootFactory(api = inject(ApiGatewayService), apiRoot = inject(API_ROOT)) {
  return async () => {
    try {
      await firstValueFrom(api.init(apiRoot));
    } catch (e) {
      console.error('Échec de chargement de la racine HATEOAS', e);
      // Ne pas relancer l’erreur pour laisser l’app démarrer
    }
  };
}


export const appConfig: ApplicationConfig = {
  providers: [
    provideRouter(routes),
    provideHttpClient(),

    provideBrowserGlobalErrorListeners(),
    provideZonelessChangeDetection(),
    { provide: API_ROOT, useValue: 'http://localhost:8000/api/' },
    { provide: APP_INITIALIZER, multi: true, useFactory: initApiRootFactory },

  ]
};
