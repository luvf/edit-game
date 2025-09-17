import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { TeamLogo } from '../../features/team-logos/team-logo.model';

import {MatInputModule} from '@angular/material/input';
import {MatSelectModule} from '@angular/material/select';
import {MatFormFieldModule} from '@angular/material/form-field';

@Component({
  selector: 'app-team-select',
  standalone: true,
  imports: [CommonModule,MatFormFieldModule, MatSelectModule, MatInputModule],
  templateUrl: './team-select.html',
  styleUrl: './team-select.css',
})
export class TeamSelectComponent {
  @Input() label = 'Team';
  @Input() teams: TeamLogo[] | null = null;
  @Input() value: string | null = null; // href HATEOAS
  @Output() valueChange = new EventEmitter<string>();

  onChange(href: string) {
    this.valueChange.emit(href);
  }

}
