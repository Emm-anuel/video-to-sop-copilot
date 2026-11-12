import { Component, input, output, signal } from '@angular/core';
import { Evidencia1 as Evidencia } from '../api/sop';
import { describir } from './edicion';

/**
 * Lista editable como chips (equipo, roles, puntos de validación): quitar con la × de cada uno y
 * agregar con el campo de texto (Enter o el botón). No guarda estado: emite la lista nueva y
 * quien la usa la pasa por las funciones de `edicion.ts`.
 */
@Component({
  selector: 'app-chips',
  template: `
    <ul class="chips" [attr.aria-label]="etiqueta()">
      @for (v of valores(); track $index) {
        <li class="chip" [class.resaltado]="esInferido(v)" [title]="titulo(v)">
          <span>{{ v }}</span>
          @if (esInferido(v)) {
            <span class="leyenda-chip">Inferido</span>
          }
          <button
            type="button"
            class="quitar"
            [attr.aria-label]="'Quitar ' + v"
            (click)="quitar($index)"
          >
            ×
          </button>
        </li>
      }
    </ul>
    <div class="agregar">
      <input
        type="text"
        [id]="idCampo()"
        [attr.aria-label]="'Agregar a ' + etiqueta()"
        [placeholder]="'Agregar…'"
        [value]="nuevo()"
        (input)="nuevo.set($any($event.target).value)"
        (keydown.enter)="$event.preventDefault(); agregar()"
      />
      <button type="button" (click)="agregar()" [disabled]="!nuevo().trim()">Agregar</button>
    </div>
  `,
  styles: `
    :host {
      display: grid;
      gap: 0.35rem;
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 0.3rem;
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      padding: 0.1rem 0.2rem 0.1rem 0.5rem;
      background: #f2f4f7;
      border-radius: 0.3rem;
      font-size: 0.9rem;
      max-width: 100%;
      overflow-wrap: anywhere;
    }
    .chip.resaltado {
      background: #fffaeb;
      outline: 1px dashed #dc6803;
    }
    .leyenda-chip {
      color: #93370d;
      font-size: 0.75rem;
      font-weight: 600;
    }
    .quitar {
      min-width: 2.25rem;
      min-height: 2.25rem;
      padding: 0;
      border: 0;
      background: transparent;
      cursor: pointer;
      font-size: 1rem;
      line-height: 1;
    }
    .agregar {
      display: flex;
      gap: 0.3rem;
    }
    .agregar input {
      flex: 1;
      min-width: 0;
    }
  `,
})
export class Chips {
  readonly valores = input.required<readonly string[]>();
  readonly etiqueta = input.required<string>();
  readonly idCampo = input<string>('');
  /** La evidencia del paso (ADR-023) y el campo de la lista: el título de cada chip la muestra. */
  readonly evidencia = input<readonly Evidencia[]>([]);
  readonly campo = input('');
  /** El campo sigue en `campos_inferidos`: sus elementos sin evidencia se resaltan (RF-25). */
  readonly inferido = input(false);
  readonly cambio = output<string[]>();

  protected readonly nuevo = signal('');

  protected esInferido(v: string): boolean {
    return this.inferido() && this.buscar(v)?.fuente === 'inferido';
  }

  protected titulo(v: string): string {
    return describir(this.buscar(v));
  }

  private buscar(v: string): Evidencia | undefined {
    return this.evidencia().find((e) => e.campo === this.campo() && e.valor === v);
  }

  protected quitar(i: number): void {
    this.cambio.emit(this.valores().filter((_, j) => j !== i));
  }

  protected agregar(): void {
    const v = this.nuevo().trim();
    if (!v) {
      return;
    }
    this.nuevo.set('');
    this.cambio.emit([...this.valores(), v]);
  }
}
