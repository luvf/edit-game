// Angular
import {Component, EventEmitter, Input, Output} from '@angular/core';
import {CommonModule} from '@angular/common';
import {MatSelectModule} from '@angular/material/select';
import {MatInputModule} from '@angular/material/input';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatIconModule} from '@angular/material/icon';

@Component({
  selector: 'app-meta-fields',
  standalone: true,
  imports: [CommonModule, MatFormFieldModule, MatInputModule, MatSelectModule, MatIconModule],
  templateUrl: `meta-fields-components.html`,
  styleUrl: 'meta-fields-components.css'
})
export class MetaFieldsComponent {

  /**
   * Video title.
   *
   * Use together with `vidNameChange` to enable two-way binding:
   * [(vidName)]="model.vidName"
   */
  @Input() vidName: string | null = null;
  @Output() vidNameChange = new EventEmitter<string>();

  /**
   * Video description (can be long, Markdown/plain text).
   *
   * Use together with `descriptionChange` to enable two-way binding:
   * [(description)]="model.description"
   */
  @Input() description: string | null = null;
  @Output() descriptionChange = new EventEmitter<string>();

  /**
   * Publication date-time in local time (HTML input type "datetime-local" expected in the template).
   *
   * Use together with `publicationDateChange` to enable two-way binding:
   * [(publicationDate)]="model.publicationDate"
   *
   * Expected format: "YYYY-MM-DDThh:mm" (browser locale-dependent rendering).
   */
  @Input() publicationDate: string | null = null;
  @Output() publicationDateChange = new EventEmitter<string>();


}
