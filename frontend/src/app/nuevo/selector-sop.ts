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
      min-height: 2.25rem;
      padding: 0.4rem 0.6rem;
      border: 1px solid #b8c0ca;
      border-radius: 0.3rem;
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
      padding: 0.25rem;
      border: 1px solid #d8dde3;
      border-radius: 0.3rem;
    }
    .opcion {
      flex: none;
      display: flex;
      gap: 0.6rem;
      align-items: flex-start;
      min-height: 2.25rem;
      padding: 0.35rem 0.5rem;
      border-radius: 0.3rem;
      font-weight: 400;
      cursor: pointer;
    }
    .opcion:hover {
      background: #f2f4f7;
    }
    .opcion.elegida {
      background: #eff8ff;
      outline: 1px solid #84caff;
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
      font-variant-numeric: tabular-nums;
      color: #475467;
      white-space: nowrap;
    }
    .titulo {
      min-width: 0;
      overflow-wrap: anywhere;
    }
    .nota {
      margin: 0;
      color: #475467;
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
