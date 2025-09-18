import {Component, inject, Input, OnInit, signal} from '@angular/core';
import {CommonModule} from '@angular/common';
import {MatSlider, MatSliderThumb} from '@angular/material/slider';
import {MatButton} from '@angular/material/button';
import {VideoMetadata} from '../../features/video-metadatas/video-metadata.model';
import {TeamLogoService} from '../../features/team-logos/team-logo';
import {TeamLogo} from '../../features/team-logos/team-logo.model';

import {FormGroup, FormGroupDirective, ReactiveFormsModule} from '@angular/forms';
import {TeamSelectComponent} from '../team-select/team-select';
import {ImagesPreviewComponent} from './image-preview/image-preview';


@Component({
  selector: 'app-miniature-builder',
  standalone: true,
  imports: [CommonModule, MatSliderThumb, MatSlider, MatButton, TeamSelectComponent, ImagesPreviewComponent, ReactiveFormsModule],
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

  private teamLogoService = inject(TeamLogoService);

  constructor() {

  }

  ngOnInit(): void {
    this.loadTeams();
    this.miniatureBuilderForm = this.gameFormGroup.control.get(this.formGroupName) as FormGroup;
  }

  /**
   * Swaps team1 and team2 selections in the form.
   */
  onSwapTeams() {
    this.miniatureBuilderForm.patchValue({
      team1: this.miniatureBuilderForm.get('team2',)?.value,
      team2: this.miniatureBuilderForm.get('team1')?.value
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
