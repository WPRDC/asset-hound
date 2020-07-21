import { defaultAction } from '../../App/actions';
import { DEFAULT_ACTION } from '../../App/constants';

describe('BulletinBoard actions', () => {
  describe('Default Action', () => {
    it('has a type of DEFAULT_ACTION', () => {
      const expected = {
        type: DEFAULT_ACTION,
      };
      expect(defaultAction()).toEqual(expected);
    });
  });
});
