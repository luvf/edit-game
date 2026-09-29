import { Component, forwardRef, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  ControlValueAccessor,
  FormControl,
  NG_VALUE_ACCESSOR,
  ReactiveFormsModule,
} from '@angular/forms';
import { startWith } from 'rxjs/operators';

import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { Team } from '../../core/models/models';
import { MatAutocompleteModule } from '@angular/material/autocomplete';

@Component({
  selector: 'app-team-select',
  standalone: true,
  templateUrl: './team-select.html',
  styleUrl: './team-select.css',
  imports: [
    CommonModule,
    MatFormFieldModule,
    MatInputModule,
    ReactiveFormsModule,
    MatAutocompleteModule,
  ],
  providers: [
    {
      provide: NG_VALUE_ACCESSOR,
      useExisting: forwardRef(() => TeamSelectComponent),
      multi: true,
    },
  ],
})
export class TeamSelectComponent implements ControlValueAccessor {
  private _teams: Team[] = [];
  @Input() set teams(value: Team[] | null) {
    this._teams = value ?? [];
    this.filteredTeams = this._teams;
    this.syncInputFromValue();
  }
  get teams(): Team[] {
    return this._teams;
  }
  @Input() label = 'Team';
  value: string | null = null;
  disabled = false;
  searchControl = new FormControl('', { nonNullable: true });
  filteredTeams: Team[] = [];

  constructor() {
    this.searchControl.valueChanges.pipe(startWith('')).subscribe((query) => {
      const normalized = (query ?? '').toLowerCase().trim();
      this.filteredTeams = this.teams.filter((team) =>
        (team.name ?? '').toLowerCase().includes(normalized),
      );
      this.clearValueIfQueryNoLongerMatchesSelection(query ?? '');
    });
  }

  writeValue(value: string | null): void {
    this.value = value ?? null;
    this.syncInputFromValue();
  }

  registerOnChange(fn: (value: string | null) => void): void {
    this.onChange = fn;
  }

  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }

  setDisabledState(isDisabled: boolean): void {
    this.disabled = isDisabled;
    if (isDisabled) {
      this.searchControl.disable({ emitEvent: false });
      return;
    }
    this.searchControl.enable({ emitEvent: false });
  }

  onSelect(value: string) {
    this.value = value ?? null;
    this.syncInputFromValue();
    this.onChange(this.value);
    this.onTouched();
  }

  onBlur(): void {
    this.syncInputFromValue();
    this.onTouched();
  }

  private syncInputFromValue(): void {
    const selectedTeam = this.teams.find(
      (team) => (team._links?.self?.href ?? '') === this.value,
    );
    this.searchControl.setValue(selectedTeam?.name ?? '', { emitEvent: false });
  }

  private clearValueIfQueryNoLongerMatchesSelection(query: string): void {
    if (!this.value) return;
    const selectedTeam = this.teams.find(
      (team) => (team._links?.self?.href ?? '') === this.value,
    );
    if (!selectedTeam) {
      this.value = null;
      this.onChange(null);
      return;
    }
    if ((selectedTeam.name ?? '') !== query) {
      this.value = null;
      this.onChange(null);
    }
  }

  private onChange: (value: string | null) => void = () => {};

  private onTouched: () => void = () => {};
}
