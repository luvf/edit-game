import {
  ChangeDetectionStrategy,
  Component,
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
import {
  CdkDragDrop,
  DragDropModule,
  moveItemInArray,
} from '@angular/cdk/drag-drop';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Cut } from '../../core/models/models';
import { MatButtonModule } from '@angular/material/button';
import { CutsService } from '../../core/services/misc-hateoas-models.service';
import { FormsModule } from '@angular/forms';
import { MatTabsModule } from '@angular/material/tabs';
import {
  CutPoint,
  GameEditCutsStateService,
} from '../game-edit-cuts/game-edit-cuts-state';
import { renderPresets } from '../../core/services/preset-service';
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

/** Compteur de groupes de radios, voir `switchName`. */
let nextSwitchGroupId = 0;

type TeamIntroductionOverlay = {
  type: 'TeamIntroduction';
  team1: string;
  team2: string;
  condition: string;
};

type WarningOverlay = {
  type: 'Warning';
  warning_type: string;
  text: string;
  tc: number;
  length?: number;
};

type Overlay = TeamIntroductionOverlay | WarningOverlay;

type CutPayload = {
  points: Point[];
  overlays: Overlay[];
};

@Component({
  selector: 'app-cut-detail',
  standalone: true,

  imports: [
    CommonModule,
    MatButtonModule,
    FormsModule,
    MatTabsModule,
    MatSelect,
    MatOption,
    DragDropModule,
  ],
  templateUrl: './cut-detail.html',
  styleUrl: './cut-detail.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CutDetailComponent implements OnChanges {
  @Input() cut: Cut | null = null;
  /**
   * Mise en page etroite : les points et les overlays passent en onglets au
   * lieu d'etre cote a cote. Le choix vient du parent, qui mesure le panneau ;
   * rendre les deux et en cacher une en CSS construisait chaque ligne deux fois.
   */
  readonly compact = input(false);
  @Output() seekToFrame = new EventEmitter<number>();

  payload = signal<CutPayload | null>(null);
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
      const points = this.payload()?.points ?? [];
      const isActive = this.state.activeCut()?.pk === this.cut?.pk;
      if (!isActive) return;
      this.state.activeCutPoints.set([...points]);
    });
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['cut']) {
      this.valid.set(this.cut?.valid ?? true);
      this.loadJson();
    }
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

  onFix(): void {}

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
    this.payload.set({
      ...payload,
      points: [...payload.points, { in: 0, out: 0, point: 'nopoint' }],
    });
  }

  onDropPoint(event: CdkDragDrop<Point[]>): void {
    const payload = this.payload();
    if (!payload || event.previousIndex === event.currentIndex) return;

    const points = [...payload.points];
    moveItemInArray(points, event.previousIndex, event.currentIndex);
    this.payload.set({ ...payload, points });
    this.publishPoints();
  }

  onDropOverlay(event: CdkDragDrop<Overlay[]>): void {
    const payload = this.payload();
    if (!payload || event.previousIndex === event.currentIndex) return;

    const overlays = [...payload.overlays];
    moveItemInArray(overlays, event.previousIndex, event.currentIndex);
    this.payload.set({ ...payload, overlays });
  }

  /**
   * `ngModel` ecrit dans le point sur place : le signal `payload` ne change
   * pas d'identite, donc la timeline doit etre prevenue a la main.
   */
  onPointEdited(): void {
    this.publishPoints();
  }

  removePoint(index: number): void {
    const payload = this.payload();
    if (!payload) return;
    const points = [...payload.points];
    points.splice(index, 1);
    this.payload.set({ ...payload, points });
    this.publishPoints();
  }

  addOverlay(type: Overlay['type'] = 'Warning'): void {
    const payload = this.payload() ?? { points: [], overlays: [] };

    const overlay =
      type === 'TeamIntroduction'
        ? {
            type: 'TeamIntroduction' as const,
            team1: '',
            team2: '',
            condition: '',
          }
        : {
            type: 'Warning' as const,
            warning_type: '',
            text: '',
            tc: 0,
            length: 300,
          };

    this.payload.set({
      ...payload,
      overlays: [...payload.overlays, overlay],
    });
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
    this.state.activeCutPoints.set([...(this.payload()?.points ?? [])]);
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

  removeOverlay(index: number): void {
    const payload = this.payload();
    if (!payload) return;
    const overlays = [...payload.overlays];
    overlays.splice(index, 1);
    this.payload.set({ ...payload, overlays });
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
        overlays: overlays
          .filter((o: any) => o && typeof o === 'object')
          .map((o: any) => this.normalizeOverlay(o))
          .filter((o: Overlay | null) => !!o) as Overlay[],
      });
    } catch (e: any) {
      this.parseError.set(e?.message ? String(e.message) : 'Invalid JSON');
    }
  }

  private normalizeOverlay(raw: any): Overlay | null {
    if (
      raw.team1 !== undefined ||
      raw.team2 !== undefined ||
      raw.condition !== undefined
    ) {
      return {
        type: 'TeamIntroduction',
        team1: String(raw.team1 ?? ''),
        team2: String(raw.team2 ?? ''),
        condition: String(raw.condition ?? ''),
      };
    }

    if (
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
      },
      null,
      2,
    );
  }
}
