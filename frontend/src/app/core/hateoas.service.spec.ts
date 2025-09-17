import { TestBed } from '@angular/core/testing';

import { HateoasService } from './hateoas.service';

describe('HateoasService', () => {
  let service: HateoasService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(HateoasService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
