import {Component, inject, Input, OnInit, signal} from '@angular/core';
import {CommonModule} from '@angular/common';
import {MatSlider, MatSliderThumb} from '@angular/material/slider';
import {MatButton} from '@angular/material/button';
import {VideoMetadata} from '../../features/video-metadatas/video-metadata.model';
import {TeamLogoService} from '../../features/team-logos/team-logo';
import {TeamLogo} from '../../features/team-logos/team-logo.model';

import {FormGroup, FormGroupDirective} from '@angular/forms';
import {TeamSelectComponent} from '../team-select/team-select';
import {ImagesPreviewComponent} from './image-preview/image-preview';
import {VideoMetadataService} from '../../features/video-metadatas/video-metadata';

type ControlKey = 'xOffset' | 'yOffset' | 'zoom' | 'timeCode';

@Component({
  selector: 'app-miniature-builder',
  standalone: true,
  imports: [CommonModule, MatSliderThumb, MatSlider, MatButton, TeamSelectComponent, ImagesPreviewComponent],
  templateUrl: './miniature-builder.html',
  styleUrl: './miniature-builder.css',
})
export class MiniatureBuilder implements OnInit {
  @Input() videoMetadata = signal<VideoMetadata | null>(null);
  @Input() formGroupName!: string;

  teams_logos = signal<TeamLogo[]>([]);
  teamByUrl = signal<Record<string, TeamLogo>>({});
  miniatureBuilderForm!: FormGroup;
  private gameFormGroup: FormGroupDirective = inject(FormGroupDirective)

  private videoMetadataService = inject(VideoMetadataService);
  private teamLogoService = inject(TeamLogoService);

  constructor() {

  }

  ngOnInit(): void {
    this.loadTeams();
    this.miniatureBuilderForm = this.gameFormGroup.control.get(this.formGroupName) as FormGroup
  }

  /**
   * Updates a control value from a number or DOM event and emits the corresponding output event.
   *
   * @param key - Name of the control to update.
   * @param valueOrEvent - Either a number value or an input event carrying the value.
   */
  setControl(key: ControlKey, valueOrEvent: number | Event) {
    const value = typeof valueOrEvent === 'number'
      ? valueOrEvent
      : Number((valueOrEvent.target as HTMLInputElement).value);

    // Update the form
    this.miniatureBuilderForm.patchValue({[key]: value} as any);

  }

  /**
   * Handles a team selection change for the given slot (1 or 2).
   *
   * @param team - Selected team logo href.
   * @param index - Team slot index (1 | 2).
   */
  onTeamChange(team: string, index: 1 | 2) {
    if (index == 1) {
      this.miniatureBuilderForm.value.team1 = team;
    } else {
      this.miniatureBuilderForm.value.team2 = team;
    }
  }

  /**
   * Swaps team1 and team2 selections in the form.
   */
  onSwapTeams() {
    const t1 = this.miniatureBuilderForm.value.team1;
    this.miniatureBuilderForm.value.team1 = this.miniatureBuilderForm.value.team2;
    this.miniatureBuilderForm.value.team2 = t1;
  }

  /**
   * Triggers miniature generation by invoking the backend with the current form payload.
   * Updates local VideoMetadata on success.
   */
  onGenerateClick() {
    const vm = this.videoMetadata();
    if (!vm) {
      console.warn('VideoMetadata indisponible, génération annulée.');
      return;
    }

    const vals = this.miniatureBuilderForm.value;
    const payload = {
      team1: vals.team1,
      team2: vals.team2,
      xoffset: Number(vals.xOffset ?? 0),
      yoffset: Number(vals.yOffset ?? 0),
      zoom: Number(vals.zoom ?? 1),
      timeCode: Number(vals.timeCode ?? 0),
    };

    this.videoMetadataService.generate_miniature(vm, payload)
      .subscribe({
        next: (videoMetadata) => {
          this.videoMetadata.set(videoMetadata);
        },
        error: (e) => {
          console.error('Erreur lors de generate_miniature', e);
        },
      });
  }

  /**
   * Loads all team logos and builds an index keyed by their self href.
   * Initializes teams_logos and teamByUrl signals.
   */
  private loadTeams(): void {
    this.teamLogoService.list().subscribe({
      next: (teams) => {
        this.teams_logos.set(teams);
        const map: Record<string, TeamLogo> = {};
        for (const t of teams) {
          const href = (t as TeamLogo)?._links?.self?.href;
          if (href) map[href] = t;
        }
        this.teamByUrl.set(map);

      },
      error: (e) => {
        console.error('Erreur chargement équipes', e);
        this.teams_logos.set([]);
        this.teamByUrl.set({});
      },
      complete: () => null,
    });
  }

}
