// The scene coordinate transform. Pure: no rendering engine involved.
//
// Every layer goes through this one local frame: kilometres east (x), up (y)
// and south (z) of the region's centre, using an equirectangular
// approximation that is adequate at regional scale. Vertical exaggeration is
// a display factor on y only and is fully reversible; physical values are
// never changed. A CRS or depth unit this frame does not understand is
// refused, not guessed.

const KM_PER_DEGREE_LATITUDE = 110.574;
const KM_PER_DEGREE_LONGITUDE_AT_EQUATOR = 111.32;

const GEOGRAPHIC_CRS = new Set(["EPSG:4326", "CF:latitude_longitude"]);
const DEPTH_UNIT_KM: Record<string, number> = {
  m: 0.001, metre: 0.001, metres: 0.001, meter: 0.001, meters: 0.001, km: 1,
};

export class TransformError extends Error {}

export interface SceneFrame {
  originLongitude: number;
  originLatitude: number;
  kmPerDegreeLongitude: number;
  depthToKm: number;
  /** +1 when depth increases downward, -1 when it increases upward. */
  depthSign: 1 | -1;
}

export function sceneFrame(
  crs: string, depthUnits: string | null | undefined, verticalPositive: "down" | "up",
  bounds: { west: number; east: number; south: number; north: number },
): SceneFrame {
  if (!GEOGRAPHIC_CRS.has(crs)) {
    throw new TransformError(`coordinate reference system ${crs} is not supported by this view`);
  }
  const depthToKm = DEPTH_UNIT_KM[(depthUnits ?? "").trim().toLowerCase()];
  if (depthToKm === undefined) {
    throw new TransformError(`depth units ${JSON.stringify(depthUnits)} are not understood`);
  }
  const originLatitude = (bounds.south + bounds.north) / 2;
  return {
    originLongitude: (bounds.west + bounds.east) / 2,
    originLatitude,
    kmPerDegreeLongitude: KM_PER_DEGREE_LONGITUDE_AT_EQUATOR * Math.cos(originLatitude * Math.PI / 180),
    depthToKm,
    depthSign: verticalPositive === "down" ? 1 : -1,
  };
}

/** Local position in km, before vertical exaggeration. */
export function toScene(frame: SceneFrame, longitude: number, latitude: number, depth: number): [number, number, number] {
  return [
    (longitude - frame.originLongitude) * frame.kmPerDegreeLongitude,
    -frame.depthSign * depth * frame.depthToKm,
    -(latitude - frame.originLatitude) * KM_PER_DEGREE_LATITUDE,
  ];
}

/** Inverse of toScene, used to report positions back in physical terms. */
export function fromScene(frame: SceneFrame, x: number, y: number, z: number): [number, number, number] {
  return [
    x / frame.kmPerDegreeLongitude + frame.originLongitude,
    -z / KM_PER_DEGREE_LATITUDE + frame.originLatitude,
    -y / (frame.depthSign * frame.depthToKm),
  ];
}

/** An exaggeration that makes the depth span a quarter of the widest span. */
export function suggestedExaggeration(horizontalSpanKm: number, depthSpanKm: number): number {
  if (!(depthSpanKm > 0) || !(horizontalSpanKm > 0)) return 1;
  const raw = (0.25 * horizontalSpanKm) / depthSpanKm;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  return Math.max(1, Math.round(raw / magnitude) * magnitude);
}
