/** The object picker: one card per object, the chosen one raised. */

export interface ShelfItem {
  name: string;
  label: string;
  thumbnail: string;
  available: boolean;
  note?: string; // shown under the name, e.g. why a card is disabled
}

export class Shelf {
  private buttons = new Map<string, HTMLButtonElement>();

  constructor(
    private readonly list: HTMLUListElement,
    private readonly onPick: (name: string) => void,
  ) {}

  render(items: ShelfItem[], selected: string): void {
    this.list.replaceChildren();
    this.buttons.clear();
    for (const item of items) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'card';
      button.disabled = !item.available;
      button.setAttribute('aria-pressed', String(item.name === selected));

      const thumb = document.createElement('img');
      thumb.className = 'card__thumb';
      thumb.src = item.thumbnail;
      thumb.alt = '';
      thumb.width = 74;
      thumb.height = 74;
      thumb.loading = 'lazy';
      thumb.decoding = 'async';

      const name = document.createElement('span');
      name.className = 'card__name';
      name.textContent = item.label;
      button.append(thumb, name);

      if (item.note) {
        const note = document.createElement('span');
        note.className = 'card__note';
        note.textContent = item.note;
        button.append(note);
      }
      button.addEventListener('click', () => this.onPick(item.name));
      const entry = document.createElement('li');
      entry.append(button);
      this.list.append(entry);
      this.buttons.set(item.name, button);
    }
  }

  select(name: string): void {
    this.buttons.forEach((button, key) => button.setAttribute('aria-pressed', String(key === name)));
    this.buttons.get(name)?.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
  }

  setBusy(busy: boolean): void {
    this.list.setAttribute('aria-busy', String(busy));
  }
}
