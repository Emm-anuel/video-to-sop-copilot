import { Component, computed, input, output, signal } from '@angular/core';
import { SopResumen } from '../api/tipos';
import { coincide } from '../biblioteca/filtro';

/**
 * Elegir el SOP de referencia de la biblioteca en `/nuevo` (RF-07): búsqueda por título o código
 * y una lista de opciones con código y título. La lista tiene alto máximo con scroll, así que una
 * biblioteca grande no empuja el resto del formulario. Cada opción mide al menos 36 px (RNF-13).
 */
@Component({
  selector: 'app-selector-sop',
  template: `
    <label class="buscar">
      <span>Buscar en la biblioteca</span>
      <input
        type="search"
        placeholder="Título o código"
        [value]="consulta()"
        (input)="consulta.set($any($event.target).value)"
        [disabled]="deshabilitado()"
      />
    </label>
    @if (visibles().length) {
      <div class="opciones" role="radiogroup" aria-label="SOP de referencia">
        @for (s of visibles(); track s.id) {
          <label class="opcion" [class.elegida]="s.id === elegido()">
            <input
              type="radio"
              name="sop-referencia"
              [value]="s.id"
              [checked]="s.id === elegido()"
              [disabled]="deshabilitado()"
              (change)="elegir.emit(s.id)"
            />
            <span class="texto">
              <span class="codigo">{{ s.codigo }}</span>
              <span class="titulo">{{ s.titulo }}</span>
            </span>
          </label>
        }
      </div>
    } @else {
      <p class="nota">Ningún SOP coincide con «{{ consulta() }}».</p>
    }
  `,
  styles: `
    :host {
      display: grid;
      gap: 0.5rem;
    }
    .buscar {
      display: grid;
      gap: 0.35rem;
      font-weight: 600;
    }
    input[type='search'] {
      background: var(--sup);
    }
    input[type='search'] {
      min-height: 2.25rem;
      padding: 0.4rem 0.6rem;
      border: 1px solid var(--linea-2);
      border-radius: var(--r1);
      font: inherit;
      font-weight: 400;
    }
    /* Columna flex y no grid: con alto máximo, una rejilla encoge las filas y se enciman. */
    .opciones {
      display: flex;
      flex-direction: column;
      gap: 0.25rem;
      max-height: 18rem;
      overflow-y: auto;
      padding: 0.3rem;
      background: var(--fondo);
      border: 1px solid var(--linea);
      border-radius: var(--r1);
      scrollbar-width: thin;
    }
    .opcion {
      flex: none;
      display: flex;
      gap: 0.6rem;
      align-items: flex-start;
      min-height: 2.25rem;
      padding: 0.35rem 0.5rem;
      border-radius: var(--r1);
      font-weight: 400;
      cursor: pointer;
    }
    .opcion:hover {
      background: var(--sup);
    }
    .opcion.elegida {
      background: var(--acento-bg);
      outline: 1.5px solid var(--acento);
    }
    .opcion input {
      flex: none;
      margin: 0.3rem 0 0;
    }
    .texto {
      display: flex;
      flex-wrap: wrap;
      gap: 0 0.6rem;
      min-width: 0;
    }
    .codigo {
      font-family: var(--mono);
      font-size: 0.85rem;
      font-weight: 500;
      color: var(--acento-2);
      white-space: nowrap;
    }
    .titulo {
      min-width: 0;
      overflow-wrap: anywhere;
    }
    .nota {
      margin: 0;
      color: var(--tinta-2);
      font-size: 0.9rem;
    }
  `,
})
export class SelectorSop {
  readonly sops = input.required<readonly SopResumen[]>();
  readonly elegido = input<number | null>(null);
  readonly deshabilitado = input(false);
  readonly elegir = output<number>();

  protected readonly consulta = signal('');
  /** Las que coinciden con la búsqueda; la elegida no se esconde aunque no coincida. */
  protected readonly visibles = computed(() =>
    this.sops().filter((s) => s.id === this.elegido() || coincide(s, this.consulta())),
  );
}
