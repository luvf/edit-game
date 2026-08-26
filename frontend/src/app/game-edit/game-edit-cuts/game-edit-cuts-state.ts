import { Injectable, signal } from '@angular/core';
import { Cut } from '../../core/models/models';
import { FALLBACK_FPS } from '../video-player/video-player';

@Injectable()
export class GameEditCutsStateService {
  readonly rushFrame = signal(0);
  readonly renderedFrame = signal(0);
  readonly activeCut = signal<Cut | null>(null);
  /**
   * Frame rate du rush, alimente par le player. Les points de cut sont
   * exprimes en frames de ce rush : c'est ce fps qui doit servir a les
   * convertir en secondes, pas une constante.
   */
  readonly rushFps = signal(FALLBACK_FPS);
}
