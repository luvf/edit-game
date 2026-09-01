import { Component, EventEmitter, inject, OnInit, Output } from '@angular/core';
import { TournamentService } from '../core/services/tournament.service';
import { Tournament } from '../core/models/models';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { ColorPicker } from '@acrodata/color-picker';

@Component({
  selector: 'app-create-tournament',
  standalone: true,
  imports: [
    MatFormFieldModule,
    MatInputModule,
    FormsModule,
    MatButtonModule,
    ColorPicker,
  ],
  templateUrl: './create-tournament.html',
  styleUrl: './create-tournament.css',
})
export class CreateTournament implements OnInit {
  @Output() tournamentCreated = new EventEmitter<Tournament | null>();

  form = {
    name: '',
    short_name: '',
    date: this.todayIso(),
    place: '',
    JTR: '',
    tugeny_link: '',
    color: '#000000',
    drive_dir: '/mnt/video/juggerData/tournois',
    tournament_dir: '',
  };
  private tournamentService = inject(TournamentService);

  ngOnInit(): void {
    this.form.date = this.todayIso();
  }

  onCreateTournament(): void {
    this.form.color = this.normalizeHexColor(this.form.color);
    const payload = {
      name: this.form.name.trim(),
      short_name: this.form.short_name.trim(),
      date: this.form.date,
      place: this.form.place.trim(),
      JTR: this.form.JTR.trim(),
      tugeny_link: this.form.tugeny_link.trim(),
      color: this.form.color || '#000000',
      drive_dir: this.form.drive_dir.trim() || '/mnt/video/juggerData/tournois',
      tournament_dir: this.form.tournament_dir.trim(),
    } as Partial<Tournament>;
    if (!payload.name || !payload.place || !payload.date) {
      return;
    }

    this.tournamentService.post(payload as any).subscribe({
      next: (created) => {
        this.form = {
          name: '',
          short_name: '',
          date: this.todayIso(),
          place: '',
          JTR: '',
          tugeny_link: '',
          color: '#000000',
          drive_dir: '/mnt/video/juggerData/tournois',
          tournament_dir: '',
        };
        this.tournamentCreated.emit(created);
      },
      error: (e) => {
        console.error('create tournament failed', e);
      },
    });
  }

  private normalizeHexColor(value: string): string {
    const raw = String(value ?? '').trim();
    const cleaned = raw.startsWith('#') ? raw.slice(1) : raw;
    if (/^[0-9a-fA-F]{6}$/.test(cleaned)) {
      return `#${cleaned.toUpperCase()}`;
    }
    return '#000000';
  }

  private todayIso(): string {
    const now = new Date();
    const year = now.getFullYear();
    const month = `${now.getMonth() + 1}`.padStart(2, '0');
    const day = `${now.getDate()}`.padStart(2, '0');
    return `${year}-${month}-${day}`;
  }
}
