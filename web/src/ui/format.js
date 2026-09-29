// Display formatting shared by every panel.
/** "2024-09-05T09:00:00.000000000" or "…+00:00" → "2024-09-05 09:00 UTC".
 *  Source times are UTC; a non-zero offset is shown as given, never shifted. */
export function formatUtc(iso) {
    const offset = iso.match(/([+-]\d\d:\d\d)$/)?.[1];
    const stamp = iso.slice(0, 16).replace("T", " ");
    return offset && offset !== "+00:00" && offset !== "-00:00" ? `${stamp} ${offset}` : `${stamp} UTC`;
}
