import {
  AfterViewInit,
  Component,
  ElementRef,
  inject,
  Input,
  OnChanges,
  OnDestroy,
  OnInit,
  signal,
  SimpleChanges,
  ViewChild,
} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {MatTabsModule} from '@angular/material/tabs';
import {MatButtonModule} from '@angular/material/button';
import {MatCardModule} from '@angular/material/card';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatInputModule} from '@angular/material/input';
import {MatSelectModule} from '@angular/material/select';
import {CutsService, GamesService} from '../../core/services/misc-hateoas-models.service';
import {Cut, Game} from '../../core/models/models';
import {CutDetailComponent} from '../cut-detail/cut-detail';

type CutTemplate = {
  code: string;
  label: string;
};

@Component({
  selector: 'app-game-edit-cuts',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatTabsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    CutDetailComponent,
  ],
  templateUrl: './game-edit-cuts.html',
  styleUrl: './game-edit-cuts.css',
})
export class GameEditCutsComponent implements AfterViewInit, OnChanges, OnDestroy,OnInit {
  @Input() game: Game | null = null;

  sourceProxy: string | null = null;

  currentFrame = signal(0);
  currentTimecode = signal('00:00:00');
  cuts = signal<Cut[]>([]);
  cutTemplates = signal<CutTemplate[]>([]);
  newCutName = signal('');
  selectedCutType = signal<string | null>(null);

  @ViewChild('proxyVideo') proxyVideo?: ElementRef<HTMLVideoElement>;
  protected readonly length = length;
  private frameCallbackId: number | null = null;
  private fallbackListener?: () => void;
  private gameService = inject(GamesService);
  private cutService = inject(CutsService);


  ngOnInit(): void {
    this.loadCutTemplates();
    if (!this.game) return;
    this.loadCuts();
    this.sourceProxy = this.game?.source_proxy;
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['cuts'] || changes['game']) {
      this.loadCuts();
    }
    if (changes['sourceProxy']) {
      if (!this.sourceProxy?.trim()) {
        this.stopFrameTracking();
        this.currentFrame.set(0);
        this.currentTimecode.set('00:00:00');
        return;
      }
      this.queueFrameTracking();
    }
  }

  ngAfterViewInit(): void {
    this.queueFrameTracking();
  }

  ngOnDestroy(): void {
    this.stopFrameTracking();
  }

  seekBy(steps: number): void {
    const video = this.proxyVideo?.nativeElement;
    if (!video) return;
    const offsetSeconds = steps * 1.5;
    const targetTime = Math.max(0, video.currentTime + offsetSeconds);
    video.currentTime = Number.isFinite(video.duration)
      ? Math.min(video.duration, targetTime)
      : targetTime;
  }

  seekToFrame = (frame: number): void => {
    const video = this.proxyVideo?.nativeElement;
    if (!video) return;
    const fps = 60;
    const targetSeconds = frame / fps;
    video.currentTime = Number.isFinite(video.duration)
      ? Math.min(video.duration, Math.max(0, targetSeconds))
      : Math.max(0, targetSeconds);
  };

  onGenerateCut(): void {
    if (!this.game) return;
    const selectedType = this.selectedCutType();
    const template = this.cutTemplates().find((item) => item.code === selectedType);
    if (!template) return;
    const name = this.newCutName().trim() || template.label;
    const payload = {
      name,
      slug: this.slugify(name),
      type_cut: template.code,
    };
    this.gameService.create_cut(this.game, payload).subscribe({
      next: (cut) => {
        this.cuts.set([...this.cuts(), cut]);
        this.newCutName.set('');
      },
      error: (e) => console.error('Erreur lors de la création du cut', e),
    });
  }

  onDeleteCut(cut: Cut, event?: MouseEvent): void {
    event?.stopPropagation();
    if (!this.game) return;
    const label = cut.name ?? cut.slug ?? 'ce cut';
    if (!confirm(`Supprimer ${label} ?`)) return;
    this.cutService.delete(cut).subscribe({
      next: () => this.cuts.set(this.cuts().filter((item) => item.pk !== cut.pk)),
      error: (e) => console.error('Erreur lors de la suppression du cut', e),
    });
  }

  onRenderCut(cut: Cut): void {
    this.cutService.render_cut(cut, {to_queue: false}).subscribe({
      next: () => {},
      error: (e) => console.error('Erreur lors du render du cut', e),
    });
  }

  private loadCuts(): void {
    if (!this.game) return;
    this.gameService.cuts(this.game).subscribe({
      next: (cuts) => this.cuts.set(cuts),
      error: (e) => console.error('Erreur lors du chargement des cuts', e),
    })

  }

  private loadCutTemplates(): void {
    this.cutService.cut_types().subscribe({
      next: (templates) => {
        this.cutTemplates.set(templates);
        if (!this.selectedCutType() && templates.length) {
          this.selectedCutType.set(templates[0].code);
        }
      },
      error: (e) => console.error('Erreur lors du chargement des templates de cuts', e),
    });
  }


  private queueFrameTracking(): void {
    setTimeout(() => this.startFrameTracking(), 0);
  }

  private startFrameTracking(): void {
    const video = this.proxyVideo?.nativeElement;
    if (!video) return;

    this.stopFrameTracking();
    const updateMetrics = () => {
      const fps = 60;
      const timeSeconds = video.currentTime;
      this.currentFrame.set(Math.max(0, Math.floor(timeSeconds * fps)));
      this.currentTimecode.set(this.formatTimecode(timeSeconds, fps));
    };

    const anyVideo = video as any;
    if (typeof anyVideo.requestVideoFrameCallback === 'function') {
      const onFrame = () => {
        updateMetrics();
        this.frameCallbackId = anyVideo.requestVideoFrameCallback(onFrame);
      };
      this.frameCallbackId = anyVideo.requestVideoFrameCallback(onFrame);
      return;
    }

    const onTimeUpdate = () => updateMetrics();
    this.fallbackListener = () => {
      video.removeEventListener('timeupdate', onTimeUpdate);
      video.removeEventListener('seeked', onTimeUpdate);
      video.removeEventListener('loadeddata', onTimeUpdate);
    };
    video.addEventListener('timeupdate', onTimeUpdate);
    video.addEventListener('seeked', onTimeUpdate);
    video.addEventListener('loadeddata', onTimeUpdate);
  }

  private stopFrameTracking(): void {
    const video = this.proxyVideo?.nativeElement as any;
    if (this.frameCallbackId !== null && video?.cancelVideoFrameCallback) {
      video.cancelVideoFrameCallback(this.frameCallbackId);
      this.frameCallbackId = null;
    }
    if (this.fallbackListener) {
      this.fallbackListener();
      this.fallbackListener = undefined;
    }
  }

  private formatTimecode(timeSeconds: number, fps: number): string {
    if (!Number.isFinite(timeSeconds) || timeSeconds < 0) return '00:00:00';
    const totalFrames = Math.floor(timeSeconds * fps);
    const minutes = Math.floor(totalFrames / (fps * 60));
    const seconds = Math.floor(totalFrames / fps) % 60;
    const frames = totalFrames % fps;
    return `${minutes.toString().padStart(2, '0')}:${seconds
      .toString()
      .padStart(2, '0')}:${frames.toString().padStart(2, '0')}`;
  }

  private slugify(value: string): string {
    return value
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }
}
