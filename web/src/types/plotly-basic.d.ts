// The basic Plotly bundle exposes the same API as plotly.js, scatter traces only.
declare module "plotly.js-basic-dist-min" {
  import * as Plotly from "plotly.js";
  export = Plotly;
}
