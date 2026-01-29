import { Component, inject, signal } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import {RouterLink} from '@angular/router';
import {NavService} from './core/services/nav.service';

@Component({
  selector: 'app-root',
  imports: [RouterLink,RouterOutlet],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  protected readonly title = signal('frontend');
  private readonly navService = inject(NavService);
  navLinks = () => this.navService.links();
  navActions = () => this.navService.actionLinks();
}
