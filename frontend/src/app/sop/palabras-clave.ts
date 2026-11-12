import { Component, input, output } from '@angular/core';
import { PalabraClave } from '../api/sop';
import { mmss } from './edicion';

/**
 * Palabras clave del SOP (RF-24), solo lectura: las menciones las cuenta el código. En pantallas
 * angostas (RNF-13) cada palabra es una tarjeta: término, categoría y menciones arriba, y los
 * segundos abajo en varias líneas; si el propio componente mide 34 rem o más (container query,
 * no el ancho de la ventana), filas alineadas como una tabla. Con video, cada
 * segundo es un botón que lo abre en ese segundo (`abrir`); sin video, solo texto.
 */
@Component({
  selector: 'app-palabras-clave',
  template: `
    <div class="cabecera" aria-hidden="true">
      <span>Término</span><span>Categoría</span><span>Menciones</span><span>Segundos</span>
    </div>
    <ul class="palabras">
      @for (x of palabras(); track $index) {
        <li class="palabra" [title]="x.literal ? 'Dicho como «' + x.literal + '»' : ''">
          <span class="termino">{{ x.termino }}</span>
          <span class="categoria">{{ x.categoria }}</span>
          <span class="menciones"
            >{{ x.menciones }} {{ x.menciones === 1 ? 'mención' : 'menciones' }}</span
          >
          <span class="segundos">
            @for (t of x.t; track $index) {
              @if (conVideo()) {
                <button
                  type="button"
                  class="enlace-t"
                  [attr.aria-label]="'Ver «' + x.termino + '» en el video en ' + mmss(t)"
                  (click)="abrir.emit(t)"
                >
                  {{ mmss(t) }}
                </button>
              } @else {
                <span class="t">{{ mmss(t) }}</span>
              }
            }
          </span>
        </li>
      }
    </ul>
  `,
  styles: `
    :host {
      display: block;
      container-type: inline-size;
    }
    .palabras {
      display: grid;
      gap: 0.5rem;
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .palabra {
      display: flex;
      flex-wrap: wrap;
      gap: 0.25rem 0.6rem;
      align-items: baseline;
      padding: 0.6rem;
      border: 1px solid #eaecf0;
      border-radius: 0.3rem;
      font-size: 0.9rem;
    }
    .termino {
      font-weight: 600;
      overflow-wrap: anywhere;
    }
    .categoria,
    .menciones {
      color: #475467;
    }
    .segundos {
      display: flex;
      flex-basis: 100%;
      flex-wrap: wrap;
      gap: 0.35rem;
    }
    .enlace-t {
      min-width: 2.25rem;
      min-height: 2.25rem;
      padding: 0 0.5rem;
      color: #175cd3;
      border-color: #b2ddff;
      font-variant-numeric: tabular-nums;
    }
    .t {
      color: #475467;
      font-variant-numeric: tabular-nums;
    }
    .cabecera {
      display: none;
    }
    @container (min-width: 34rem) {
      .cabecera,
      .palabra {
        display: grid;
        grid-template-columns: minmax(6rem, 1fr) 6rem 6.5rem 2fr;
        gap: 0.6rem;
        align-items: start;
      }
      .cabecera {
        padding: 0 0.6rem 0.3rem;
        font-weight: 600;
        font-size: 0.9rem;
      }
      .segundos {
        flex-basis: auto;
      }
    }
  `,
})
export class PalabrasClave {
  readonly palabras = input.required<readonly PalabraClave[]>();
  /** Si hay video: los segundos son botones que lo abren. */
  readonly conVideo = input(false);
  readonly abrir = output<number>();

  protected readonly mmss = mmss;
}
