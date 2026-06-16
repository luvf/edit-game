import {
  Component,
  EventEmitter,
  inject,
  Input,
  OnChanges,
  Output,
  signal,
  SimpleChanges,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Cut } from '../../core/models/models';
import { MatButtonModule } from '@angular/material/button';
import { CutsService } from '../../core/services/misc-hateoas-models.service';
import { FormsModule } from '@angular/forms';
import { MatTabsModule } from '@angular/material/tabs';
import { GameEditCutsStateService } from '../game-edit-cuts/game-edit-cuts-state';

type Point = {
  in: number;
  out: number;
  point?: 'left' | 'right' | 'nopoint';
};

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

  imports: [CommonModule, MatButtonModule, FormsModule, MatTabsModule],
  templateUrl: './cut-detail.html',
  styleUrl: './cut-detail.css',
})
export class CutDetailComponent implements OnChanges {
  @Input() cut: Cut | null = null;
  @Output() seekToFrame = new EventEmitter<number>();

  payload = signal<CutPayload | null>(null);
  parseError: string | null = null;
  valid = signal(true);
  queuePreset = 'medium';
  private http = inject(HttpClient);
  private cutService = inject(CutsService);
  private state = inject(GameEditCutsStateService);

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

  addPointAfter(index: number): void {
    const payload = this.payload();
    if (!payload) return;

    const current = payload.points[index];
    const next = payload.points[index + 1];
    const currentOut = Number(current?.out ?? 0);
    const nextIn = Number(next?.in ?? currentOut + 2);
    const newIn = Number.isFinite(currentOut) ? currentOut + 1 : 0;
    const newOut = Number.isFinite(nextIn) ? nextIn - 1 : newIn;

    const points = [...payload.points];
    points.splice(index + 1, 0, { in: newIn, out: newOut, point: 'nopoint' });
    this.payload.set({ ...payload, points });
  }

  removePoint(index: number): void {
    const payload = this.payload();
    if (!payload) return;
    const points = [...payload.points];
    points.splice(index, 1);
    this.payload.set({ ...payload, points });
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

  addOverlayAfter(index: number, type?: Overlay['type']): void {
    const payload = this.payload();
    if (!payload) return;
    const current = payload.overlays[index];
    const nextType = type ?? current?.type ?? 'Warning';

    const overlay =
      nextType === 'TeamIntroduction'
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

    const overlays = [...payload.overlays];
    overlays.splice(index + 1, 0, overlay);
    this.payload.set({ ...payload, overlays });
  }

  formatTimecode(frameValue: number): string {
    if (!Number.isFinite(frameValue) || frameValue < 0) return '00:00:00:00';
    const fps = 60;
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
    const fps = 60;
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
    this.parseError = null;
    const path = this.cut?.json_file?.trim();
    if (!path || !this.isFetchablePath(path)) return;

    this.http.get(path, { responseType: 'text' }).subscribe({
      next: (text) => queueMicrotask(() => this.parseJson(text)),
      error: (e) => {
        this.parseError = e?.message
          ? String(e.message)
          : 'Erreur de chargement';
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
      this.parseError = e?.message ? String(e.message) : 'Invalid JSON';
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
