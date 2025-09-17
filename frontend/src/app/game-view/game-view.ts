import {Component, inject, OnInit, signal} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormBuilder, ReactiveFormsModule, Validators} from '@angular/forms';
import {ActivatedRoute, Router} from '@angular/router';
import {VideoMetadataService} from "../features/video-metadatas/video-metadata";
import {VideoMetadata} from '../features/video-metadatas/video-metadata.model';
import {MetaFieldsComponent} from './meta-fields-components/meta-fields-components';
import {MiniatureBuilder} from './miniature-builder/miniature-builder';
import {MatButtonModule} from '@angular/material/button';


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
  selector: 'app-game-view',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MetaFieldsComponent,
    MiniatureBuilder, MatButtonModule
  ],
  templateUrl: './game-view.html',
  styleUrl: './game-view.css',
})
export class GameViewComponent implements OnInit {
  /**
   * HATEOAS parameter: self URL-backed VideoMetadata resource.
   */
  videoMetadata = signal<VideoMetadata | null>(null);

  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private videoMetadataService = inject(VideoMetadataService);

  private formBuilder = inject(FormBuilder);
  /**
   * Reactive form holding editable fields of VideoMetadata.
   *
   * Notes:
   * - team1/team2 are stored as rel hrefs when present.
   * - timeCode is normalized (0..1) and emitted from the MiniatureBuilder.
   */
  videoMetadataForm = this.formBuilder.group({
    team1: ['', [Validators.required]],
    team2: ['', [Validators.required]],
    timeCode: [0],
    description: [''],
    video_name: [''],
    publication_date: [''],
  });


  onVidNameChange(value: string) {
    this.videoMetadataForm.value.video_name = value;
  }

  onDescriptionChange(value: string) {
    this.videoMetadataForm.value.description = value;
  }

  onPublicationDateChange(value: string) {
    this.videoMetadataForm.value.publication_date = value;
  }

  /**
   * Persists editable fields to the backend using PATCH.
   */
  onSave() {
    const vidMetadata = this.videoMetadata();
    if (!vidMetadata) return;

    const payload = this.buildVmPayload();
    this.videoMetadataService.update(vidMetadata, payload).subscribe({
      next: () => {
      },
      error: (e) => console.log(this.stringifyError(e)),
    });
  }

  /**
   * Calls backend action to reset title and description then updates local state.
   */
  onResetDescription() {
    const vidMetadata = this.videoMetadata();
    if (!vidMetadata) return;
    this.videoMetadataService.reset_title_descriptiont(vidMetadata).subscribe({
      next: (vm) => this.videoMetadata.set(vm),
      error: (e) => console.log(this.stringifyError(e)),
    })
  }

  /**
   * Publishes description and miniature via backend actions.
   */
  onPublish() {
    const vidMetadata = this.videoMetadata();
    if (!vidMetadata) return;

    this.videoMetadataService.upload_descripton(vidMetadata).subscribe({
      next: () => console.log('description upload'),
      error: (e) => console.log(this.stringifyError(e)),
    });
    this.videoMetadataService.upload_miniature(vidMetadata).subscribe({
      next: () => console.log('miniature upload'),
      error: (e) => console.log(this.stringifyError(e)),
    });
  }

  /**
   * Navigates back to the tournament games view using the tournament rel.
   */
  onBackTournament(): void {
    const vidMetadata = this.videoMetadata();
    if (!vidMetadata?._links?.tournament?.href) return;
    this.router.navigate(['/tournament/games'], {
      queryParams: {url: vidMetadata._links.tournament.href},
    });
  }

  /**
   * Receives normalized time code (0..1) from the MiniatureBuilder.
   */
  onTimecodesChange(time_code: number) {
    this.videoMetadataForm.value.timeCode = time_code;
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
   * Fetches VideoMetadata by URL and initializes the form fields.
   * Translations:
   * - “Initialiser TOUS les champs ...” -> “Initialize ALL form fields...”
   * - “S’assurer que les noms ...” -> “Ensure displayed names can be resolved ...”
   */
  private loadVideoMetadata(url: string) {
    this.videoMetadataService.get(url).subscribe({
      next: (vm: VideoMetadata) => {
        // Initialize ALL form fields with values from VideoMetadata
        this.videoMetadata.set(vm)
        this.videoMetadataForm.patchValue({
          team1: vm._links?.team1?.href ?? '',
          team2: vm._links?.team2?.href ?? '',
          description: vm.description ?? '',
          video_name: vm.video_name ?? '',
          publication_date: vm?.publication_date ? this.toDatetimeLocal(vm.publication_date) : '',
        });
      },
      error: (e) => console.log(this.stringifyError(e)),
    });
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
    const v = this.videoMetadataForm.value;
    return {
      //team1: v.team1 ?? undefined,
      //team2: v.team2 ?? undefined,
      //tc: v.timeCode ?? undefined,
      description: v.description ?? undefined,
      video_name: v.video_name ?? undefined,
      publication_date: v.publication_date ?? undefined,
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
