import { Component, inject, Input, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatSlider, MatSliderThumb } from '@angular/material/slider';
import { MatButton } from '@angular/material/button';

import {
  FormGroup,
  FormGroupDirective,
  ReactiveFormsModule,
} from '@angular/forms';
import { TeamSelectComponent } from '../team-select/team-select';
import { ImagesPreviewComponent } from './image-preview/image-preview';
import { TeamCreateComponent } from '../../game-edit/team-create/team-create';
import { Team, VideoMetadata } from '../../core/models/models';
import { TeamService } from '../../core/services/misc-hateoas-models.service';

@Component({
  selector: 'app-miniature-builder',
  standalone: true,
  imports: [
    CommonModule,
    MatSliderThumb,
    MatSlider,
    MatButton,
    TeamSelectComponent,
    TeamCreateComponent,
    ImagesPreviewComponent,
    ReactiveFormsModule,
  ],
  templateUrl: './miniature-builder.html',
  styleUrl: './miniature-builder.css',
})
export class MiniatureBuilder implements OnInit {
  @Input() videoMetadata = signal<VideoMetadata | null>(null);
  @Input() formGroupName!: string;

  teams_logos = signal<Team[]>([]);
  teamByUrl = signal<Record<string, Team>>({});
  miniatureBuilderForm!: FormGroup;
  private gameFormGroup: FormGroupDirective = inject(FormGroupDirective);

  private teamLogoService = inject(TeamService);

  constructor() {}

  ngOnInit(): void {
    this.loadTeams();
    this.miniatureBuilderForm = this.gameFormGroup.control.get(
      this.formGroupName,
    ) as FormGroup;
  }

  /**
   * Swaps team1 and team2 selections in the form.
   */
  onSwapTeams() {
    this.miniatureBuilderForm.patchValue({
      team1: this.miniatureBuilderForm.get('team2')?.value,
      team2: this.miniatureBuilderForm.get('team1')?.value,
    });
  }

  /**
   * Adds a team just created from the "+" bubble and selects it in its slot.
   */
  onTeamCreated(slot: 'team1' | 'team2', team: Team) {
    this.teams_logos.set(
      [...this.teams_logos(), team].sort((a, b) =>
        (a.name ?? '').localeCompare(b.name ?? ''),
      ),
    );
    const href = team._links?.self?.href;
    if (!href) return;
    this.teamByUrl.set({ ...this.teamByUrl(), [href]: team });
    this.miniatureBuilderForm.get(slot)?.setValue(href);
  }

  /**
   * Loads all team logos and builds an index keyed by their self href.
   * Initializes teams_logos and teamByUrl signals.
   */
  private loadTeams(): void {
    this.teamLogoService.list().subscribe({
      next: (teams) => {
        this.teams_logos.set(teams);
        const map: Record<string, Team> = {};
        for (const t of teams) {
          const href = (t as Team)?._links?.self?.href;
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
