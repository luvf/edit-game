import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  EventEmitter,
  inject,
  Input,
  input,
  OnChanges,
  Output,
  signal,
  SimpleChanges,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import {
  Cut,
  CutComment,
  CutReviewItem,
  DecodeSettings,
} from '../../core/models/models';
import { MatButtonModule } from '@angular/material/button';
import { CutsService } from '../../core/services/misc-hateoas-models.service';
import { FormsModule } from '@angular/forms';
import {
  CutEvent,
  CutPoint,
  GameEditCutsStateService,
  ReviewMarker,
} from '../game-edit-cuts/game-edit-cuts-state';
import { renderPresets } from '../../core/services/preset-service';
import { buildStates, stateAt } from '../scoreboard';
import { MatOption, MatSelect } from '@angular/material/select';

type Point = CutPoint;

/**
 * Les trois positions du selecteur de point, dans l'ordre affiche. `short` est
 * ce qui tient dans la ligne, `label` ce que disent l'infobulle et le lecteur
 * d'ecran.
 */
const POINT_OPTIONS: {
  value: NonNullable<Point['point']>;
  short: string;
  label: string;
}[] = [
  { value: 'left', short: 'L', label: 'left' },
  { value: 'nopoint', short: '–', label: 'nopoint' },
  { value: 'right', short: 'R', label: 'right' },
];

/** Les seuils mesures, ceux avec lesquels le modele a propose la premiere fois. */
const DEFAULT_DECODE: DecodeSettings = {
  threshold_in: 0.5,
  threshold_out: 0.7,
  min_gap: 30,
  snap: true,
};

/** Compteur de groupes de radios, voir `switchName`. */
let nextSwitchGroupId = 0;

/**
 * Ce qu'est le match. Attendu sur tout cut : c'est lui qui donne la carte
 * d'ouverture et le nombre de sets. L'ancien nom `TeamIntroduction` est
 * encore lu par le back, donc les fichiers deja ecrits passent.
 */
type GameInfoOverlay = {
  type: 'GameInfo';
  team1: string;
  team2: string;
  condition: string;
  sets_to_win?: number;
};

/**
 * Un evenement qui change la lecture du score sans rien dessiner : les
 * equipes changent de cote, ou un set se termine.
 */
type ScoreEventOverlay = {
  type: 'SideSwitch' | 'SetEnd';
  tc: number;
};

type WarningOverlay = {
  type: 'Warning';
  warning_type: string;
  text: string;
  tc: number;
  length?: number;
};

type Overlay = GameInfoOverlay | ScoreEventOverlay | WarningOverlay;

/** Tout ce qui vit dans la liste, hors les infos du match. */
type TimedOverlay = ScoreEventOverlay | WarningOverlay;

/**
 * Une ligne de la liste unique : un point du montage, ou un evenement.
 *
 * Les deux sont ranges ensemble et tries par timecode, parce qu'un
 * changement de cote n'a de sens qu'entre deux points precis : dans une
 * colonne separee on ne voit jamais ou il tombe.
 */
type Row =
  | { kind: 'point'; point: Point; index: number }
  | { kind: 'event'; overlay: TimedOverlay };

/** Le timecode qui range une ligne dans la liste. */
function rowFrame(row: Row): number {
  return row.kind === 'point' ? row.point.in : row.overlay.tc;
}

/**
 * Le timecode d'un overlay. Les infos du match n'en ont pas : elles restent
 * en tete, d'ou le -1.
 */
function overlayFrame(overlay: Overlay): number {
  return overlay.type === 'GameInfo' ? -1 : overlay.tc;
}

/**
 * Ce que la timeline pose sur la barre : tout ce qui a un timecode.
 *
 * Les infos du match n'en font pas partie, elles n'ont pas d'instant.
 */
function timelineEvents(overlays: readonly Overlay[]): CutEvent[] {
  return overlays
    .filter((overlay): overlay is TimedOverlay => overlay.type !== 'GameInfo')
    .map((overlay) => ({
      type: overlay.type,
      tc: overlay.tc,
      label:
        overlay.type === 'Warning'
          ? overlay.warning_type || overlay.text || 'warning'
          : overlay.type === 'SideSwitch'
            ? 'changement de côté'
            : 'fin de set',
    }));
}

type CutPayload = {
  points: Point[];
  overlays: Overlay[];
  /**
   * Le bloc laisse par le modele. Conserve tel quel, y compris a travers une
   * sauvegarde manuelle : c'est la provenance du cut et la liste des endroits
   * a verifier, et l'ecraser en enregistrant un timecode serait une perte
   * silencieuse.
   */
  comment?: CutComment;
};

/** Une ligne de la liste « a verifier », prete a etre affichee. */
type ReviewRow = ReviewMarker & { timecode: string };

/** Ce que chaque motif de revue veut dire, en francais et en une ligne. */
const REVIEW_LABELS: Record<string, string> = {
  in_incertain: 'début peu sûr',
  out_incertain: 'fin peu sûre',
  segment_long: 'point anormalement long',
  pause_longue: 'longue pause',
  in_isole: 'début sans fin',
  out_orphelin: 'fin sans début',
  in_non_referme: 'début non refermé',
  segment_court: 'segment trop court',
  segment_trop_long: 'segment trop long',
  inside_faible: 'segment rejeté',
  fusion: 'segments fusionnés',
};

@Component({
  selector: 'app-cut-detail',
  standalone: true,

  imports: [CommonModule, MatButtonModule, FormsModule, MatSelect, MatOption],
  templateUrl: './cut-detail.html',
  styleUrl: './cut-detail.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CutDetailComponent implements OnChanges {
  @Input() cut: Cut | null = null;
  /**
   * Mise en page etroite : le panneau d'infos passe au-dessus de la liste en
   * une seule colonne. Le choix vient du parent, qui mesure le panneau.
   */
  readonly compact = input(false);
  @Output() seekToFrame = new EventEmitter<number>();

  payload = signal<CutPayload | null>(null);
  /**
   * La liste affichee : points et evenements ranges ensemble.
   *
   * Elle n'est reconstruite qu'au chargement, a l'ajout, a la suppression et
   * sur « Fix ». Trier a chaque frappe ferait sauter la ligne sous le curseur
   * pendant qu'on tape un timecode.
   */
  readonly rows = signal<Row[]>([]);
  readonly parseError = signal<string | null>(null);
  valid = signal(true);
  queuePreset = 'medium';
  protected readonly renderPresets = renderPresets;
  protected readonly pointOptions = POINT_OPTIONS;
  /**
   * Prefixe des `name` du selecteur de point. Les radios de meme `name` forment
   * un seul groupe pour le navigateur, et `preserveContent` garde plusieurs
   * cuts vivants : sans prefixe unique par composant, changer le point d'une
   * ligne deselectionnerait la meme ligne d'un autre cut.
   */
  protected readonly switchName = `cut-point-${++nextSwitchGroupId}-`;
  /**
   * Les endroits a verifier, dans l'ordre du temps.
   *
   * Ce que le modele a propose sans en etre sur et ce qu'il a failli
   * proposer sont melanges : pour le monteur c'est la meme consigne — va
   * regarder la — et les separer l'obligerait a lire deux listes.
   */
  readonly reviewRows = computed<ReviewRow[]>(() => {
    const comment = this.payload()?.comment;
    if (!comment) return [];

    const fps = comment.fps || this.state.rushFps();
    const rows = [
      ...this.toMarkers(comment.review, 'review', fps),
      ...this.toMarkers(comment.rejected, 'rejected', fps),
    ].sort((a, b) => a.frame - b.frame);
    return rows.map((marker) => ({
      ...marker,
      timecode: this.formatTimecode(marker.frame),
    }));
  });

  /** Le libelle francais d'un motif, ou le motif brut s'il est inconnu. */
  reviewLabel(kind: string): string {
    return REVIEW_LABELS[kind] ?? kind;
  }

  /** Envoie le lecteur a l'endroit signale. */
  onReviewSeek(row: ReviewRow): void {
    this.seekToFrame.emit(row.frame);
  }

  private toMarkers(
    items: CutReviewItem[] | undefined,
    source: ReviewMarker['source'],
    fps: number,
  ): ReviewMarker[] {
    return (items ?? [])
      .filter((item) => Number.isFinite(item?.at))
      .map((item) => ({
        frame: Math.max(0, Math.round(item.at * fps)),
        kind: String(item.kind ?? ''),
        detail: String(item.detail ?? ''),
        source,
      }));
  }

  /** Reglages du decodage, quand le cut porte des courbes. */
  readonly decode = signal<DecodeSettings>({ ...DEFAULT_DECODE });
  /** Resume du dernier apercu, ou `null` tant qu'on n'a rien tourne. */
  readonly decodePreview = signal<{
    segments: number;
    kept: number;
    snapped: boolean;
  } | null>(null);
  readonly decodePending = signal(false);
  private decodeTimer: ReturnType<typeof setTimeout> | null = null;
  private http = inject(HttpClient);
  private cutService = inject(CutsService);
  private state = inject(GameEditCutsStateService);
  /** Point survole, partage avec la timeline sous le lecteur. */
  readonly hoveredPoint = this.state.hoveredPointIndex;

  constructor() {
    // La timeline vit a cote du lecteur : seul le cut ouvert lui envoie ses
    // sections, sinon les onglets gardes en vie par `preserveContent`
    // s'ecraseraient les uns les autres.
    effect(() => {
      // Les deux signaux se lisent avant tout `return` : un effet ne se
      // reabonne qu'a ce qu'il a lu au dernier passage, et sortir plus haut
      // le rendrait sourd aux changements de `payload`.
      const payload = this.payload();
      const points = payload?.points ?? [];
      const overlays = payload?.overlays ?? [];
      const isActive = this.state.activeCut()?.pk === this.cut?.pk;
      if (!isActive) return;
      this.state.activeCutPoints.set([...points]);
      this.state.activeCutEvents.set(timelineEvents(overlays));
      this.state.reviewMarkers.set(this.reviewRows());
    });
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['cut']) {
      this.valid.set(this.cut?.valid ?? true);
      this.loadJson();
    }
  }

  /**
   * Redemande un apercu apres chaque mouvement de curseur.
   *
   * Attendre un court instant plutot que de tirer a chaque pixel : le
   * re-decodage coute une passe de numpy, pas un GPU, mais un curseur emet
   * des dizaines d'evenements par seconde.
   */
  onDecodeChange<K extends keyof DecodeSettings>(
    key: K,
    value: DecodeSettings[K],
  ): void {
    this.decode.set({ ...this.decode(), [key]: value });
    if (this.decodeTimer) clearTimeout(this.decodeTimer);
    this.decodeTimer = setTimeout(() => this.previewDecode(), 250);
  }

  /** Abandonne l'apercu et remet les seuils mesures. */
  onDecodeReset(): void {
    if (this.decodeTimer) clearTimeout(this.decodeTimer);
    this.decode.set({ ...DEFAULT_DECODE });
    this.decodePreview.set(null);
    this.state.previewPoints.set([]);
  }

  /**
   * Ecrit l'apercu dans le cut.
   *
   * C'est le seul geste destructif de ce panneau : il remplace la liste de
   * points, corrections manuelles comprises, d'ou le bouton separe.
   */
  onDecodeApply(): void {
    if (!this.cut) return;
    this.decodePending.set(true);
    this.cutService.redecode(this.cut, this.decode(), true).subscribe({
      next: () => {
        this.decodePending.set(false);
        this.decodePreview.set(null);
        this.state.previewPoints.set([]);
        this.loadJson();
      },
      error: (e) => {
        this.decodePending.set(false);
        console.error('Erreur lors du re-decodage', e);
      },
    });
  }

  private previewDecode(): void {
    if (!this.cut) return;
    this.decodePending.set(true);
    this.cutService.redecode(this.cut, this.decode()).subscribe({
      next: (result) => {
        this.decodePending.set(false);
        if (this.state.activeCut()?.pk !== this.cut?.pk) return;
        this.decodePreview.set({
          segments: result.segments,
          kept: result.stats.kept,
          snapped: result.snapped,
        });
        this.state.previewPoints.set(
          result.points.map((point) => ({ in: point.in, out: point.out })),
        );
      },
      error: (e) => {
        this.decodePending.set(false);
        console.error("Erreur lors de l'apercu du re-decodage", e);
      },
    });
  }

  onSave(): void {
    if (!this.cut) return;
    const json = this.buildJson();
    const file = new File([json], `cut-${this.cut.pk ?? 'new'}.json`, {
      type: 'application/json',
    });
    const formData = new FormData();
    formData.append('json_file', file);
    this.cutService.update(this.cut, formData as any).subscribe({
      next: () => {},
      error: (e) => console.error('Erreur lors de la sauvegarde du cut', e),
    });
  }

  /**
   * Range la liste par timecode, et l'ecrit dans le fichier.
   *
   * L'ordre des points est celui du montage : ffmpeg concatene dans l'ordre
   * de la liste, pas dans celui des timecodes. Trier ici fait donc les deux
   * a la fois — remettre la liste en ordre et remettre le montage en ordre.
   */
  /** Le score du tableau devant chaque point de la liste. */
  readonly boardStates = computed(() => {
    const payload = this.payload();
    if (!payload) return [];
    const events = payload.overlays.filter(
      (overlay): overlay is ScoreEventOverlay =>
        overlay.type === 'SideSwitch' || overlay.type === 'SetEnd',
    );
    return buildStates(payload.points, events);
  });

  /**
   * Le score affiche en face d'un point : celui avec lequel l'action
   * commence, comme un vrai tableau pendant le jeu.
   */
  scoreFor(row: Row): string {
    if (row.kind !== 'point') return '';
    const state = stateAt(this.boardStates(), row.index);
    return `${state.leftScore} – ${state.rightScore}`;
  }

  onFix(): void {
    this.sortPayload();
    this.rebuildRows();
    this.onPointEdited();
  }

  /** Range les points par `in` et les overlays par `tc`, sur place. */
  private sortPayload(): void {
    const payload = this.payload();
    if (!payload) return;
    const points = [...payload.points].sort((a, b) => a.in - b.in);
    const overlays = [...payload.overlays].sort(
      (a, b) => overlayFrame(a) - overlayFrame(b),
    );
    this.payload.set({ ...payload, points, overlays });
  }

  /** Recalcule la liste affichee a partir du payload. */
  private rebuildRows(): void {
    const payload = this.payload();
    if (!payload) {
      this.rows.set([]);
      return;
    }
    const rows: Row[] = [
      ...payload.points.map((point, index) => ({
        kind: 'point' as const,
        point,
        index,
      })),
      ...payload.overlays
        .filter(
          (overlay): overlay is TimedOverlay => overlay.type !== 'GameInfo',
        )
        .map((overlay) => ({ kind: 'event' as const, overlay })),
    ];
    rows.sort((a, b) => rowFrame(a) - rowFrame(b));
    this.rows.set(rows);
  }

  /** Les infos du match, creees si le fichier n'en a pas encore. */
  gameInfo(): GameInfoOverlay | null {
    const payload = this.payload();
    if (!payload) return null;
    const found = payload.overlays.find(
      (overlay): overlay is GameInfoOverlay =>
        overlay.type === 'GameInfo' ||
        (overlay.type as string) === 'TeamIntroduction',
    );
    return found ? { ...found, type: 'GameInfo' } : null;
  }

  /** Ajoute le bloc d'infos du match, absent des fichiers anciens. */
  addGameInfo(): void {
    const payload = this.payload() ?? { points: [], overlays: [] };
    if (this.gameInfo()) return;
    const info: GameInfoOverlay = {
      type: 'GameInfo',
      team1: '',
      team2: '',
      condition: '',
    };
    this.payload.set({ ...payload, overlays: [info, ...payload.overlays] });
  }

  /** Ajoute un evenement, place a la frame courante du lecteur. */
  addEvent(type: TimedOverlay['type']): void {
    const payload = this.payload() ?? { points: [], overlays: [] };
    const tc = Math.max(Math.round(this.state.rushFrame()), 0);
    const overlay: TimedOverlay =
      type === 'Warning'
        ? { type: 'Warning', warning_type: '', text: '', tc, length: 300 }
        : { type, tc };
    this.payload.set({ ...payload, overlays: [...payload.overlays, overlay] });
    // Range tout de suite : le score de chaque point se lit dans l'ordre des
    // timecodes, et un evenement pose au milieu doit compter des maintenant.
    this.sortPayload();
    this.rebuildRows();
  }

  /** Le nom lisible d'un evenement qui ne se dessine pas. */
  eventLabel(type: TimedOverlay['type']): string {
    if (type === 'SideSwitch') return 'changement de côté';
    if (type === 'SetEnd') return 'fin de set';
    return type;
  }

  /** Cale un evenement sur la frame courante du lecteur. */
  setEventFromCurrentFrame(overlay: TimedOverlay): void {
    overlay.tc = Math.max(Math.round(this.state.rushFrame()), 0);
    this.onPointEdited();
  }

  /**
   * Ecrit un champ des infos du match.
   *
   * Passe par le payload plutot que par un `ngModel` a deux sens : le bloc
   * est retrouve par recherche dans la liste, donc l'objet rendu par
   * `gameInfo()` est une copie.
   */
  setGameInfo(field: keyof GameInfoOverlay, value: unknown): void {
    const payload = this.payload();
    if (!payload) return;
    const overlays = payload.overlays.map((overlay) => {
      if (overlay.type !== 'GameInfo') return overlay;
      if (field === 'sets_to_win') {
        const sets = Number(value);
        return {
          ...overlay,
          sets_to_win: Number.isFinite(sets) && sets > 0 ? sets : undefined,
        };
      }
      return { ...overlay, [field]: String(value ?? '') };
    });
    this.payload.set({ ...payload, overlays });
  }

  /** Retire une ligne, point ou evenement. */
  removeRow(row: Row): void {
    const payload = this.payload();
    if (!payload) return;
    if (row.kind === 'point') {
      this.payload.set({
        ...payload,
        points: payload.points.filter((point) => point !== row.point),
      });
    } else {
      this.payload.set({
        ...payload,
        overlays: payload.overlays.filter((overlay) => overlay !== row.overlay),
      });
    }
    this.rebuildRows();
    this.onPointEdited();
  }

  onAddToQueue(): void {
    if (!this.cut?.pk) return;
    const preset = this.queuePreset || 'medium';
    this.cutService.render_cut(this.cut, { preset, to_queue: true }).subscribe({
      next: () => {},
      error: (e) => console.error("Erreur lors de l'ajout a la queue", e),
    });
  }

  addPoint(): void {
    const payload = this.payload();
    if (!payload) {
      this.payload.set({ points: [], overlays: [] });
      return;
    }
    const at = Math.max(Math.round(this.state.rushFrame()), 0);
    this.payload.set({
      ...payload,
      points: [...payload.points, { in: at, out: at, point: 'nopoint' }],
    });
    this.sortPayload();
    this.rebuildRows();
  }

  /**
   * `ngModel` ecrit dans le point sur place : le signal `payload` ne change
   * pas d'identite, donc la timeline doit etre prevenue a la main.
   */
  onPointEdited(): void {
    this.publishPoints();
  }

  formatTimecode(frameValue: number): string {
    if (!Number.isFinite(frameValue) || frameValue < 0) return '00:00:00:00';
    const fps = this.nominalRushFps();
    const totalFrames = Math.floor(frameValue);
    const totalSeconds = Math.floor(totalFrames / fps);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor(totalSeconds / 60) % 60;
    const seconds = totalSeconds % 60;
    const frames = totalFrames % fps;
    return `${hours.toString().padStart(2, '0')}:${minutes
      .toString()
      .padStart(2, '0')}:${seconds.toString().padStart(2, '0')}:${frames
      .toString()
      .padStart(2, '0')}`;
  }

  formatDurationFrames(startFrame: number, endFrame: number): string {
    if (!Number.isFinite(startFrame) || !Number.isFinite(endFrame))
      return '00:00:00';
    const fps = this.nominalRushFps();
    const totalFrames = Math.max(
      0,
      Math.floor(endFrame) - Math.floor(startFrame),
    );
    const totalSeconds = Math.floor(totalFrames / fps);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    const frames = totalFrames % fps;
    return `${minutes.toString().padStart(2, '0')}:${seconds
      .toString()
      .padStart(2, '0')}:${frames.toString().padStart(2, '0')}`;
  }

  setFromCurrentFrame(point: Point, field: 'in' | 'out'): void {
    const frame = this.state.rushFrame();
    if (!Number.isFinite(frame as number)) return;
    point[field] = Math.max(0, Math.floor(frame as number));
    this.publishPoints();
  }

  private publishPoints(): void {
    if (this.state.activeCut()?.pk !== this.cut?.pk) return;
    const payload = this.payload();
    this.state.activeCutPoints.set([...(payload?.points ?? [])]);
    this.state.activeCutEvents.set(timelineEvents(payload?.overlays ?? []));
    this.state.reviewMarkers.set(this.reviewRows());
  }

  /**
   * Fps du rush arrondi a l'entier : les timecodes affichent un compteur de
   * frames, qui doit rester entier meme sur du 59.94.
   */
  private nominalRushFps(): number {
    return Math.max(1, Math.round(this.state.rushFps()));
  }

  /**
   * Temps mort entre la fin de ce point et le debut du suivant, au format
   * mm:ss:ff. `null` sur le dernier point : il n'y a pas de suivant.
   */
  gapToNext(index: number): string | null {
    const payload = this.payload();
    if (!payload) return null;
    const current = payload.points[index];
    const next = payload.points[index + 1];
    if (!current || !next) return null;
    return this.formatDurationFrames(current.out, next.in);
  }

  setHoveredPoint(index: number | null): void {
    this.hoveredPoint.set(index);
  }

  /** Index de la position active du selecteur, pour placer le curseur. */
  pointPosition(point: Point): number {
    const value = point.point ?? 'nopoint';
    const index = POINT_OPTIONS.findIndex((option) => option.value === value);
    return index < 0 ? 1 : index;
  }

  onSeekToFrame(frameValue: number): void {
    if (!Number.isFinite(frameValue)) return;
    this.seekToFrame.emit(Math.max(0, Math.floor(frameValue)));
  }

  isInInvalid(index: number): boolean {
    const payload = this.payload();
    if (!payload) return false;
    if (index <= 0) return false;
    const current = payload.points[index];
    const prev = payload.points[index - 1];
    const currentIn = Number(current?.in ?? NaN);
    const prevOut = Number(prev?.out ?? NaN);
    if (!Number.isFinite(currentIn) || !Number.isFinite(prevOut)) return false;
    return currentIn < prevOut;
  }

  isOutInvalid(index: number): boolean {
    const payload = this.payload();
    if (!payload) return false;
    const current = payload.points[index];
    const next = payload.points[index + 1];
    if (!next) return false;
    const currentOut = Number(current?.out ?? NaN);
    const nextIn = Number(next?.in ?? NaN);
    if (!Number.isFinite(currentOut) || !Number.isFinite(nextIn)) return false;
    return currentOut > nextIn;
  }

  isRangeInvalid(point: Point): boolean {
    const start = Number(point?.in ?? NaN);
    const end = Number(point?.out ?? NaN);
    if (!Number.isFinite(start) || !Number.isFinite(end)) return false;
    return start > end;
  }

  private loadJson(): void {
    this.payload.set(null);
    this.parseError.set(null);
    const path = this.cut?.json_file?.trim();
    if (!path || !this.isFetchablePath(path)) return;

    this.http.get(path, { responseType: 'text' }).subscribe({
      next: (text) => queueMicrotask(() => this.parseJson(text)),
      error: (e) => {
        this.parseError.set(
          e?.message ? String(e.message) : 'Erreur de chargement',
        );
      },
    });
  }

  private parseJson(content: string): void {
    if (!content?.trim()) return;

    try {
      const raw = JSON.parse(content);
      const points = Array.isArray(raw?.points) ? raw.points : [];
      const overlays = Array.isArray(raw?.overlays) ? raw.overlays : [];

      this.payload.set({
        points: points
          .filter((p: any) => p && typeof p === 'object')
          .map((p: any) => ({
            in: Number(p.in),
            out: Number(p.out),
            point: p.point,
          }))
          .filter(
            (p: Point) => Number.isFinite(p.in) && Number.isFinite(p.out),
          ),
        comment:
          raw?.comment && typeof raw.comment === 'object'
            ? (raw.comment as CutComment)
            : undefined,
        overlays: overlays
          .filter((o: any) => o && typeof o === 'object')
          .map((o: any) => this.normalizeOverlay(o))
          .filter((o: Overlay | null) => !!o) as Overlay[],
      });
      this.sortPayload();
      this.rebuildRows();
    } catch (e: any) {
      this.parseError.set(e?.message ? String(e.message) : 'Invalid JSON');
    }
  }

  /**
   * Reconnait un overlay a son `type`, en retombant sur ses champs pour les
   * fichiers ecrits avant que les types existent.
   */
  private normalizeOverlay(raw: any): Overlay | null {
    const type = String(raw?.type ?? '');

    if (type === 'SideSwitch' || type === 'SetEnd') {
      const tc = Number(raw.tc);
      return Number.isFinite(tc) ? { type, tc } : null;
    }

    if (
      type === 'GameInfo' ||
      type === 'TeamIntroduction' ||
      raw.team1 !== undefined ||
      raw.team2 !== undefined ||
      raw.condition !== undefined
    ) {
      const sets = Number(raw.sets_to_win);
      return {
        type: 'GameInfo',
        team1: String(raw.team1 ?? ''),
        team2: String(raw.team2 ?? ''),
        condition: String(raw.condition ?? ''),
        sets_to_win: Number.isFinite(sets) ? sets : undefined,
      };
    }

    if (
      type === 'Warning' ||
      raw.warning_type !== undefined ||
      raw.text !== undefined ||
      raw.tc !== undefined
    ) {
      return {
        type: 'Warning',
        warning_type: String(raw.warning_type ?? ''),
        text: String(raw.text ?? ''),
        tc: Number(raw.tc ?? 0),
        length: raw.length !== undefined ? Number(raw.length) : undefined,
      };
    }

    return null;
  }

  private isFetchablePath(path: string): boolean {
    return path.startsWith('http') || path.startsWith('/');
  }

  private buildJson(): string {
    const payload = this.payload();
    if (!payload) return '';
    return JSON.stringify(
      {
        points: payload.points,
        overlays: payload.overlays,
        ...(payload.comment ? { comment: payload.comment } : {}),
      },
      null,
      2,
    );
  }
}
