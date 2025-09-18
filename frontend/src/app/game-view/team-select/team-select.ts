import {Component, forwardRef, Input} from '@angular/core';
import {CommonModule} from '@angular/common';
import {TeamLogo} from '../../features/team-logos/team-logo.model';
import {ControlValueAccessor, NG_VALUE_ACCESSOR, ReactiveFormsModule} from '@angular/forms';

import {MatInputModule} from '@angular/material/input';
import {MatSelectModule} from '@angular/material/select';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatIconModule} from '@angular/material/icon';

@Component({
  selector: 'app-team-select',
  standalone: true,
  templateUrl: './team-select.html',
  styleUrl: './team-select.css',
  imports: [
    CommonModule,
    MatFormFieldModule,
    MatSelectModule,
    MatInputModule,
    CommonModule,
    MatFormFieldModule,
    MatInputModule,
    MatIconModule,
    ReactiveFormsModule],
  providers: [
    {
      provide: NG_VALUE_ACCESSOR,
      useExisting: forwardRef(() => TeamSelectComponent),
      multi: true,
    },
  ],

})
export class TeamSelectComponent implements ControlValueAccessor {
  @Input() teams: TeamLogo[] | null = null;
  @Input() label = 'Team';
  value: string | null = null;
  disabled = false;


  writeValue(value: string | null): void {
    this.value = value ?? null;
  }

  registerOnChange(fn: (value: string | null) => void): void {
    this.onChange = fn;
  }

  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }

  setDisabledState(isDisabled: boolean): void {
    this.disabled = isDisabled;
  }

  onSelect(value: string) {
    this.value = value ?? null;
    this.onChange(this.value);
    this.onTouched();
  }

  private onChange: (value: string | null) => void = () => {
  };

  private onTouched: () => void = () => {
  };


}
