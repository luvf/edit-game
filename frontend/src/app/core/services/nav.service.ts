import { Injectable, signal } from '@angular/core';

export type NavLink = {
  label: string;
  routerLink: string | string[];
  queryParams?: Record<string, unknown>;
};

export type NavAction = {
  label: string;
  onClick: () => void;
};

@Injectable({ providedIn: 'root' })
export class NavService {
  private readonly extraLinks = signal<NavLink[]>([]);
  private readonly actions = signal<NavAction[]>([]);

  links() {
    return this.extraLinks();
  }

  actionLinks() {
    return this.actions();
  }

  setLinks(links: NavLink[]) {
    this.extraLinks.set(links);
  }

  setActions(actions: NavAction[]) {
    this.actions.set(actions);
  }

  clear() {
    this.extraLinks.set([]);
    this.actions.set([]);
  }
}
