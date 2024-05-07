/**
 *
 * Map
 *
 */

import React, { useEffect, useState } from 'react';
import InteractiveMap, {
  StaticMap,
  Source,
  Layer,
  NavigationControl,
} from 'react-map-gl';

import PropTypes from 'prop-types';

import styled from 'styled-components';
import { MAPBOX_API_TOKEN } from '../../settings';
import { DEFAULT_VIEWPORT, basemaps, getTheme } from './settings';
import { extractFeatureFromEvent } from './utils';
import { categorySchema } from '../../schemas';
import PopUp from './PopUp';
import Legend from './Legend';

// import { FormattedMessage } from 'react-intl';
// import messages from './messages';

const ControlDiv = styled.div`
  position: absolute;
  top: 1rem;
  right: 1rem;
`;

function Map({
  defaultViewport,
  sources,
  layers,
  isStatic,
  colorScheme,
  children,
  onAssetClick,
  categories,
  filter,
  searchTerm,
}) {
  const ReactMapGL = isStatic ? StaticMap : InteractiveMap;

  const startingViewport = { ...DEFAULT_VIEWPORT, ...defaultViewport };

  // Internal state
  const [viewport, setViewport] = useState(startingViewport);
  const [popup, setPopup] = useState(undefined);
  const [assetLayerFilter, setAssetLayerFilter] = useState(['has', 'name']);

  // Theming
  const mapStyle = basemaps[colorScheme];
  const { categoryColors, assetLayer } = getTheme(colorScheme);

  useEffect(() => {
    if (searchTerm) {
      setAssetLayerFilter([
        'all',
        filter,
        ['in', ['downcase', searchTerm], ['downcase', ['get', 'name']]],
      ]);
    } else {
      setAssetLayerFilter(filter);
    }
  }, [searchTerm, filter]);

  function closePopup() {
    setPopup(undefined);
  }

  function handleHover(event) {
    const feature = extractFeatureFromEvent(event);
    if (feature) {
      const [lng, lat] = event.lngLat;
      setPopup(
        <PopUp
          name={feature.properties.name}
          slug={feature.properties.category}
          type={feature.properties.asset_type_title}
          lat={lat}
          lng={lng}
          onClose={closePopup}
        />,
      );
    }
    if (!feature) {
      setPopup(undefined);
    }
  }

  function handleClick(event) {
    const feature = extractFeatureFromEvent(event);
    console.log(feature.properties, feature.properties.id);
    if (feature) {
      onAssetClick(feature.properties.id);
    }
  }

  return (
    <ReactMapGL
      mapboxApiAccessToken={MAPBOX_API_TOKEN}
      {...viewport}
      onViewportChange={v =>
        setViewport(Object.assign({}, v, { width: '100%', height: '100%' }))
      }
      mapStyle={mapStyle}
      onHover={handleHover}
      onClick={handleClick}
      interactiveLayerIds={['asset-points']}
    >
      <Source
        id="assets"
        type="vector"
        url="https://data.wprdc.org/tiles/table.asset_index._geom"
      >
        <Layer {...assetLayer} filter={assetLayerFilter} />
      </Source>

      {sources.map(source => (
        <Source {...source} />
      ))}

      {layers.map(layer => (
        <Layer {...layer} />
      ))}

      {children /* todo: ¿tightly define what goes in the map? */}

      {popup}

      {!!categories && (
        <Legend
          colors={categoryColors}
          categories={categories}
          backgroundColor="gray-500"
        />
      )}
      <ControlDiv style={{ right: 44 }}>
        <NavigationControl />
      </ControlDiv>
    </ReactMapGL>
  );
}

Map.propTypes = {
  defaultViewport: PropTypes.shape({
    width: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    height: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    latitude: PropTypes.number,
    longitude: PropTypes.number,
    zoom: PropTypes.number,
    pitch: PropTypes.number,
  }),
  sources: PropTypes.arrayOf(PropTypes.object),
  layers: PropTypes.arrayOf(PropTypes.object),
  isStatic: PropTypes.bool,
  colorScheme: PropTypes.string,
  children: PropTypes.node,
  onAssetClick: PropTypes.func,
  categories: PropTypes.arrayOf(PropTypes.shape(categorySchema)),
  filter: PropTypes.array,
  searchTerm: PropTypes.string,
};

Map.defaultProps = {
  sources: [],
  layers: [],
};

export default Map;
