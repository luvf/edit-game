import { computed, Injectable, signal } from '@angular/core';
import { Cut } from '../../core/models/models';
import { FALLBACK_FPS } from '../video-player/video-player';
import { ScoringEvent, stateAtFrame } from '../scoreboard';

/** Une section du cut, en frames du rush. */
export type CutPoint = {
  in: number;
  out: number;
  point?: 'left' | 'right' | 'nopoint';
};

/**
 * Un evenement du cut, en frames du rush.
 *
 * Il n'a qu'un instant, pas de duree : un changement de cote ou une fin de
 * set tombe entre deux points, un warning s'affiche a partir de son `tc`.
 */
export type CutEvent = {
  type: 'SideSwitch' | 'SetEnd' | 'Warning';
  tc: number;
  label: string;
};

/**
 * Un repere de revue pose sur la timeline, en frames du rush.
 *
 * `review` est ce que le modele a propose sans en etre sur, `rejected` ce
 * qu'il a failli proposer. Les deux disent la meme chose au monteur : c'est
 * ici qu'il faut aller voir.
 */
export type ReviewMarker = {
  frame: number;
  kind: string;
  detail: string;
  source: 'review' | 'rejected';
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
   * Evenements du cut ouvert, publies avec les points. La timeline les pose
   * sur la barre : c'est la seule vue ou l'on voit tomber un changement de
   * cote entre deux points precis.
   */
  readonly activeCutEvents = signal<CutEvent[]>([]);
  /** Rang du point sous la tete de lecture, `null` entre deux points. */
  readonly activePointIndex = computed(() => {
    const frame = this.rushFrame();
    const index = this.activeCutPoints().findIndex(
      (point) => point.in <= frame && frame <= point.out,
    );
    return index < 0 ? null : index;
  });

  /**
   * Score que le rendu affichera a l'instant du lecteur, deja dans le sens de
   * la video : « gauche – droite ».
   *
   * Entre deux points, c'est celui du point suivant : le montage saute cet
   * intervalle, et ce qu'on veut verifier en se placant la, c'est le score
   * avec lequel la suite va repartir. Vide tant qu'aucun point n'est connu.
   */
  readonly activeCutScore = computed(() => {
    const points = this.activeCutPoints();
    if (!points.length) return '';

    const events: ScoringEvent[] = this.activeCutEvents()
      .filter((event) => event.type !== 'Warning')
      .map((event) => ({
        type: event.type as ScoringEvent['type'],
        tc: event.tc,
      }));

    const state = stateAtFrame(points, events, this.rushFrame());
    return `${state.leftScore} – ${state.rightScore}`;
  });
  /**
   * Index du point survole, partage entre la liste et la timeline pour que
   * survoler l'un surligne l'autre. `null` quand rien n'est survole.
   */
  readonly hoveredPointIndex = signal<number | null>(null);
  /**
   * Ce que donnerait un autre reglage de seuils, sans rien ecrire.
   *
   * Le re-decodage est gratuit mais ecraserait les corrections deja faites a
   * la main : il s'affiche donc en dessous du montage courant tant que
   * personne n'a dit « applique ».
   */
  readonly previewPoints = signal<CutPoint[]>([]);
  /** Les endroits a verifier du cut ouvert, vides pour un cut manuel. */
  readonly reviewMarkers = signal<ReviewMarker[]>([]);
}
