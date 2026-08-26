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
import {Video, VideoFiles, VideoQuality} from '../../core/models/models';
import {MatButton} from '@angular/material/button';
import {MatFormField, MatLabel} from '@angular/material/input';
import {MatOption, MatSelect} from '@angular/material/select';
import {HttpClient} from '@angular/common/http';

type Quality = 'high' | 'medium' | 'low';

export const VIDEO_FPS = 60;
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
  availableQualities = signal<VideoQuality[]>([]);
  selectedQuality = signal<VideoQuality | null>(null);
  currentVideoUrl = signal<string | null>(null);
  currentTimecode: string = '00:00:00'; //signal('00:00:00');
  private readonly FPS = VIDEO_FPS;
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
    this.currentTimecode = this.formatTimecode(timeSeconds, this.FPS);
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

  setQuality(q: Quality) {
    if (!this.sourceVideo) return;
    const nextUrl = this.sourceVideo.files[q] ?? null;
    if (!nextUrl) return;
    if (this.selectedQuality() === q) return;

    const video = this.videoElement?.nativeElement;
    const wasPlaying = !!video && !video.paused && !video.ended;
    const currentTime = video?.currentTime ?? 0;

    this.selectedQuality.set(q);
    this.currentVideoUrl.set(nextUrl.url);

    this.isApplyingQuality = true;
    this.pendingSeekTime = currentTime;
    this.pendingPlayAfterLoad = wasPlaying;
  }

  /** Positionne la lecture sur une frame donnée (appelé par le parent). */
  goToFrame(frame: number): void {
    const video = this.videoElement?.nativeElement;
    if (!video) return;

    const targetSeconds = Math.max(0, frame / this.FPS);

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
    return frame / this.FPS;
  }

  timeToFrame(time: number): number {
    return Math.round(time * this.FPS);
  }

  ngOnDestroy() {
    if (this.animationFrameId) cancelAnimationFrame(this.animationFrameId);
  }

  private initQualities(): void {
    if (!this.sourceVideo?.files) return;
    const sourceVideoFiles: VideoFiles = this.sourceVideo.files;
    this.availableQualities.set(
      Object.keys(sourceVideoFiles) as VideoQuality[],
    );
    const order: VideoQuality[] = ['low', 'medium', 'high'];
    const ordered_included = order.filter((quality) =>
      this.availableQualities().includes(quality),
    );
    if (!ordered_included.length) return;
    this.selectedQuality.set(ordered_included[0]);
    this.currentVideoUrl.set(sourceVideoFiles[ordered_included[0]].url);
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
}
