// Angular
import {Component, inject, Input, OnInit} from '@angular/core';
import {CommonModule} from '@angular/common';
import {MatSelectModule} from '@angular/material/select';
import {MatInputModule} from '@angular/material/input';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatIconModule} from '@angular/material/icon';
import {FormGroup, FormGroupDirective, ReactiveFormsModule} from '@angular/forms';

@Component({
  selector: 'app-meta-fields',
  standalone: true,
  imports: [CommonModule, MatFormFieldModule, MatInputModule, MatSelectModule, MatIconModule, ReactiveFormsModule],
  templateUrl: `meta-fields-components.html`,
  styleUrl: 'meta-fields-components.css'
})
export class MetaFieldsComponent implements OnInit {

  @Input() formGroupName!: string;
  form!: FormGroup;

  private gameFormGroup: FormGroupDirective = inject(FormGroupDirective)

  ngOnInit(): void {
    this.form = this.gameFormGroup.control.get(this.formGroupName) as FormGroup
  }

}
