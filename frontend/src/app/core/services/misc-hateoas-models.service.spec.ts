import { TestBed } from '@angular/core/testing';

import { MiscHateoasModelsService } from './misc-hateoas-models.service';

describe('MiscHateoasModelsService', () => {
  let service: MiscHateoasModelsService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(MiscHateoasModelsService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
