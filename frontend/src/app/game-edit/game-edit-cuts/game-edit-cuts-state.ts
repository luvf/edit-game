import { Injectable, signal } from '@angular/core';
import { Cut } from '../../core/models/models';
import { FALLBACK_FPS } from '../video-player/video-player';

/** Une section du cut, en frames du rush. */
export type CutPoint = {
  in: number;
  out: number;
  point?: 'left' | 'right' | 'nopoint';
};

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
  /** Duree du rush en frames, connue seulement une fois la source chargee. */
  readonly rushDurationFrames = signal(0);
  /**
   * Points du cut ouvert, republies par `CutDetailComponent` a chaque edition.
   * C'est ce que la timeline surligne sous le lecteur : elle vit a cote du
   * lecteur, pas dans l'onglet, donc elle ne peut pas les lire directement.
   */
  readonly activeCutPoints = signal<CutPoint[]>([]);
  /**
   * Index du point survole, partage entre la liste et la timeline pour que
   * survoler l'un surligne l'autre. `null` quand rien n'est survole.
   */
  readonly hoveredPointIndex = signal<number | null>(null);
}
