import { Component, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  FormBuilder,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { MetaFieldsComponent } from './meta-fields-components/meta-fields-components';
import { MiniatureBuilder } from './miniature-builder/miniature-builder';
import { MatButtonModule } from '@angular/material/button';
import { VideoMetadata, Yt_Video } from '../core/models/models';
import { VideoMetadataService } from '../core/services/video-metadata.service';
import { NavService } from '../core/services/nav.service';
import { YTVideoService } from '../core/services/misc-hateoas-models.service';

/**
 * Container view for editing a single VideoMetadata resource.
 *
 * Responsibilities:
 * - Load a VideoMetadata by HATEOAS self URL (from query param `url`).
 * - Display and update meta fields (title, description, publication date).
 * - Delegate miniature generation to the MiniatureBuilder child component.
 * - Invoke backend actions like publishing or resetting description.
 */
@Component({
  selector: 'app-game-miniature',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MetaFieldsComponent,
    MiniatureBuilder,
    MatButtonModule,
  ],
  templateUrl: './game-miniature.html',
  styleUrl: './game-miniature.css',
})
export class GameMiniatureComponent implements OnInit, OnDestroy {
  /**
   * HATEOAS parameter: self URL-backed VideoMetadata resource.
   */
  videoMetadata = signal<VideoMetadata | null>(null);
  ytVideos = signal<Yt_Video[]>([]);
  selectedYtVideoHref = signal<string | null>(null);

  /**
   * Reactive form holding editable fields of VideoMetadata.
   *
   * Notes:
   * - team1/team2 are stored as rel hrefs when present.
   * - timeCode is normalized (0..1) and emitted from the MiniatureBuilder.
   */
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private videoMetadataService = inject(VideoMetadataService);
  private ytVideoService = inject(YTVideoService);
  private formBuilder = inject(FormBuilder);
  videoMetadataForm: FormGroup = this.formBuilder.group({
    miniatureBuilder: this.formBuilder.group({
      team1: ['', [Validators.required]],
      team2: ['', [Validators.required]],
      timeCode: [
        0,
        [Validators.required, Validators.min(0), Validators.max(1)],
      ],
      viewport: this.formBuilder.group({
        miniature_x_offset: [
          0,
          [Validators.required, Validators.min(0), Validators.max(1)],
        ],
        miniature_y_offset: [
          0,
          [Validators.required, Validators.min(0), Validators.max(1)],
        ],
        miniature_zoom: [
          1,
          [Validators.required, Validators.min(1), Validators.max(5)],
        ],
      }),
    }),
    meta_fields: this.formBuilder.group({
      description: ['', [Validators.required]],
      video_name: ['', [Validators.required]],
      publication_date: ['', [Validators.required]],
    }),
  });
  private navService = inject(NavService);

  ngOnDestroy(): void {
    this.navService.clear();
  }

  /**
   * Reads the query param `url`, then loads the VideoMetadata from the API.
   */
  ngOnInit(): void {
    this.route.queryParamMap.subscribe((params) => {
      const url = params.get('url');
      if (!url) return;
      this.loadVideoMetadata(url);
    });
  }

  /**
   * Calls backend action to reset title and description then updates local state.
   */
  onResetDescription() {
    const vidMetadata = this.videoMetadata();
    if (!vidMetadata) return;
    this.videoMetadataService.reset_title_description(vidMetadata).subscribe({
      next: (vm) => this.videoMetadata.set(vm),
      error: (e) => console.log(this.stringifyError(e)),
    });
  }

  /**
   * Publishes description and miniature via backend actions.
   */
  onPublish() {
    const vidMetadata = this.videoMetadata();
    if (!vidMetadata) return;

    this.videoMetadataService.upload_description(vidMetadata).subscribe({
      next: () => console.log('description upload'),
      error: (e) => console.log(this.stringifyError(e)),
    });
    this.videoMetadataService.upload_miniature(vidMetadata).subscribe({
      next: () => console.log('miniature upload'),
      error: (e) => console.log(this.stringifyError(e)),
    });
  }

  /**
   * Triggers miniature generation by invoking the backend with the current form payload.
   * Updates local VideoMetadata on success.
   */
  onGenerateClick() {
    const miniatureBuilder =
      this.videoMetadataForm.get('miniatureBuilder')?.value;
    const viewport = this.videoMetadataForm.get([
      'miniatureBuilder',
      'viewport',
    ])?.value;
    if (!miniatureBuilder || !viewport) return;

    const payload = {
      team1: miniatureBuilder.team1,
      team2: miniatureBuilder.team2,
      miniature_x_offset: Number(viewport.miniature_x_offset ?? 0),
      miniature_y_offset: Number(viewport.miniature_y_offset ?? 0),
      miniature_zoom: Number(viewport.miniature_zoom ?? 1),
      time_code: Number(miniatureBuilder.timeCode ?? 0),
    };

    const vm = this.videoMetadata();
    if (!vm) {
      console.warn('VideoMetadata indisponible, génération annulée.');
      return;
    }

    this.videoMetadataService.generate_miniature(vm, payload).subscribe({
      next: (videoMetadata) => {
        this.videoMetadata.set(videoMetadata);
        this.patchForm(videoMetadata);
      },
      error: (e) => {
        console.error('Erreur lors de generate_miniature', e);
      },
    });
  }

  /**
   * Persists editable fields to the backend using PATCH.
   */
  onSave() {
    const vidMetadata = this.videoMetadata();
    if (!vidMetadata) return;

    const payload = this.buildVmPayload();
    this.videoMetadataService.update(vidMetadata, payload).subscribe({
      next: () => {},
      error: (e) => console.log(this.stringifyError(e)),
    });
  }

  onYtVideoSelected(ytVideoHref: string | null): void {
    const vidMetadata = this.videoMetadata();
    if (!vidMetadata) return;

    const previousYtVideoHref = this.selectedYtVideoHref();
    this.selectedYtVideoHref.set(ytVideoHref);
    const ytVideo = ytVideoHref
      ? (this.ytVideos().find(
          (video) => this.ytVideoHref(video) === ytVideoHref,
        ) ?? ytVideoHref)
      : null;

    this.videoMetadataService.set_yt_video(vidMetadata, ytVideo).subscribe({
      next: (response) => {
        const linkedVideo = response.yt_video;
        this.selectedYtVideoHref.set(
          linkedVideo ? this.ytVideoHref(linkedVideo) : null,
        );
        if (linkedVideo) {
          this.ytVideos.set(
            this.withLinkedYtVideo(this.ytVideos(), linkedVideo),
          );
        }
      },
      error: (e) => {
        this.selectedYtVideoHref.set(previousYtVideoHref);
        console.log(this.stringifyError(e));
      },
    });
  }

  /**
   * Navigates back to the tournament games view using the tournament rel.
   */
  onBackTournament(): void {
    const vidMetadata = this.videoMetadata();
    if (!vidMetadata?._links?.tournament?.href) return;
    this.router.navigate(['/tournament/games'], {
      queryParams: { url: vidMetadata._links.tournament.href },
    });
  }

  /**
   * Fetches VideoMetadata by URL and initializes the form fields.
   * Translations:
   * - “Initialiser TOUS les champs ...” -> “Initialize ALL form fields...”
   * - “S’assurer que les noms ...” -> “Ensure displayed names can be resolved ...”
   */
  private loadVideoMetadata(url: string) {
    this.videoMetadataService.get(url).subscribe({
      next: (vm: VideoMetadata) => {
        // Initialize ALL form fields with values from VideoMetadata
        this.videoMetadata.set(vm);
        this.patchForm(vm);
        this.updateNav(vm);
        this.loadYtVideos(vm);
      },
      error: (e) => console.log(this.stringifyError(e)),
    });
  }

  private loadYtVideos(vm: VideoMetadata): void {
    this.ytVideoService.latest(20).subscribe({
      next: (videos) => {
        this.ytVideos.set(this.withSelectedYtVideo(videos));
      },
      error: (e) => console.log(this.stringifyError(e)),
    });

    this.videoMetadataService.linked_yt_videos(vm, true).subscribe({
      next: (videos) => {
        const linkedVideo = videos[0] ?? null;
        this.selectedYtVideoHref.set(
          linkedVideo ? this.ytVideoHref(linkedVideo) : null,
        );
        if (linkedVideo) {
          this.ytVideos.set(
            this.withLinkedYtVideo(this.ytVideos(), linkedVideo),
          );
        }
      },
      error: (e) => console.log(this.stringifyError(e)),
    });
  }

  private ytVideoHref(video: Yt_Video): string {
    return video._links?.self?.href ?? String(video.pk);
  }

  private withSelectedYtVideo(videos: Yt_Video[]): Yt_Video[] {
    const selectedHref = this.selectedYtVideoHref();
    if (!selectedHref) return videos;
    const selectedVideo = this.ytVideos().find(
      (video) => this.ytVideoHref(video) === selectedHref,
    );
    return selectedVideo
      ? this.withLinkedYtVideo(videos, selectedVideo)
      : videos;
  }

  private withLinkedYtVideo(
    videos: Yt_Video[],
    linkedVideo: Yt_Video,
  ): Yt_Video[] {
    const linkedHref = this.ytVideoHref(linkedVideo);
    const withoutLinked = videos.filter(
      (video) => this.ytVideoHref(video) !== linkedHref,
    );
    return [linkedVideo, ...withoutLinked].slice(0, 20);
  }

  private patchForm(vm: VideoMetadata) {
    this.videoMetadataForm.patchValue({
      miniatureBuilder: {
        team1: vm._links?.team1?.href ?? '',
        team2: vm._links?.team2?.href ?? '',
        timeCode: vm.time_code,
        viewport: {
          miniature_x_offset: vm.miniature_x_offset ?? 0,
          miniature_y_offset: vm.miniature_y_offset ?? 0,
          miniature_zoom: vm.miniature_zoom ?? 1,
        },
      },
      meta_fields: {
        description: vm.description ?? '',
        video_name: vm.video_name ?? '',
        publication_date: vm?.publication_date
          ? this.toDatetimeLocal(vm.publication_date)
          : '',
      },
    });
  }

  private updateNav(vm: VideoMetadata) {
    const tournamentUrl = vm._links?.tournament?.href;
    if (!tournamentUrl) {
      this.navService.clear();
      return;
    }
    const embedded = vm._embedded;
    const tournament = embedded?.['tournament'] as
      | { name?: string }
      | undefined;
    const tournamentName = tournament?.name;
    const label = tournamentName ?? 'Tournoi';
    this.navService.setLinks([
      {
        label,
        routerLink: ['/tournament/games'],
        queryParams: { url: tournamentUrl },
      },
    ]);
  }

  /**
   * Converts an ISO (UTC/Z or offset) string to a value compatible with
   * <input type="datetime-local">, e.g., "2025-08-28T14:30".
   *
   * @param iso - ISO 8601 date-time string.
   * @returns Local datetime string without seconds.
   */
  private toDatetimeLocal(iso: string): string {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    const pad = (n: number) => n.toString().padStart(2, '0');
    const yyyy = d.getFullYear();
    const mm = pad(d.getMonth() + 1);
    const dd = pad(d.getDate());
    const hh = pad(d.getHours());
    const mi = pad(d.getMinutes());
    return `${yyyy}-${mm}-${dd}T${hh}:${mi}`;
  }

  /**
   * Builds a partial VideoMetadata payload for updates.
   */
  private buildVmPayload(): Partial<VideoMetadata> {
    const metadataForm = this.videoMetadataForm.value;
    console.log('payload_value', metadataForm);
    return {
      //team1: v.team1 ?? undefined,
      //team2: v.team2 ?? undefined,
      //tc: v.timeCode ?? undefined,
      description: metadataForm.meta_fields.description ?? undefined,
      video_name: metadataForm.meta_fields.video_name ?? undefined,
      publication_date: metadataForm.meta_fields.publication_date ?? undefined,
    } as Partial<VideoMetadata>;
  }

  /**
   * Converts various error shapes to a human-readable string.
   */
  private stringifyError(e: unknown): string {
    if (!e) return 'Erreur inconnue';
    if (typeof e === 'string') return e;
    if (e instanceof Error) return e.message;
    try {
      return JSON.stringify(e);
    } catch {
      return String(e);
    }
  }
}
