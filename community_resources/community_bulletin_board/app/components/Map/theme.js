/**
 * theme.js
 *
 * Here is where the style considerations for use across all layers will be configured.
 *
 * */

export const ZoomBreakPoints = {
  START: 0,
  MID: 9,
  END: 18,
};

const colors = {
  primary: '#07818c',
  secondary: '#FF5B01',
  gunmetal: 'rgba(48, 50, 61, 1)',
  gray: 'rgba(77, 80, 97, 1)',
  offWhite: 'rgba(205, 209, 196, 1)',
};

const polygons = {
  lineJoin: 'round',
  lineWidth: {
    standard: {
      stops: [
        [ZoomBreakPoints.START, 1],
        [ZoomBreakPoints.MID, 4],
        [ZoomBreakPoints.END, 10],
      ],
    },
    dense: {
      stops: [
        [ZoomBreakPoints.START, 1],
        [ZoomBreakPoints.MID, 2],
        [ZoomBreakPoints.END, 4],
      ],
    },
  },
  lineOpacity: {
    standard: 0.8,
  },
  lineColor: colors.gunmetal,
  fillColor: ['case', ['==', ['get', 'geoid'], ''], colors.secondary, colors.primary],
  hoverColor: colors.primary,
  selectedColor: colors.secondary,
  fillOpacity: {
    standard: 0.6,
    selection: [
      'case',
      [
        'any',
        ['==', ['get', 'geoid'], '/*hover*/'],
        ['==', ['get', 'geoid'], '/*select*/'],
      ],
      0.8,
      0.1,
    ],
  },
};

const theme = {
  polygons,
};

export default theme;
