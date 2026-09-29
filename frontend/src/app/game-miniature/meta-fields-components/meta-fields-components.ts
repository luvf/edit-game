// Angular
import {
  Component,
  EventEmitter,
  inject,
  Input,
  OnInit,
  Output,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatSelectModule } from '@angular/material/select';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import {
  FormGroup,
  FormGroupDirective,
  ReactiveFormsModule,
} from '@angular/forms';
import { Yt_Video } from '../../core/models/models';

@Component({
  selector: 'app-meta-fields',
  standalone: true,
  imports: [
    CommonModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatIconModule,
    MatButtonModule,
    ReactiveFormsModule,
  ],
  templateUrl: `meta-fields-components.html`,
  styleUrl: 'meta-fields-components.css',
})
export class MetaFieldsComponent implements OnInit {
  @Input() formGroupName!: string;
  @Input() ytVideos: Yt_Video[] = [];
  @Input() selectedYtVideoHref: string | null = null;
  @Output() ytVideoSelected = new EventEmitter<string | null>();
  form!: FormGroup;

  private gameFormGroup: FormGroupDirective = inject(FormGroupDirective);

  ngOnInit(): void {
    this.form = this.gameFormGroup.control.get(this.formGroupName) as FormGroup;
  }

  onYtVideoSelected(href: string | null): void {
    this.ytVideoSelected.emit(href);
  }

  selectedYtVideo(): Yt_Video | null {
    const href = this.selectedYtVideoHref;
    if (!href) return null;
    return (
      this.ytVideos.find((video) => this.ytVideoHref(video) === href) ?? null
    );
  }

  selectedYtVideoUrl(): string | null {
    const videoId = this.selectedYtVideo()?.video_id;
    return videoId ? `https://www.youtube.com/watch?v=${videoId}` : null;
  }

  setPublicationToNow(): void {
    const date = new Date(Date.now() + 5 * 60 * 1000);
    this.form.patchValue({ publication_date: this.toDatetimeLocal(date) });
  }

  ytVideoHref(video: Yt_Video): string {
    return video._links?.self?.href ?? String(video.pk);
  }

  private toDatetimeLocal(date: Date): string {
    const pad = (n: number) => n.toString().padStart(2, '0');
    const yyyy = date.getFullYear();
    const mm = pad(date.getMonth() + 1);
    const dd = pad(date.getDate());
    const hh = pad(date.getHours());
    const mi = pad(date.getMinutes());
    return `${yyyy}-${mm}-${dd}T${hh}:${mi}`;
  }
}
