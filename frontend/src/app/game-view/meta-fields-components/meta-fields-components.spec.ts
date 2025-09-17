import { ComponentFixture, TestBed } from '@angular/core/testing';

import { MetaFieldsComponents } from './meta-fields-components';

describe('MetaFieldsComponents', () => {
  let component: MetaFieldsComponents;
  let fixture: ComponentFixture<MetaFieldsComponents>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [MetaFieldsComponents]
    })
    .compileComponents();

    fixture = TestBed.createComponent(MetaFieldsComponents);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
