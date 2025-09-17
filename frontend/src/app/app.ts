import { Component, signal } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import {RouterLink} from '@angular/router';

@Component({
  selector: 'app-root',
  imports: [RouterLink,RouterOutlet],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  protected readonly title = signal('frontend');
}
