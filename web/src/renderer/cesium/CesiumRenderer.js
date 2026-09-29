// CesiumJS: the renderer-facade implementation (Decision Record D12).
//
// The field is shown on the Earth: an offline Natural Earth II globe with a
// lat/lon grid, translucent only over the selected region so the water
// column beneath the sea surface stays visible. Each point is placed
// geodetically at its own longitude and latitude, with height equal to the
// exaggerated depth below the ellipsoid; a flat local frame would drift tens
// of kilometres off the curved surface across a regional selection.
// Exaggeration and colour are display state only: physical values are read
// from the decoded product itself and positions are recomputed from them.
//
// Every product is validated before the current layer is touched, so a
// refusal leaves the previous field displayed exactly as S7 still describes it.
import { BoundingSphere, buildModuleUrl, Cartesian3, Color, GridImageryProvider, HeadingPitchRange, ImageryLayer, PointPrimitiveCollection, Rectangle, ScreenSpaceEventHandler, ScreenSpaceEventType, TileMapServiceImageryProvider, Viewer, } from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import { logScaleProblem, normalise, paletteColour } from "../colour";
import { markerPick } from "../markers";
import { isGeographicCrs, sceneFrame, TransformError } from "../transform";
const POINT_PIXELS = 4;
const MARKER_PIXELS = 11;
const MARKER_FILL = Color.fromCssColorString("#ffcf5a");
const REGION_OUTLINE = Color.fromCssColorString("#9fd3ea").withAlpha(0.9);
export class CesiumRenderer {
    capabilities;
    listeners = new Set();
    viewer;
    handler;
    layer;
    display;
    hovered = null;
    markers;
    constructor(maximumPoints) {
        this.capabilities = { engine: "CesiumJS on WebGL2", maximumPoints };
    }
    mount(container) {
        try {
            this.viewer = new Viewer(container, {
                baseLayer: ImageryLayer.fromProviderAsync(TileMapServiceImageryProvider.fromUrl(buildModuleUrl("Assets/Textures/NaturalEarthII"))),
                baseLayerPicker: false, geocoder: false, homeButton: false,
                sceneModePicker: false, navigationHelpButton: false, animation: false,
                timeline: false, fullscreenButton: false, infoBox: false,
                selectionIndicator: false, showRenderLoopErrors: false,
                requestRenderMode: true, maximumRenderTimeChange: Infinity,
            });
        }
        catch {
            this.emit({ type: "unsupported", reason: "this browser cannot create the WebGL context the globe requires" });
            return;
        }
        const { scene } = this.viewer;
        this.viewer.imageryLayers.addImageryProvider(new GridImageryProvider({
            color: Color.WHITE.withAlpha(0.12), glowColor: Color.TRANSPARENT,
            backgroundColor: Color.TRANSPARENT, cells: 1,
        }));
        scene.globe.undergroundColor = Color.fromCssColorString("#07131f");
        scene.globe.translucency.frontFaceAlpha = 0.35;
        scene.screenSpaceCameraController.enableCollisionDetection = false;
        scene.renderError.addEventListener((_scene, error) => {
            this.emit({ type: "renderFailed", reason: `the globe stopped rendering: ${String(error)}` });
        });
        // CesiumJS does not rebuild its GPU resources after a context loss, so the
        // loss is reported as permanent rather than as a recoverable error.
        scene.canvas.addEventListener("webglcontextlost", (event) => {
            event.preventDefault();
            this.emit({ type: "contextLost", reason: "the graphics context was lost; reload the page to restore the view" });
        });
        this.handler = new ScreenSpaceEventHandler(scene.canvas);
        this.handler.setInputAction((movement) => this.hover(movement.endPosition), ScreenSpaceEventType.MOUSE_MOVE);
        this.handler.setInputAction((click) => this.select(click.position), ScreenSpaceEventType.LEFT_CLICK);
        // Start over the northern Indian Ocean.
        this.viewer.camera.setView({ destination: Cartesian3.fromDegrees(78, 5, 9_000_000) });
    }
    showPointField(descriptor, arrays) {
        const viewer = this.viewer;
        if (!viewer)
            return { status: "refused", reason: "the 3D view is not available" };
        if (descriptor.point_count > this.capabilities.maximumPoints) {
            return {
                status: "too-large",
                reason: `${descriptor.point_count} points exceed this view's limit of ${this.capabilities.maximumPoints}`,
                retryWithPoints: this.capabilities.maximumPoints,
            };
        }
        const product = descriptor.product;
        const bounds = extent(arrays.longitude, arrays.latitude);
        let frame;
        try {
            frame = sceneFrame(product.spatial_reference.crs, product.coordinates.units.depth, product.spatial_reference.vertical_positive, bounds);
        }
        catch (error) {
            if (error instanceof TransformError)
                return { status: "refused", reason: error.message };
            throw error;
        }
        // Valid from here on: only now is the previous field replaced.
        this.clear();
        const count = arrays.values.length;
        const index = new Uint32Array(count);
        const height = new Float64Array(count);
        const heightPerDepthUnit = -frame.depthSign * frame.depthToKm * 1000;
        let shown = 0;
        let deepest = 0;
        for (let i = 0; i < count; i++) {
            if (arrays.missingValueMask[i] || !Number.isFinite(arrays.values[i]))
                continue;
            index[shown] = i;
            height[shown] = arrays.depth[i] * heightPerDepthUnit;
            deepest = Math.min(deepest, height[shown]);
            shown++;
        }
        const collection = viewer.scene.primitives.add(new PointPrimitiveCollection());
        const exaggeration = this.display?.verticalExaggeration ?? 1;
        const points = new Array(shown);
        for (let k = 0; k < shown; k++) {
            const i = index[k];
            points[k] = collection.add({
                position: Cartesian3.fromDegrees(arrays.longitude[i], arrays.latitude[i], height[k] * exaggeration),
                pixelSize: POINT_PIXELS,
                color: Color.GRAY,
                id: k,
            });
        }
        this.layer = {
            collection, points, bounds, deepest, coloured: false, outline: [],
            source: arrays, index: index.subarray(0, shown), height: height.subarray(0, shown),
        };
        viewer.scene.globe.translucency.rectangle = Rectangle.fromDegrees(bounds.west, bounds.south, bounds.east, bounds.north);
        viewer.scene.globe.translucency.enabled = true;
        this.drawOutline(exaggeration);
        if (this.display)
            this.applyDisplay(this.display);
        this.flyToRegion();
        return { status: "shown", shownPoints: shown, hiddenMissingPoints: count - shown };
    }
    clear() {
        const viewer = this.viewer;
        const layer = this.layer;
        if (!viewer || !layer)
            return;
        viewer.scene.primitives.remove(layer.collection); // destroys its GPU resources
        for (const entity of layer.outline)
            viewer.entities.remove(entity);
        viewer.scene.globe.translucency.enabled = false;
        this.layer = undefined;
        this.setHovered(null);
        viewer.scene.requestRender();
    }
    showMarkers(set) {
        const viewer = this.viewer;
        if (!viewer)
            return { status: "refused", reason: "the 3D view is not available" };
        if (!isGeographicCrs(set.crs)) {
            return { status: "refused", reason: `marker coordinate reference system ${set.crs} is not supported by this view` };
        }
        this.clearMarkers();
        const collection = viewer.scene.primitives.add(new PointPrimitiveCollection());
        for (let i = 0; i < set.platformIds.length; i++) {
            collection.add({
                position: Cartesian3.fromDegrees(set.longitude[i], set.latitude[i], 0),
                pixelSize: MARKER_PIXELS,
                color: MARKER_FILL,
                outlineColor: Color.WHITE,
                outlineWidth: 2,
                // Never hidden behind the globe or the field: a marker is a handle.
                disableDepthTestDistance: Number.POSITIVE_INFINITY,
                id: { marker: i },
            });
        }
        this.markers = { collection, set };
        viewer.scene.requestRender();
        return { status: "shown", count: set.platformIds.length };
    }
    clearMarkers() {
        const viewer = this.viewer;
        if (!viewer || !this.markers)
            return;
        viewer.scene.primitives.remove(this.markers.collection); // releases GPU resources
        this.markers = undefined;
        viewer.scene.canvas.style.cursor = "";
        viewer.scene.requestRender();
    }
    applyDisplay(display) {
        const { minimum, maximum } = display.range;
        const problem = display.scale === "log" ? logScaleProblem(minimum, maximum) : null;
        if (problem)
            return { status: "refused", reason: problem }; // nothing changed
        const previous = this.display;
        this.display = display;
        const layer = this.layer;
        if (!layer || !this.viewer)
            return { status: "applied" };
        const { source, index } = layer;
        if (!previous || previous.verticalExaggeration !== display.verticalExaggeration) {
            const e = display.verticalExaggeration;
            for (let k = 0; k < layer.points.length; k++) {
                const i = index[k];
                layer.points[k].position = Cartesian3.fromDegrees(source.longitude[i], source.latitude[i], layer.height[k] * e);
            }
            this.drawOutline(e);
        }
        const recolour = !layer.coloured || !previous || previous.palette !== display.palette ||
            previous.scale !== display.scale || previous.opacity !== display.opacity ||
            previous.range.minimum !== minimum || previous.range.maximum !== maximum;
        if (recolour) {
            for (let k = 0; k < layer.points.length; k++) {
                const [r, g, b] = paletteColour(display.palette, normalise(source.values[index[k]], minimum, maximum, display.scale));
                layer.points[k].color = new Color(r, g, b, display.opacity);
            }
            layer.coloured = true;
        }
        this.viewer.scene.requestRender();
        return { status: "applied" };
    }
    command(command) {
        if (command.type === "resetCamera")
            this.flyToRegion();
    }
    onEvent(listener) {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }
    dispose() {
        this.clearMarkers();
        this.clear();
        this.handler?.destroy();
        if (this.viewer && !this.viewer.isDestroyed())
            this.viewer.destroy();
        this.viewer = undefined;
        this.listeners.clear();
    }
    // The region at the sea surface and at its deepest shown level, joined at
    // the corners, so depth and extent read at a glance.
    drawOutline(exaggeration) {
        const viewer = this.viewer;
        const layer = this.layer;
        if (!viewer || !layer)
            return;
        for (const entity of layer.outline)
            viewer.entities.remove(entity);
        const { west, east, south, north } = layer.bounds;
        const bottom = layer.deepest * exaggeration;
        const rectangle = Rectangle.fromDegrees(west, south, east, north);
        const corners = [[west, south], [east, south], [east, north], [west, north]];
        layer.outline = [
            viewer.entities.add({ rectangle: { coordinates: rectangle, height: 0, fill: false, outline: true, outlineColor: REGION_OUTLINE } }),
            viewer.entities.add({ rectangle: { coordinates: rectangle, height: bottom, fill: false, outline: true, outlineColor: REGION_OUTLINE.withAlpha(0.5) } }),
            ...corners.map(([lon, lat]) => viewer.entities.add({
                polyline: { positions: Cartesian3.fromDegreesArrayHeights([lon, lat, 0, lon, lat, bottom]), width: 1, material: REGION_OUTLINE.withAlpha(0.5) },
            })),
        ];
    }
    flyToRegion() {
        const viewer = this.viewer;
        const layer = this.layer;
        if (!viewer || !layer)
            return;
        const { west, east, south, north } = layer.bounds;
        const sphere = BoundingSphere.fromPoints([
            Cartesian3.fromDegrees(west, south), Cartesian3.fromDegrees(east, north),
            Cartesian3.fromDegrees(west, north), Cartesian3.fromDegrees(east, south),
        ]);
        viewer.camera.flyToBoundingSphere(sphere, {
            offset: new HeadingPitchRange(0, -0.62, sphere.radius * 2.6),
            duration: 1.2,
        });
    }
    markerIndexAt(position) {
        const viewer = this.viewer;
        const markers = this.markers;
        if (!viewer || !markers)
            return null;
        const picked = viewer.scene.pick(position);
        const id = picked?.collection === markers.collection ? picked.id : null;
        return id && typeof id.marker === "number" ? id.marker : null;
    }
    select(position) {
        const index = this.markerIndexAt(position);
        if (index !== null && this.markers) {
            this.emit({ type: "pick", marker: markerPick(this.markers.set, index) });
        }
    }
    hover(position) {
        const viewer = this.viewer;
        if (viewer)
            viewer.scene.canvas.style.cursor = this.markerIndexAt(position) !== null ? "pointer" : "";
        const layer = this.layer;
        if (!viewer || !layer)
            return;
        const picked = viewer.scene.pick(position);
        const point = picked?.collection === layer.collection && typeof picked.id === "number" ? picked.id : null;
        this.setHovered(point);
    }
    setHovered(point) {
        if (point === this.hovered)
            return;
        this.hovered = point;
        const layer = this.layer;
        let sample = null;
        if (point !== null && layer) {
            const i = layer.index[point];
            const { source } = layer;
            sample = { longitude: source.longitude[i], latitude: source.latitude[i], depth: source.depth[i], value: source.values[i] };
        }
        this.emit({ type: "hover", sample });
    }
    emit(event) {
        for (const listener of this.listeners)
            listener(event);
    }
}
function extent(longitude, latitude) {
    let west = Infinity, east = -Infinity, south = Infinity, north = -Infinity;
    for (let i = 0; i < longitude.length; i++) {
        west = Math.min(west, longitude[i]);
        east = Math.max(east, longitude[i]);
        south = Math.min(south, latitude[i]);
        north = Math.max(north, latitude[i]);
    }
    return { west, east, south, north };
}
