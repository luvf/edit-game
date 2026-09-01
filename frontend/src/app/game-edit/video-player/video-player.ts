import {
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnInit,
  Output,
  signal,
  SimpleChanges,
  ViewChild,
} from '@angular/core';
import {Video, VideoFile, VideoFiles, VideoQuality} from '../../core/models/models';
import {MatButton} from '@angular/material/button';
import {MatFormField, MatLabel} from '@angular/material/input';
import {MatOption, MatSelect} from '@angular/material/select';
import {HttpClient} from '@angular/common/http';

/**
 * Utilise seulement quand l'API ne renvoie pas de fps : fichier jamais sonde,
 * absent du disque, ou illisible. Les rushs sont en 60000/1001.
 */
export const FALLBACK_FPS = 60000 / 1001;
@Component({
  selector: 'app-video-player',
  imports: [MatButton, MatFormField, MatLabel, MatSelect, MatOption],
  templateUrl: './video-player.html',
  styleUrl: './video-player.css',
})
export class VideoPlayer implements OnInit {
  @ViewChild('videoElement') videoElement?: ElementRef<HTMLVideoElement>;

  @Input() sourceVideo!: Video;

  currentFrame: number = 0;
  @Output() currentFrameChange = new EventEmitter<number>();
  /** Frame rate reelle de la source affichee, une fois la qualite choisie. */
  @Output() fpsChange = new EventEmitter<number>();
  availableQualities = signal<VideoQuality[]>([]);
  selectedQuality = signal<VideoQuality | null>(null);
  currentVideoUrl = signal<string | null>(null);
  currentTimecode: string = '00:00:00'; //signal('00:00:00');
  private fps = FALLBACK_FPS;
  private animationFrameId?: number;

  private pendingSeekTime: number | null = null;
  private pendingPlayAfterLoad = false;
  private isApplyingQuality = false;

  constructor(private http: HttpClient) {}

  ngOnInit() {}

  ngOnChanges(changes: SimpleChanges) {
    if (changes['sourceVideo']) {
      this.initQualities();
    }
  }

  onTimeUpdate() {
    const video = this.videoElement?.nativeElement;
    if (!video) return;

    const timeSeconds = video.currentTime;
    this.currentFrame = this.timeToFrame(timeSeconds);
    this.currentTimecode = this.formatTimecode(timeSeconds, this.fps);
    this.currentFrameChange.emit(this.currentFrame);
  }

  onLoadedMetadata() {
    const video = this.videoElement?.nativeElement;
    if (!video) return;

    // La nouvelle source est prête : le seek redevient possible.
    this.isApplyingQuality = false;

    if (this.pendingSeekTime !== null) {
      const target = Math.max(
        0,
        Math.min(
          Number.isFinite(video.duration)
            ? video.duration
            : this.pendingSeekTime,
          this.pendingSeekTime,
        ),
      );
      video.currentTime = target;
      this.pendingSeekTime = null;
    }
  }

  onCanPlay() {
    const video = this.videoElement?.nativeElement;
    if (!video) return;

    // Filet de sécurité si loadedmetadata n'est pas passé.
    this.isApplyingQuality = false;

    if (this.pendingPlayAfterLoad) {
      this.pendingPlayAfterLoad = false;
      void video.play().catch(() => {});
    }
  }

  setQuality(q: VideoQuality) {
    if (!this.sourceVideo) return;
    const nextUrl = this.sourceVideo.files[q] ?? null;
    if (!nextUrl) return;
    if (this.selectedQuality() === q) return;

    const video = this.videoElement?.nativeElement;
    const wasPlaying = !!video && !video.paused && !video.ended;
    const currentTime = video?.currentTime ?? 0;

    this.applySource(q, nextUrl);

    this.isApplyingQuality = true;
    this.pendingSeekTime = currentTime;
    this.pendingPlayAfterLoad = wasPlaying;
  }

  /** Positionne la lecture sur une frame donnée (appelé par le parent). */
  goToFrame(frame: number): void {
    const video = this.videoElement?.nativeElement;
    if (!video) return;

    const targetSeconds = Math.max(0, frame / this.fps);

    // Source en cours de rechargement : on applique le seek sur loadedmetadata.
    if (this.isApplyingQuality) {
      this.pendingSeekTime = targetSeconds;
      return;
    }

    video.currentTime = Number.isFinite(video.duration)
      ? Math.min(video.duration, targetSeconds)
      : targetSeconds;
  }

  seekBy(steps: number): void {
    const video = this.videoElement?.nativeElement;
    if (!video) return;
    const offsetSeconds = steps * 1.5;
    const targetTime = Math.max(0, video.currentTime + offsetSeconds);
    video.currentTime = Number.isFinite(video.duration)
      ? Math.min(video.duration, targetTime)
      : targetTime;
  }

  // Utilitaires
  frameToTime(frame: number): number {
    return frame / this.fps;
  }

  timeToFrame(time: number): number {
    return Math.round(time * this.fps);
  }

  ngOnDestroy() {
    if (this.animationFrameId) cancelAnimationFrame(this.animationFrameId);
  }

  private initQualities(): void {
    if (!this.sourceVideo?.files) return;
    const sourceVideoFiles: VideoFiles = this.sourceVideo.files;
    const available = Object.keys(sourceVideoFiles) as VideoQuality[];
    this.availableQualities.set(available);
    // L'archive est la source la plus lourde : on ne la choisit que si le
    // proxy n'expose aucune de ses qualites. Une qualite inconnue de cet
    // ordre (les variantes av1) reste jouable en dernier recours.
    const order: VideoQuality[] = ['low', 'medium', 'high', 'archive'];
    const quality =
      order.find((item) => available.includes(item)) ?? available[0];
    const file = quality ? sourceVideoFiles[quality] : undefined;
    if (!quality || !file) return;

    const video = this.videoElement?.nativeElement;
    const currentTime = video?.currentTime ?? 0;
    const wasPlaying = !!video && !video.paused && !video.ended;
    const previousUrl = this.currentVideoUrl();

    this.applySource(quality, file);

    // Le fichier ne change pas (nouvelle liste de qualites sur la meme
    // source) : rien a recharger, donc pas de seek en attente a armer.
    if (this.currentVideoUrl() === previousUrl) return;

    if (currentTime > 0) {
      this.isApplyingQuality = true;
      this.pendingSeekTime = currentTime;
      this.pendingPlayAfterLoad = wasPlaying;
    }
  }

  /** Selectionne un fichier et adopte sa frame rate reelle. */
  private applySource(quality: VideoQuality, file: VideoFile): void {
    this.selectedQuality.set(quality);
    this.currentVideoUrl.set(file.url);
    this.fps = file.fps ?? FALLBACK_FPS;
    this.fpsChange.emit(this.fps);
  }

  private formatTimecode(timeSeconds: number, fps: number): string {
    if (!Number.isFinite(timeSeconds) || timeSeconds < 0) return '00:00:00';
    // Le compteur de frames s'exprime en fps nominal (60 pour du 59.94),
    // sinon le modulo rend une fraction.
    const nominalFps = Math.max(1, Math.round(fps));
    const totalFrames = Math.floor(timeSeconds * fps);
    const minutes = Math.floor(totalFrames / nominalFps / 60);
    const seconds = Math.floor(totalFrames / nominalFps) % 60;
    const frames = totalFrames % nominalFps;
    return `${minutes.toString().padStart(2, '0')}:${seconds
      .toString()
      .padStart(2, '0')}:${frames.toString().padStart(2, '0')}`;
  }
}
