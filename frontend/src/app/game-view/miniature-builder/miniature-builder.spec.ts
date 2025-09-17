import { ComponentFixture, TestBed } from '@angular/core/testing';

import { MiniatureBuilder } from './miniature-builder';

describe('MiniatureBuilder', () => {
  let component: MiniatureBuilder;
  let fixture: ComponentFixture<MiniatureBuilder>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [MiniatureBuilder]
    })
    .compileComponents();

    fixture = TestBed.createComponent(MiniatureBuilder);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
