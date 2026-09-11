import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
  model,
  OnDestroy,
  output,
  signal,
} from '@angular/core';
import { CutCurves } from '../../core/models/models';
import {
  CutEvent,
  CutPoint,
  ReviewMarker,
} from '../game-edit-cuts/game-edit-cuts-state';

/** Un point projete sur la barre, en pourcentage de la duree du rush. */
type Segment = {
  /** Rang dans la liste de points, conserve : le filtrage decale les indices. */
  index: number;
  left: number;
  width: number;
  point: 'left' | 'right' | 'nopoint';
  title: string;
};

/** Un evenement pose sur la barre, en pourcentage de la duree du rush. */
type Marker = {
  left: number;
  type: CutEvent['type'];
  title: string;
};

/** Un endroit a verifier, pose sur la barre. */
type ReviewTick = {
  left: number;
  frame: number;
  source: ReviewMarker['source'];
  title: string;
};

/** Une courbe prete a etre dessinee, plus le seuil qu'un pic devait franchir. */
type Curve = {
  channel: 'in' | 'out' | 'inside';
  points: string;
  threshold: number | null;
};

/** Hauteur du repere des courbes. L'axe des x reste celui de la barre. */
const CURVE_HEIGHT = 100;

@Component({
  selector: 'app-cut-timeline',
  standalone: true,
  templateUrl: './cut-timeline.html',
  styleUrl: './cut-timeline.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CutTimelineComponent implements OnDestroy {
  readonly durationFrames = input(0);
  readonly currentFrame = input(0);
  readonly points = input<CutPoint[]>([]);
  readonly events = input<CutEvent[]>([]);
  readonly fps = input(60);
  /**
   * Les courbes du modele, quand le cut en porte. Absentes, la bande n'est
   * pas rendue du tout : un cut monte a la main n'en aura jamais.
   */
  readonly curves = input<CutCurves | null>(null);
  /**
   * Ce que proposerait un autre reglage de seuils. Dessine sous le montage
   * courant, pour comparer avant d'ecraser quoi que ce soit.
   */
  readonly previewPoints = input<CutPoint[]>([]);
  /** Les endroits que le modele signale, poses sur la barre et cliquables. */
  readonly reviewMarkers = input<ReviewMarker[]>([]);

  readonly seek = output<number>();
  /** Point survole, ici ou dans la liste de points. */
  readonly hoveredIndex = model<number | null>(null);

  /** Frame survolee, pour l'infobulle. `null` quand le curseur est sorti. */
  readonly hoverFrame = signal<number | null>(null);

  readonly segments = computed<Segment[]>(() => this.project(this.points()));

  /** Projette une liste de points en barres, en pourcentage de la duree. */
  private project(points: CutPoint[]): Segment[] {
    const duration = this.durationFrames();
    if (duration <= 0) return [];

    return points
      .map((point, index) => {
        const start = Math.max(0, Math.min(duration, point.in));
        const end = Math.max(start, Math.min(duration, point.out));
        return {
          index,
          left: (start / duration) * 100,
          width: Math.max(((end - start) / duration) * 100, 0.25),
          point: point.point ?? 'nopoint',
          title: `${this.timecode(start)} → ${this.timecode(end)}`,
        };
      })
      .filter((segment) => segment.left < 100);
  }

  /** Les reperes de revue, dans leur propre voie sous la barre. */
  readonly reviewTicks = computed<ReviewTick[]>(() => {
    const duration = this.durationFrames();
    if (duration <= 0) return [];

    return this.reviewMarkers()
      .filter((marker) => marker.frame >= 0 && marker.frame <= duration)
      .map((marker) => ({
        left: (marker.frame / duration) * 100,
        frame: marker.frame,
        source: marker.source,
        title: `${this.timecode(marker.frame)} — ${marker.detail}`,
      }));
  });

  /**
   * Saute a l'endroit signale.
   *
   * `stopPropagation` parce que la barre entiere est un scrub : sans ca, le
   * clic serait aussi lu comme un deplacement a la position du pointeur,
   * c'est-a-dire a quelques frames pres au lieu de la frame exacte.
   */
  onReviewTick(tick: ReviewTick, event: Event): void {
    event.stopPropagation();
    this.seek.emit(tick.frame);
  }

  /** L'apercu d'un autre reglage, sur le meme axe que le montage courant. */
  readonly previewSegments = computed<Segment[]>(() =>
    this.project(this.previewPoints()),
  );

  /**
   * Les evenements du cut, poses a leur timecode.
   *
   * Un changement de cote ne se voit nulle part ailleurs : dans la liste on
   * lit son timecode, ici on voit entre quels points il tombe.
   */
  readonly markers = computed<Marker[]>(() => {
    const duration = this.durationFrames();
    if (duration <= 0) return [];

    return this.events()
      .filter((event) => event.tc >= 0 && event.tc <= duration)
      .map((event) => ({
        left: (event.tc / duration) * 100,
        type: event.type,
        title: `${this.timecode(event.tc)} — ${event.label}`,
      }));
  });

  readonly playheadPercent = computed(() => {
    const duration = this.durationFrames();
    if (duration <= 0) return 0;
    return Math.max(0, Math.min(100, (this.currentFrame() / duration) * 100));
  });

  readonly hoverPercent = computed(() => {
    const duration = this.durationFrames();
    const frame = this.hoverFrame();
    if (duration <= 0 || frame === null) return 0;
    return Math.max(0, Math.min(100, (frame / duration) * 100));
  });

  readonly hoverTimecode = computed(() => {
    const frame = this.hoverFrame();
    return frame === null ? '' : this.timecode(frame);
  });

  /**
   * Jusqu'ou les courbes s'etendent sur la barre, en pourcentage.
   *
   * Les courbes sont en secondes de l'archive, la barre en frames du rush.
   * La conversion se fait ici plutot que d'etaler les courbes sur toute la
   * largeur : si les deux durees divergent, ca doit se voir.
   */
  readonly curveSpan = computed(() => {
    const curves = this.curves();
    const duration = this.durationFrames();
    if (!curves || duration <= 0) return 0;
    const fps = curves.fps || this.fps();
    return (curves.duration * fps * 100) / duration;
  });

  /** Les trois courbes, en coordonnees du repere de la bande. */
  readonly curveShapes = computed<Curve[]>(() => {
    const curves = this.curves();
    const span = this.curveSpan();
    if (!curves || span <= 0) return [];

    const thresholds = curves.decode?.threshold ?? {};
    return (['inside', 'out', 'in'] as const)
      .filter((channel) => curves[channel]?.length)
      .map((channel) => ({
        channel,
        points: this.polyline(curves[channel], span),
        threshold: channel === 'inside' ? null : (thresholds[channel] ?? null),
      }));
  });

  /** La hauteur d'un seuil dans le repere, pour le trait en pointilles. */
  thresholdY(threshold: number): number {
    return (1 - threshold) * CURVE_HEIGHT;
  }

  /**
   * Les trois probabilites sous le curseur, pour l'infobulle.
   *
   * C'est ce qui rend la bande lisible : on voit qu'un pic monte, on veut
   * savoir de combien il a manque le seuil.
   */
  readonly hoverValues = computed<string>(() => {
    const curves = this.curves();
    const frame = this.hoverFrame();
    const duration = this.durationFrames();
    if (!curves || frame === null || duration <= 0) return '';

    const span = this.curveSpan();
    const length = curves.in?.length ?? 0;
    if (!length || span <= 0) return '';
    const ratio = (frame / duration) * (100 / span);
    if (ratio < 0 || ratio > 1) return '';

    const index = Math.min(length - 1, Math.round(ratio * (length - 1)));
    const read = (values: number[] | undefined) =>
      (values?.[index] ?? 0).toFixed(2);
    return `in ${read(curves.in)} · out ${read(curves.out)} · dans ${read(
      curves.inside,
    )}`;
  });

  private scrubbing = false;
  private pendingSeekFrame: number | null = null;
  private rafId: number | null = null;

  ngOnDestroy(): void {
    if (this.rafId !== null) cancelAnimationFrame(this.rafId);
  }

  onPointerDown(event: PointerEvent): void {
    if (this.durationFrames() <= 0) return;
    const track = event.currentTarget as HTMLElement;
    track.setPointerCapture(event.pointerId);
    this.scrubbing = true;
    this.queueSeek(this.frameAt(event, track));
  }

  onPointerMove(event: PointerEvent): void {
    if (this.durationFrames() <= 0) return;
    const track = event.currentTarget as HTMLElement;
    const frame = this.frameAt(event, track);
    this.hoverFrame.set(frame);
    if (this.scrubbing) this.queueSeek(frame);
  }

  onPointerUp(event: PointerEvent): void {
    this.scrubbing = false;
    const track = event.currentTarget as HTMLElement;
    if (track.hasPointerCapture(event.pointerId)) {
      track.releasePointerCapture(event.pointerId);
    }
  }

  onPointerLeave(): void {
    this.hoverFrame.set(null);
    this.hoveredIndex.set(null);
  }

  onSegmentEnter(index: number): void {
    this.hoveredIndex.set(index);
  }

  onSegmentLeave(): void {
    this.hoveredIndex.set(null);
  }

  /**
   * Projette une courbe en attribut `points` d'une polyline.
   *
   * Le repere fait 100 de large comme la barre, donc un x est deja un
   * pourcentage, et y descend quand la probabilite monte.
   */
  private polyline(values: number[], span: number): string {
    const last = Math.max(values.length - 1, 1);
    return values
      .map((value, index) => {
        const x = ((index / last) * span).toFixed(3);
        const y = ((1 - value) * CURVE_HEIGHT).toFixed(2);
        return `${x},${y}`;
      })
      .join(' ');
  }

  timecode(frameValue: number): string {
    const nominalFps = Math.max(1, Math.round(this.fps()));
    const totalSeconds = Math.floor(Math.max(0, frameValue) / nominalFps);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor(totalSeconds / 60) % 60;
    const seconds = totalSeconds % 60;
    const head = hours > 0 ? `${hours}:` : '';
    return `${head}${minutes.toString().padStart(2, '0')}:${seconds
      .toString()
      .padStart(2, '0')}`;
  }

  private frameAt(event: PointerEvent, track: HTMLElement): number {
    const rect = track.getBoundingClientRect();
    if (rect.width <= 0) return 0;
    const ratio = Math.min(
      1,
      Math.max(0, (event.clientX - rect.left) / rect.width),
    );
    return Math.round(ratio * this.durationFrames());
  }

  /**
   * Un scrub emet a chaque `pointermove`. Avec un GOP de plusieurs secondes,
   * chaque seek coute un decodage : on n'en garde qu'un par frame d'affichage.
   */
  private queueSeek(frame: number): void {
    this.pendingSeekFrame = frame;
    if (this.rafId !== null) return;

    this.rafId = requestAnimationFrame(() => {
      this.rafId = null;
      const target = this.pendingSeekFrame;
      this.pendingSeekFrame = null;
      if (target !== null) this.seek.emit(target);
    });
  }
}
