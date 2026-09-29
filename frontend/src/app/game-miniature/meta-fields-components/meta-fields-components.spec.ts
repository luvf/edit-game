import { ComponentFixture, TestBed } from '@angular/core/testing';

import { MetaFieldsComponent } from './meta-fields-components';

describe('MetaFieldsComponent', () => {
  let component: MetaFieldsComponent;
  let fixture: ComponentFixture<MetaFieldsComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [MetaFieldsComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(MetaFieldsComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
