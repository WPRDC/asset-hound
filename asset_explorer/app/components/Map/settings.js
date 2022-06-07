export const basemaps = {
  dark: 'mapbox://styles/stevendsaylor/ckd6iq0n702if1inv6rbbq5bg', // Basic/Dark
  light: 'mapbox://styles/mapbox/streets-v11', // Basic/Light
};

export const DEFAULT_VIEWPORT = {
  width: '100%',
  height: '100%',
  latitude: 40.440624,
  longitude: -79.995888,
  zoom: 12,
};

export const CARTO_USER = 'wprdc';
export const MAPS_API_ENDPOINT = `https://${CARTO_USER}.carto.com/api/v1/map`;
// get a better query for this
export const CARTO_SQL = `SELECT id, cartodb_id, name, asset_type, asset_type_title,category, the_geom, the_geom_webmercator FROM wprdc.assets_v1`;

// #a6cee3
// #1f78b4
// #b2df8a
// #33a02c
// #fb9a99
// #e31a1c
// #fdbf6f
// #ff7f00
// #cab2d6

const categoryColors = colorScheme =>
  ({
    dark: {
      'non-profit': '#fbb4ae',
      transportation: '#b3cde3',
      business: '#ccebc5',
      housing: '#decbe4',
      health: '#fed9a6',
      food: '#ffffcc',
      'education/youth': '#e5d8bd',
      'community-center': '#fddaec',
      civic: '#f2f2f2',
    },
    light: {
      'non-profit': '#555',
      transportation: '#1f78b4',
      business: '#b2df8a',
      housing: '#33a02c',
      health: '#fb9a99',
      food: '#e31a1c',
      'education/youth': '#fdbf6f',
      'community-center': '#ff7f00',
      civic: '#cab2d6',
    },
  }[colorScheme]);

/**
 * Generates Mapbox experession that colors map points based on category
 * @param colorScheme
 * @returns {(string|string[]|string)[]}
 */
const colorExpression = colorScheme => [
  'match',
  ['get', 'category'],
  ...Object.entries(categoryColors(colorScheme)).reduce(
    (expression, [cat, color]) => [...expression, [cat], color],
    [],
  ),
  'hsl(0, 0%, 0%)',
];

const assetLayer = colorScheme => ({
  id: 'asset-points',
  source: 'assets',
  'source-layer': 'assets',
  type: 'circle',
  paint: {
    'circle-radius': [
      'interpolate',
      ['cubic-bezier', 0.5, 0, 0.5, 1],
      ['zoom'],
      8,
      1,
      22,
      12,
    ],
    'circle-color': colorExpression(colorScheme),
    'circle-stroke-width': 1,
    'circle-stroke-opacity': { stops: [[0, 0], [9, 0], [12, 0.1], [14, 0.3]] },
  },
});

/**
 * Returns themed map layer and corresponding set of colors for use in overlays.
 * @param {string} colorScheme
 * @returns {{categoryColors: {business: string, housing: string, 'education/youth': string, 'non-profit': string, health: string, 'community-center': string, food: string, civic: string, transportation: string}, assetLayer: {paint: {'circle-color': *, 'circle-radius': (string|(string|number)[]|string[]|number)[]}, id: string, source: string, 'source-layer': string, type: string}}}
 */
export function getTheme(colorScheme) {
  return {
    assetLayer: assetLayer(colorScheme),
    categoryColors: categoryColors(colorScheme),
  };
}

export const DEFAULT_BASEMAP = basemaps.dark;
