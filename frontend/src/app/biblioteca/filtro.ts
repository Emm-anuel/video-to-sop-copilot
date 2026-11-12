import { SopResumen } from '../api/tipos';

/** Sin acentos ni mayúsculas ni espacios de más: "Válvula" y "valvula" coinciden. */
export function normalizar(texto: string): string {
  return texto
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}

/** Si el SOP coincide con la búsqueda por título o por código ("sop-0003" o "0003"). */
export function coincide(sop: SopResumen, consulta: string): boolean {
  const q = normalizar(consulta);
  return !q || normalizar(sop.titulo).includes(q) || normalizar(sop.codigo).includes(q);
}

/** Fecha corta en español de México ("12 nov 2026"). */
export function fechaCorta(iso: string): string {
  const fecha = new Date(iso);
  return Number.isNaN(fecha.getTime())
    ? ''
    : new Intl.DateTimeFormat('es-MX', { dateStyle: 'medium' }).format(fecha);
}
