import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ImagePreview } from './image-preview';

describe('ImagePreview', () => {
  let component: ImagePreview;
  let fixture: ComponentFixture<ImagePreview>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ImagePreview]
    })
    .compileComponents();

    fixture = TestBed.createComponent(ImagePreview);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
