import { TestBed } from '@angular/core/testing';

import VideoMetadataService from './video-metadata.service';

describe('VideoMetadataService', () => {
  let service: VideoMetadataService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(VideoMetadataService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
