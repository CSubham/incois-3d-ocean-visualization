// Formatting for surface readouts and legends.

/** CF/UDUNITS spellings shown the way people read them. */
export function displayUnits(units: string): string {
  const u = units.trim();
  if (/^(degree_?C(elsius)?|degC|celsius|°C)$/i.test(u)) return "°C";
  if (/^(m\/s|m s-1|m\.s-1|m s\^-1)$/i.test(u)) return "m/s";
  return u;
}

const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

/** Direction the water flows toward, clockwise from north. */
export function flowBearing(eastward: number, northward: number): { degrees: number; compass: string } {
  const degrees = (Math.atan2(eastward, northward) * 180 / Math.PI + 360) % 360;
  return { degrees, compass: COMPASS[Math.round(degrees / 45) % 8] };
}

export function formatPosition(longitude: number, latitude: number): string {
  const lat = `${Math.abs(latitude).toFixed(2)}°${latitude >= 0 ? "N" : "S"}`;
  const lonWrapped = ((longitude + 540) % 360) - 180;
  const lon = `${Math.abs(lonWrapped).toFixed(2)}°${lonWrapped >= 0 ? "E" : "W"}`;
  return `${lat} ${lon}`;
}
